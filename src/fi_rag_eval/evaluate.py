"""The eval run: golden set + corpus -> outcomes -> metrics, once per grid cell.

There is deliberately no skip path. Every question in the golden set produces an
outcome or the run fails, because a metric averaged over a silently reduced N is
the worst output this harness could produce.

Slice 3 turns one run into eight. A **cell** is one analyser crossed with one
`ts_rank` normalisation setting, and every cell scores the same 21 questions
against the same 82 chunks -- only the normalisation of the text differs. That is
what makes a delta between two cells attributable: nothing else moved.

The two changes are measured **together, as a grid**, rather than in sequence,
because they interact. Compound splitting inflates the number of lexemes in a
chunk, and `ts_rank` at normalisation 0 rewards accumulated term weight, so
running the analyser change first and the normalisation change afterwards would
confound exactly the interaction worth seeing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import psycopg

from fi_rag_eval import db
from fi_rag_eval.analyse import Analyser, Morphology
from fi_rag_eval.golden import GoldenSet, Question
from fi_rag_eval.manifest import Manifest
from fi_rag_eval.metrics import Metrics, Miss, MissKind, QuestionOutcome, compute

DEFAULT_K = 5


class EvaluationError(RuntimeError):
    """The run could not be completed honestly, so it was not completed at all."""


@dataclass(frozen=True, slots=True)
class Cell:
    """One point in the grid: an analyser and a `ts_rank` normalisation setting."""

    analyser: Analyser
    normalisation: int

    @property
    def name(self) -> str:
        return f"{self.analyser}/{self.normalisation}"

    @property
    def short(self) -> str:
        """A column-heading-width name, for the per-question pass matrix."""
        initials = "".join(part[0] for part in str(self.analyser).split("-"))
        return f"{initials}{self.normalisation}"


GRID: tuple[Cell, ...] = tuple(
    Cell(analyser, normalisation) for analyser in Analyser for normalisation in db.NORMALISATIONS
)
"""All eight cells. Fixed, because the recorded baseline names every one of them."""

PUBLISHED = Cell(Analyser.SNOWBALL, 0)
"""The cell the README quotes.

Deliberately **not** "whichever cell won". Moving the published headline is the
Owner's explicit decision and comes with a deliberate re-baseline; a number that
migrates to whichever configuration happens to score best is how a project ends
up publishing its own tuning noise.
"""


@dataclass(frozen=True, slots=True)
class QuestionRun:
    """One question's full trace, kept so the table can be read, not just believed."""

    question: Question
    authority_key: str
    effective_date: date
    lexemes: tuple[str, ...]
    hits: tuple[db.Hit, ...]
    outcome: QuestionOutcome


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    """One cell, scored over the whole golden set."""

    k: int
    cell: Cell
    runs: tuple[QuestionRun, ...]
    metrics: Metrics

    def by_authority(self) -> tuple[tuple[str, Metrics], ...]:
        """The same metrics computed per authority, as a diagnostic (slice 4, D11).

        `metrics` is pooled over every question in the set, and it is the pooled
        number that carries the statistical power the golden set was grown to buy.
        These rows sit beneath it the way per-chunk recall and MRR already sit
        beneath complete-set recall: they say *where* the pooled number comes from,
        and neither of them is the headline.

        A per-authority row over ~25 questions cannot register an improvement on
        its own -- six discordant questions are needed for p<0.05 either way -- so
        reading one as a verdict on an authority is the mistake this docstring
        exists to prevent.
        """
        groups: dict[str, list[QuestionOutcome]] = {}
        for run in self.runs:
            groups.setdefault(run.authority_key, []).append(run.outcome)
        return tuple((key, compute(runs, k=self.k)) for key, runs in sorted(groups.items()))


@dataclass(frozen=True, slots=True)
class GridRun:
    """Every cell, plus the identity of the analyser that produced them.

    `fingerprint` is what makes the numbers reproducible. `libvoikko` reports the
    library version but not the dictionary version, so without hashing the
    analyser's own output a `voikko-fi` upgrade would move every published metric
    with no code change.
    """

    k: int
    cells: tuple[EvaluationRun, ...]
    library_version: str
    fingerprint: str

    def cell(self, cell: Cell) -> EvaluationRun:
        for run in self.cells:
            if run.cell == cell:
                return run
        raise EvaluationError(f"this run has no {cell.name} cell")

    @property
    def published(self) -> EvaluationRun:
        return self.cell(PUBLISHED)

    @property
    def best(self) -> EvaluationRun:
        """Highest complete-set recall, ties broken by grid order, not by luck."""
        return max(self.cells, key=lambda run: (run.metrics.complete_set_recall,))


def _resolve_labels(conn: psycopg.Connection[tuple[object, ...]], golden: GoldenSet) -> None:
    """Every label must point at a chunk that exists. No exceptions, no skips."""
    wanted = [address for q in golden.questions for address in q.required_addresses]
    present = db.resolve_addresses(conn, wanted)
    missing = sorted(set(wanted) - present)
    if missing:
        detail = "\n".join(
            f"  {q.id}: {address}"
            for q in golden.questions
            for address in q.required_addresses
            if address in set(missing)
        )
        raise EvaluationError(
            "these golden labels do not resolve to a chunk in the corpus:\n"
            f"{detail}\n"
            "An unresolvable label is a hard error, never a skipped question: the "
            "alternative is a metric computed over a smaller N than the table claims."
        )


def assert_one_authority(hits: Sequence[db.Hit], authority_key: str, question_id: str) -> None:
    """No hit may come from another authority. The hard filter, verified per run.

    `db.search` applies the authority filter in the WHERE clause, before ranking,
    so a foreign chunk is never a candidate (ADR-0002). That is the *design*; this
    is the *check*, and it lives inside `evaluate` rather than only in a unit test
    for one reason -- it cannot be skipped. Every question of every cell of every
    run passes through it, so the filter cannot silently regress into a
    post-ranking filter, or be dropped when the column is absent, without the run
    going red.

    What this verifies is **retrieval-layer isolation**, not refusal. A resident
    asking municipality A's question with municipality B's filter set must be
    *refused*, and refusing needs an answer to refuse; that is why the hard-filter
    debt closes PARTIAL and not CLOSED (slice 4, D9/D12).
    """
    foreign = [
        (hit.position, hit.address, hit.authority_key)
        for hit in hits
        if hit.authority_key != authority_key
    ]
    if foreign:
        raise EvaluationError(
            f"{question_id}: the top {len(hits)} for authority {authority_key!r} contains "
            f"chunks from another authority: {foreign}.\n"
            "The authority filter is the product's #1 failure mode (DESIGN.md:15,67): it "
            "makes a cross-jurisdiction answer structurally impossible rather than merely "
            "discouraged. A leak here means a resident can be told another municipality's "
            "rules with a correct-looking citation, so the run fails rather than reporting "
            "a number computed over mixed jurisdictions."
        )


def question_stopwords(
    conn: psycopg.Connection[tuple[object, ...]],
    golden: GoldenSet,
    morphology: Morphology,
) -> frozenset[str]:
    """The stopword decision for the golden set's own words, asked of Postgres.

    Computed once for the whole set and shared by every lemma cell, so a question
    is stopped identically on the query side and the index side.
    """
    return db.snowball_stopwords(
        conn, [word for q in golden.questions for word in morphology.words(q.question)]
    )


def cell_query_lexemes(
    conn: psycopg.Connection[tuple[object, ...]],
    text: str,
    cell: Cell,
    *,
    morphology: Morphology | None,
    stopwords: frozenset[str],
) -> list[str]:
    """Normalise a question the same way this cell's index was normalised.

    The snowball cell goes through Postgres, the lemma cells through the same
    Python function that built their columns. Either way one component normalises
    both sides -- the discipline the double-stemming bug was a violation of.
    """
    if not cell.analyser.lemmatising:
        return db.query_lexemes(conn, text)
    if morphology is None:  # pragma: no cover - callers below always supply one
        raise EvaluationError(f"{cell.name} needs a morphological analyser")
    return morphology.query_lexemes(text, cell.analyser, stopwords=stopwords)


def evaluate_grid(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    manifest: Manifest,
    golden: GoldenSet,
    k: int = DEFAULT_K,
    morphology: Morphology | None = None,
    cells: Sequence[Cell] = GRID,
) -> GridRun:
    """Score every cell. One corpus, one golden set, eight normalisations.

    Cells are scored in a fixed order and the analyser's fingerprint is captured
    with them, so the recorded baseline names both what was measured and what
    measured it.
    """
    analyser = morphology or Morphology.open()
    stopwords = question_stopwords(conn, golden, analyser)
    return GridRun(
        k=k,
        library_version=analyser.library_version,
        fingerprint=analyser.fingerprint(),
        cells=tuple(
            evaluate(
                conn,
                manifest=manifest,
                golden=golden,
                k=k,
                cell=cell,
                morphology=analyser,
                stopwords=stopwords,
            )
            for cell in cells
        ),
    )


def evaluate(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    manifest: Manifest,
    golden: GoldenSet,
    k: int = DEFAULT_K,
    cell: Cell = PUBLISHED,
    morphology: Morphology | None = None,
    stopwords: frozenset[str] | None = None,
) -> EvaluationRun:
    """Score one cell over the whole golden set."""
    if k < 1:
        raise EvaluationError(f"k must be at least 1, got {k}")
    _resolve_labels(conn, golden)
    if cell.analyser.lemmatising:
        morphology = morphology or Morphology.open()
        if stopwords is None:
            stopwords = question_stopwords(conn, golden, morphology)
    stopwords = stopwords if stopwords is not None else frozenset()

    runs: list[QuestionRun] = []
    for question in golden.questions:
        authority = manifest.resolve_municipality(question.municipality)
        # Slice 1 ingests one document version per authority; when a second
        # arrives the golden entry will have to name which one it labels.
        if len(authority.sources) != 1:
            raise EvaluationError(
                f"{question.id}: authority {authority.key!r} has "
                f"{len(authority.sources)} document versions, so the question must "
                "say which one it is labelled against."
            )
        effective_date = authority.sources[0].effective_date

        lexemes = cell_query_lexemes(
            conn, question.question, cell, morphology=morphology, stopwords=stopwords
        )
        if not lexemes:
            raise EvaluationError(
                f"{question.id}: the question normalises to zero lexemes under the "
                f"{cell.name} analyser, so it cannot be retrieved for at all. Fix the "
                "question rather than scoring it as a miss."
            )
        tsquery = db.or_tsquery(lexemes)
        hits = db.search(
            conn,
            tsquery=tsquery,
            authority_key=authority.key,
            effective_date=effective_date,
            limit=k,
            analyser=cell.analyser,
            normalisation=cell.normalisation,
        )
        assert_one_authority(hits, authority.key, question.id)
        retrieved = tuple(hit.address for hit in hits)
        required = set(question.required_addresses)
        # Leakage: how much of the question's vocabulary its own targets already
        # hand it. Computed before anything about retrieval is considered, because
        # it is a property of the golden set, not of the retriever.
        target_lexemes = db.chunk_lexemes(conn, question.required_addresses, cell.analyser)
        leaked = tuple(lexeme for lexeme in lexemes if lexeme in target_lexemes)
        missed = sorted(required - set(retrieved))
        reachable = db.addresses_matching(
            conn, addresses=missed, tsquery=tsquery, analyser=cell.analyser
        )
        misses = tuple(
            Miss(
                address=address,
                kind=MissKind.RANKED_OUT if address in reachable else MissKind.ZERO_OVERLAP,
            )
            for address in missed
        )
        runs.append(
            QuestionRun(
                question=question,
                authority_key=authority.key,
                effective_date=effective_date,
                lexemes=tuple(lexemes),
                hits=tuple(hits),
                outcome=QuestionOutcome(
                    question_id=question.id,
                    required=question.required_addresses,
                    retrieved=retrieved,
                    misses=misses,
                    query_lexemes=tuple(lexemes),
                    leaked_lexemes=leaked,
                ),
            )
        )

    if len(runs) != len(golden.questions):  # pragma: no cover - the loop cannot skip
        raise EvaluationError(
            f"scored {len(runs)} of {len(golden.questions)} questions; refusing to "
            "report a table over a reduced N"
        )
    return EvaluationRun(
        k=k,
        cell=cell,
        runs=tuple(runs),
        metrics=compute([run.outcome for run in runs], k=k),
    )

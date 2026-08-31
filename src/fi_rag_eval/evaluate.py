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
from fi_rag_eval.golden import GoldenSet, Question, RefusalKind, RefusalQuestion
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

PUBLISHED = Cell(Analyser.LEMMA_REASM, 0)
"""The cell the README quotes.

Deliberately **not** "whichever cell won". Moving the published headline is the
Owner's explicit decision and comes with a deliberate re-baseline; a number that
migrates to whichever configuration happens to score best is how a project ends
up publishing its own tuning noise.

**Moved from `snowball/0` to `lemma-reasm/0` by the Owner on 27 Aug 2026** — the
first time this project had evidence rather than a preference. At N=21 no
comparison in the grid could reach p<0.05 at any effect size, so "0.857 beats
0.762" was never a claim the instrument could support. At N=50 this cell beats
the old control on the **paired** exact McNemar test: 9 discordant questions, 8
of them in its favour, **p=0.039**. See ADR-0007 for the decision and its costs.

The costs are real and were accepted, not discovered afterwards: the published
leakage figure rises 0.332 -> 0.550 because a lemmatising analyser sees overlap
snowball stems apart -- **a property of the analyser, not of the questions** --
and the instrument spends power, because this cell fails 9 of 50 rather than 16,
so the next improvement has to fix more questions to register.
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

    Both populations feed it, so one word is never a stopword for an answerable
    question and a content word for a refusal one. This cannot move an answerable
    question's lexemes: the result is a per-word lookup, and a word an answerable
    question contains was already offered to it. Argued, then checked -- the
    retrieval baseline was re-run byte-identical after the refusal population
    landed (slice 5, AC7).
    """
    words = [word for q in golden.questions for word in morphology.words(q.question)]
    words += [word for r in golden.refusals for word in morphology.words(r.question)]
    return db.snowball_stopwords(conn, words)


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


@dataclass(frozen=True, slots=True)
class RefusalRetrieval:
    """What the retriever handed the answerer for one refusal question.

    There is no `QuestionOutcome` here and there must not be: recall over a
    question with no required chunks is a vacuous 1.0, and the surest way to keep
    that out of the headline is to have no type that could carry it there.
    """

    refusal: RefusalQuestion
    authority_key: str
    effective_date: date
    lexemes: tuple[str, ...]
    hits: tuple[db.Hit, ...]


ABSENCE_ANALYSER = Analyser.LEMMA_BASEFORM
"""The analyser the refusal drift detector lemmatises with, and NOT the published cell's.

`lemma-reasm` decomposes compounds: it reads `lisajate` as `lisa` + `jate` as well
as whole, and `jate` occurs in almost every chunk of a waste-regulation corpus. A
reassembling absence check would therefore fire on every compound needle in the
population and go red for entries whose labels are sound. `lemma-baseform` gives
one lemma per word with no decomposition, which is exactly what "is this WORD
present, in any inflected form" needs.

Deliberately independent of `evaluate.PUBLISHED`: the absence claim is a fact
about the corpus, not about the cell under measurement, and it must not start
reading differently because the published cell moved.
"""


def needle_lemmas(needle: str, morphology: Morphology) -> tuple[tuple[str, ...], ...]:
    """One tuple of candidate lemmas per word of the needle, in order.

    Every reading is kept rather than the first: voikko's ordering is not a
    confidence ranking, so picking one would silently decide a morphological
    question in a check whose whole job is to not be silently wrong.
    """
    words = morphology.words(needle)
    if not words:
        raise EvaluationError(
            f"{needle!r} tokenises to no words, so its absence cannot be checked at all"
        )
    readings = tuple(
        morphology.lexemes(word, ABSENCE_ANALYSER) or (word.casefold(),) for word in words
    )
    return readings


def _present(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    authority_key: str,
    refusal: RefusalQuestion,
    tsquery: str,
) -> list[str]:
    """Chunks of this authority carrying the needle, by EITHER check.

    Two independent detectors, unioned. The substring match cannot be weakened by
    a change to the analyser; the lemma match can see `renkaat` when the needle is
    `rengas`, which the substring match provably cannot. Neither alone is enough
    and neither is a proof of absence -- see `db.chunks_matching_lemmas`.
    """
    hits = set(
        db.chunks_containing(conn, authority_key=authority_key, needle=refusal.absent_lexeme)
    )
    hits |= set(
        db.chunks_matching_lemmas(
            conn, authority_key=authority_key, tsquery=tsquery, analyser=ABSENCE_ANALYSER
        )
    )
    return sorted(hits)


def assert_refusal_absences(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    manifest: Manifest,
    refusals: Sequence[RefusalQuestion],
    morphology: Morphology | None = None,
) -> None:
    """Check every refusal question's central claim against the corpus, per run.

    A refusal question asserts that a topic is not answerable where it was asked.
    That assertion decays: a new edition adds a clause, an authority adopts a
    mechanism, and a question whose correct answer used to be a refusal quietly
    becomes answerable. The metric would not go red -- it would score a *correct*
    answer as a missed refusal and read as the answerer getting worse.

    So the claim is checked rather than trusted, and for the out-of-jurisdiction
    kind it is checked from **both sides**: the lexeme must be absent where the
    question was asked and present where the answer lives. A one-sided check
    passes just as happily when an entry has gone vacuous for the opposite reason
    -- the foreign clause disappearing -- and that is the failure that would leave
    six questions in the population measuring nothing.
    """
    if not refusals:
        return
    foreign = [str(r.answerable_from) for r in refusals if r.answerable_from is not None]
    unresolvable = sorted(set(foreign) - db.resolve_addresses(conn, foreign))
    if unresolvable:
        raise EvaluationError(
            f"these refusal questions name an answerable_from chunk that is not in the "
            f"corpus: {unresolvable}. The entry claims the question is answerable in "
            "another jurisdiction; if that chunk does not exist, the claim is not."
        )

    morphology = morphology or Morphology.open()
    every_authority = [a.key for a in manifest.authorities]
    for refusal in refusals:
        asked = manifest.resolve_municipality(refusal.municipality).key
        tsquery = db.lemma_tsquery(needle_lemmas(refusal.absent_lexeme, morphology))
        present = _present(conn, authority_key=asked, refusal=refusal, tsquery=tsquery)
        if present:
            raise EvaluationError(
                f"{refusal.id}: {refusal.absent_lexeme!r} is NOT absent from {asked!r} -- "
                f"it appears in {present}. This question is scored as a refusal, so if "
                "the topic has become covered, a correct answer would now be counted as "
                "a missed refusal and the metric would read as the answerer regressing. "
                "Fix the label or drop the question; do not relax the check."
            )
        if refusal.kind is RefusalKind.OUT_OF_JURISDICTION:
            elsewhere = refusal.foreign_authority
            if elsewhere is None:
                # The loader refuses this, but a RefusalQuestion can be constructed
                # directly -- and an `assert` would vanish under `python -O`, taking
                # the guard with it.
                raise EvaluationError(
                    f"{refusal.id}: an out-of-jurisdiction refusal with no answerable_from "
                    "claims the hard kind of refusal while carrying no evidence that the "
                    "question is answerable anywhere."
                )
            if not _present(conn, authority_key=elsewhere, refusal=refusal, tsquery=tsquery):
                raise EvaluationError(
                    f"{refusal.id}: {refusal.absent_lexeme!r} is absent from {asked!r} but "
                    f"ALSO absent from {elsewhere!r}, where this entry claims the answer "
                    "lives. The question may now be unanswerable everywhere, which is a "
                    "different kind of refusal scored in a different population."
                )
            continue
        covered = {
            key: _present(conn, authority_key=key, refusal=refusal, tsquery=tsquery)
            for key in every_authority
        }
        elsewhere_hits = {key: hits for key, hits in covered.items() if hits}
        if elsewhere_hits:
            raise EvaluationError(
                f"{refusal.id}: this is an out-of-corpus refusal, so "
                f"{refusal.absent_lexeme!r} must be absent from the WHOLE corpus, but it "
                f"appears in {elsewhere_hits}. If one authority covers the topic, the "
                "question is out-of-jurisdiction rather than out-of-corpus, and the two "
                "are scored apart because they are not equally hard."
            )


def retrieve_refusals(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    manifest: Manifest,
    refusals: Sequence[RefusalQuestion],
    k: int = DEFAULT_K,
    cell: Cell = PUBLISHED,
    morphology: Morphology | None = None,
    stopwords: frozenset[str] | None = None,
) -> tuple[RefusalRetrieval, ...]:
    """Retrieve for each refusal question exactly as the answerable ones are.

    Same cell, same query normalisation, same authority filter, same top-k. That
    identity is the measurement: an out-of-jurisdiction question must reach the
    answerer holding five plausible, same-topic chunks from the authority it was
    asked about, because refusing *those* is the behaviour under test. Retrieving
    differently here would be measuring a different system.
    """
    if cell.analyser.lemmatising:
        morphology = morphology or Morphology.open()
    stopwords = stopwords if stopwords is not None else frozenset()

    retrieved: list[RefusalRetrieval] = []
    for refusal in refusals:
        authority = manifest.resolve_municipality(refusal.municipality)
        if len(authority.sources) != 1:
            raise EvaluationError(
                f"{refusal.id}: authority {authority.key!r} has "
                f"{len(authority.sources)} document versions, so the question must "
                "say which one it is asked against."
            )
        effective_date = authority.sources[0].effective_date
        lexemes = cell_query_lexemes(
            conn, refusal.question, cell, morphology=morphology, stopwords=stopwords
        )
        if not lexemes:
            raise EvaluationError(
                f"{refusal.id}: the question normalises to zero lexemes under the "
                f"{cell.name} analyser, so nothing would be retrieved for it at all. A "
                "refusal earned by retrieving nothing measures the tokeniser, not the "
                "answerer. Fix the question."
            )
        hits = db.search(
            conn,
            tsquery=db.or_tsquery(lexemes),
            authority_key=authority.key,
            effective_date=effective_date,
            limit=k,
            analyser=cell.analyser,
            normalisation=cell.normalisation,
        )
        assert_one_authority(hits, authority.key, refusal.id)
        retrieved.append(
            RefusalRetrieval(
                refusal=refusal,
                authority_key=authority.key,
                effective_date=effective_date,
                lexemes=tuple(lexemes),
                hits=tuple(hits),
            )
        )
    if len(retrieved) != len(refusals):  # pragma: no cover - the loop cannot skip
        raise EvaluationError(
            f"retrieved for {len(retrieved)} of {len(refusals)} refusal questions"
        )
    return tuple(retrieved)


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

"""End-to-end: the real corpus, indexed, and queried the way the eval queries it.

Every test here is an invariant of the *measurement*. A green run of the pure
unit tests says the arithmetic is right; these say the arithmetic is being done
over the corpus we think it is.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import cast

import psycopg
import pytest

from fi_rag_eval import db
from fi_rag_eval.addressing import ChunkAddress
from fi_rag_eval.analyse import Analyser, Morphology
from fi_rag_eval.evaluate import (
    GRID,
    Cell,
    EvaluationError,
    GridRun,
    evaluate,
)
from fi_rag_eval.golden import GoldenSet, Question
from fi_rag_eval.manifest import Manifest
from fi_rag_eval.metrics import MissKind, discordance

pytestmark = pytest.mark.requires_db

Connection = psycopg.Connection[tuple[object, ...]]
EFFECTIVE = "2024-08-01"
EFFECTIVE_DATE = date(2024, 8, 1)


def _search(conn: Connection, question: str, limit: int = 5) -> list[db.Hit]:
    lexemes = db.query_lexemes(conn, question)
    return db.search(
        conn,
        tsquery=db.or_tsquery(lexemes),
        authority_key="lounais-suomi",
        effective_date=EFFECTIVE_DATE,
        limit=limit,
    )


def test_a_query_lexeme_is_not_stemmed_a_second_time(corpus: Connection) -> None:
    """The bug that inflated the first ever run of this harness.

    ``or_tsquery`` returns a literal over lexemes the stemmer has *already*
    produced. Passing that through ``to_tsquery`` stems them again -- ``biojät``
    becomes ``biojä`` -- and the query silently stops matching chunks that
    contain the term. It has to be cast, not parsed.
    """
    lexemes = db.query_lexemes(corpus, "Mitä biojätteellä tarkoitetaan?")
    assert "biojät" in lexemes
    literal = db.or_tsquery(lexemes)
    with corpus.cursor() as cur:
        cur.execute("SELECT CAST(%s AS tsquery)::text", (literal,))
        cast = str(cur.fetchone()[0])  # type: ignore[index]
        cur.execute("SELECT to_tsquery('finnish', %s)::text", (literal,))
        reparsed = str(cur.fetchone()[0])  # type: ignore[index]
    assert "'biojät'" in cast
    assert cast != reparsed, "to_tsquery is expected to over-stem; if not, note it here"


@pytest.mark.parametrize("lexeme", ["biojät", "it's", "a\\b", "quote'double"])
def test_a_lexeme_survives_the_tsquery_literal_intact(corpus: Connection, lexeme: str) -> None:
    """Escaping must preserve the lexeme, not merely produce parsable SQL.

    Inside a quoted tsquery literal both the quote and the backslash are special.
    A mis-escaped lexeme still parses -- it just means something else, which is a
    measurement corrupted silently rather than a query that errors.
    """
    vector = f"'{db.escape_lexeme(lexeme)}':1"
    with corpus.cursor() as cur:
        cur.execute(
            "SELECT CAST(%s AS tsvector) @@ CAST(%s AS tsquery), "
            "(SELECT lexeme FROM unnest(CAST(%s AS tsvector)) LIMIT 1)",
            (vector, db.or_tsquery([lexeme]), vector),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] is True
    assert row[1] == lexeme


def test_a_chunk_containing_the_query_term_is_reachable(corpus: Connection) -> None:
    """The invariant the double-stemming bug violated."""
    lexemes = db.query_lexemes(corpus, "Mitä biojätteellä tarkoitetaan?")
    reachable = db.addresses_matching(
        corpus,
        addresses=[f"lounais-suomi@{EFFECTIVE}#2.biojatteella"],
        tsquery=db.or_tsquery(lexemes),
    )
    assert reachable == {f"lounais-suomi@{EFFECTIVE}#2.biojatteella"}


def test_the_corpus_matches_the_manifest(corpus: Connection, manifest: Manifest) -> None:
    """Every authority the manifest lists is loaded, with the parse it was labelled at."""
    summary = {(row.authority_key, row.effective_date): row for row in db.corpus_summary(corpus)}
    expected = {
        (authority.key, source.effective_date): source.expected
        for authority in manifest.authorities
        for source in authority.sources
    }
    assert set(summary) == set(expected)
    for key, parse in expected.items():
        row = summary[key]
        assert (row.clauses, row.chunks, row.definitions) == (
            parse.clauses,
            parse.chunks,
            parse.definitions,
        ), key


def test_every_golden_label_resolves(corpus: Connection, golden: GoldenSet) -> None:
    wanted = [address for q in golden.questions for address in q.required_addresses]
    assert db.resolve_addresses(corpus, wanted) == set(wanted)


def test_an_authority_with_no_corpus_retrieves_nothing(corpus: Connection) -> None:
    """The weak half of the hard-filter claim, and all slice 1 can prove.

    This shows the filter is *applied* -- it is in the WHERE clause, so a chunk
    outside the jurisdiction is never a candidate rather than a filtered result.
    It does **not** show that a real second authority's chunks stay out of a
    ranking they would otherwise win, because there is no second authority to
    leak from. That test arrives with slice 2, and until then the project's worst
    failure mode is unverified (`REVIEW-DEBT.md`).
    """
    lexemes = db.query_lexemes(corpus, "Kuinka usein biojäteastia tyhjennetään?")
    hits = db.search(
        corpus,
        tsquery=db.or_tsquery(lexemes),
        authority_key="savo-pielinen",
        effective_date=EFFECTIVE_DATE,
        limit=5,
    )
    assert hits == []


def test_ranking_is_deterministic(corpus: Connection) -> None:
    """The regression gate compares exact values, so ties must break the same way."""
    first = [hit.address for hit in _search(corpus, "jäteastian tyhjennysväli taajamassa", 10)]
    second = [hit.address for hit in _search(corpus, "jäteastian tyhjennysväli taajamassa", 10)]
    assert first == second
    assert len(first) == 10


def test_a_keyword_trap_question_still_ranks_the_right_clause_first(
    corpus: Connection,
) -> None:
    """27 § over 26 §: "pestävä" must beat the far more common "biojäteastia"."""
    hits = _search(corpus, "Kuinka monta kertaa vuodessa biojäteastia on pestävä?")
    assert hits[0].address == f"lounais-suomi@{EFFECTIVE}#27"


def test_the_evaluation_scores_every_question_or_fails(
    corpus: Connection, manifest: Manifest, golden: GoldenSet
) -> None:
    run = evaluate(corpus, manifest=manifest, golden=golden, k=5)
    assert run.metrics.questions == len(golden)
    assert run.metrics.required_chunks == sum(len(q.required_chunks) for q in golden.questions)
    assert len(run.runs) == len(golden)


def test_an_unresolvable_label_fails_the_run_rather_than_being_skipped(
    corpus: Connection, manifest: Manifest, golden: GoldenSet
) -> None:
    broken = replace(
        golden,
        questions=(
            *golden.questions,
            replace(
                golden.questions[0],
                id="points-at-nothing",
                required_chunks=(ChunkAddress.parse(f"lounais-suomi@{EFFECTIVE}#999"),),
                required_branches=(),
            ),
        ),
    )
    with pytest.raises(EvaluationError, match="do not resolve"):
        evaluate(corpus, manifest=manifest, golden=broken, k=5)


def test_short_chunks_are_under_retrieved_at_default_normalisation(
    corpus: Connection,
) -> None:
    """The measured finding that refuted the pre-registered prediction.

    ``ts_rank`` at normalisation 0 does not divide by document length, so a long
    clause accumulates more matched-term weight than a short one. Definition
    chunks are 39% of this corpus and were 0% of every top-5. The prediction said
    the opposite would happen, for the opposite reason.
    """
    hits = _search(corpus, "Mitä biojätteellä tarkoitetaan näissä jätehuoltomääräyksissä?")
    with corpus.cursor() as cur:
        cur.execute(
            "SELECT length(body) FROM chunk WHERE address = ANY(%s)",
            ([hit.address for hit in hits],),
        )
        lengths = [int(str(row[0])) for row in cur.fetchall()]
        cur.execute(
            "SELECT length(body) FROM chunk WHERE address = %s",
            (f"lounais-suomi@{EFFECTIVE}#2.biojatteella",),
        )
        target = int(str(cur.fetchone()[0]))  # type: ignore[index]
    assert min(lengths) > target, "every retrieved chunk is longer than the missed target"


def test_resident_vocabulary_is_unreachable_by_stemming_alone(corpus: Connection) -> None:
    """The finding the golden-set rewrite bought, pinned so it cannot regress quietly.

    Nothing a Finnish stemmer does connects "taloyhtiö", "asunto" or "keskusta"
    to the words the regulations use (`kiinteistö`, `huoneisto`, `taajama`). This
    is a genuine vocabulary gap, not a morphology one, and it is the evidence for
    the vector layer -- previously an assumption in the design.

    If this ever passes, something semantic was added. Update the test and say so.
    """
    question = "Meillä on taloyhtiössä kolme asuntoa keskustassa. Tarvitaanko biojäteastia?"
    lexemes = db.query_lexemes(corpus, question)
    assert {"taloyhtiö", "asunto", "keskust"} <= set(lexemes)
    targets = [f"lounais-suomi@{EFFECTIVE}#13", f"lounais-suomi@{EFFECTIVE}#15"]
    assert db.chunk_lexemes(corpus, targets) & set(lexemes) == set()
    assert db.addresses_matching(corpus, addresses=targets, tsquery=db.or_tsquery(lexemes)) == set()


def test_the_same_word_stems_differently_in_query_and_corpus(corpus: Connection) -> None:
    """Why a question containing the document's own word can still miss it.

    Snowball gives ``biojäteastia`` the stem ``biojäteast`` but ``biojäteastiaan``
    the stem ``biojäteastia``. The query and the index therefore disagree about a
    word both of them contain, which no amount of ranking can repair. This is the
    measured case for lemmatisation.
    """
    assert db.query_lexemes(corpus, "biojäteastia") == ["biojäteast"]
    assert db.query_lexemes(corpus, "biojäteastiaan") == ["biojäteastia"]
    assert db.query_lexemes(corpus, "kesällä") != db.query_lexemes(corpus, "kesäaikana")


def test_leakage_is_measured_against_the_targets_not_the_whole_corpus(
    corpus: Connection, manifest: Manifest, golden: GoldenSet
) -> None:
    """Pinned to the SNOWBALL control cell, deliberately, and not to whichever cell
    is published.

    The mechanism under test -- a question's leakage is computed against its own
    required chunks, never against the corpus -- is analyser-agnostic. Its
    *example* is not: `taloyhtiö` leaks nothing under snowball and does leak under
    compound splitting, because `talo` + `yhtiö` are in the clause. That is a
    slice-3 finding, not a defect, so this test names its cell rather than
    inheriting the published one and breaking when the Owner moves it.
    """
    control = Cell(Analyser.SNOWBALL, 0)
    run = evaluate(corpus, manifest=manifest, golden=golden, k=5, cell=control)
    by_id = {r.outcome.question_id: r.outcome for r in run.runs}

    resident = by_id["taloyhtio-kolme-asuntoa-biojate"]
    assert resident.leaked_lexemes == ()
    assert resident.lexical_leakage == 0.0

    # Every leaked stem must actually be present in that question's own targets,
    # read through the same analyser the cell was scored with.
    for outcome in by_id.values():
        target_lexemes = db.chunk_lexemes(corpus, outcome.required, control.analyser)
        assert set(outcome.leaked_lexemes) <= target_lexemes
        assert set(outcome.leaked_lexemes) <= set(outcome.query_lexemes)

    assert 0.0 < run.metrics.lexical_leakage < 1.0


def _grid_search(
    conn: Connection,
    question: str,
    *,
    analyser: Analyser,
    normalisation: int,
    morphology: Morphology,
    limit: int = 5,
) -> list[db.Hit]:
    lexemes = (
        db.query_lexemes(conn, question)
        if not analyser.lemmatising
        else morphology.query_lexemes(question, analyser, stopwords=frozenset())
    )
    return db.search(
        conn,
        tsquery=db.or_tsquery(lexemes),
        authority_key="lounais-suomi",
        effective_date=EFFECTIVE_DATE,
        limit=limit,
        analyser=analyser,
        normalisation=normalisation,
    )


def test_normalisation_32_cannot_reorder_anything(corpus: Connection) -> None:
    """The spec named `ts_rank` normalisation 32 as the grid's second axis. Wrong.

    Postgres documents 32 as "divides the rank by itself + 1" -- that is
    ``rank / (rank + 1)``, a strictly monotonic rescale into `[0, 1)`. It cannot
    change the order of a single result, so it never tested slice 1's
    document-length finding at all. The first run of this grid scored every cell
    identically at 0 and 32, with an identical per-question pass matrix, which is
    what sent us back to the manual.

    Pinned so that 32 is not reintroduced as a length-normalisation setting, and
    so the arithmetic reason is on the record rather than the empirical one.
    """
    lexemes = db.query_lexemes(corpus, "Mitä biojätteellä tarkoitetaan?")
    tsquery = db.or_tsquery(lexemes)
    with corpus.cursor() as cur:
        cur.execute(
            "SELECT ts_rank(tsv, query, 0), ts_rank(tsv, query, 32) "
            "FROM chunk, CAST(%s AS tsquery) AS query WHERE tsv @@ query "
            "ORDER BY 1 DESC, address ASC",
            (tsquery,),
        )
        ranks = [(float(str(row[0])), float(str(row[1]))) for row in cur.fetchall()]
    assert len(ranks) > 5
    for plain, rescaled in ranks:
        assert rescaled == pytest.approx(plain / (plain + 1))
    assert [rescaled for _, rescaled in ranks] == sorted(
        (rescaled for _, rescaled in ranks), reverse=True
    ), "32 preserves the order exactly, which is why it is not in the grid"


def test_length_normalisation_actually_reorders(corpus: Connection) -> None:
    """The settings that *do* test the finding, and the size of the effect.

    Slice 1 measured definition chunks at 39% of this corpus and 0% of every
    top-5. Normalisation 1 and 2 both divide by document length and both put the
    short definition chunk into the top 5 of the very query that missed it.
    """
    target = f"lounais-suomi@{EFFECTIVE}#2.biojatteella"
    question = "Mitä biojätteellä tarkoitetaan näissä jätehuoltomääräyksissä?"
    lexemes = db.query_lexemes(corpus, question)
    for normalisation in (1, 2):
        hits = db.search(
            corpus,
            tsquery=db.or_tsquery(lexemes),
            authority_key="lounais-suomi",
            effective_date=EFFECTIVE_DATE,
            limit=5,
            normalisation=normalisation,
        )
        assert target in {hit.address for hit in hits}, normalisation
    assert target not in {hit.address for hit in _search(corpus, question)}


def test_an_unmeasured_normalisation_is_refused(corpus: Connection) -> None:
    """The baseline records a fixed set of cells, so widening the grid is a
    deliberate act rather than an argument someone can pass."""
    with pytest.raises(db.DatabaseError, match="not one of the settings"):
        db.search(
            corpus,
            tsquery=db.or_tsquery(["jäte"]),
            authority_key="lounais-suomi",
            effective_date=EFFECTIVE_DATE,
            limit=5,
            normalisation=32,
        )


def test_every_chunk_is_indexed_under_every_analyser(corpus: Connection) -> None:
    """The invariant the generated `tsv` gets from Postgres for free.

    The three lemma columns are written by the ingest, so an empty one would make
    a chunk unretrievable in that cell -- scored as a retrieval miss and blamed on
    the analyser instead of on the ingest.
    """
    db.assert_lemma_vectors_populated(corpus)
    counts = db.lexeme_counts(corpus)
    assert set(counts) == set(Analyser)
    assert counts[Analyser.SNOWBALL] > 0
    # The grid's second axis exists because splitting inflates these counts and
    # ts_rank at normalisation 0 rewards accumulated term weight.
    assert (
        counts[Analyser.SNOWBALL]
        < counts[Analyser.LEMMA_BASEFORM]
        < counts[Analyser.LEMMA_SAFE]
        < counts[Analyser.LEMMA_REASM]
    )


def test_a_tsvector_literal_round_trips_through_postgres(corpus: Connection) -> None:
    """The lemma columns are serialised by hand, so the escaping has to hold.

    A mis-escaped lexeme still parses; it just means something else -- a
    measurement corrupted silently rather than a statement that errors.
    """
    entries = [("biojäte", (1, 4)), ("it's", (2,)), ("a\\b", (3,)), ("840-1", (5,))]
    literal = db.tsvector_literal(entries)
    with corpus.cursor() as cur:
        cur.execute(
            "SELECT lexeme, positions FROM unnest(CAST(%s AS tsvector)) ORDER BY lexeme",
            (literal,),
        )
        rows = {
            str(row[0]): tuple(int(position) for position in cast("list[int]", row[1]))
            for row in cur.fetchall()
        }
    assert rows == dict(entries)


def test_an_empty_tsvector_is_refused_rather_than_written(corpus: Connection) -> None:
    """A chunk indexing to nothing is unretrievable, and would be scored as a
    retrieval failure rather than as the ingest bug it is."""
    del corpus
    with pytest.raises(db.DatabaseError, match="empty tsvector"):
        db.tsvector_literal([])


def test_the_lemma_analysers_stop_on_the_same_words_as_snowball(corpus: Connection) -> None:
    """Otherwise the grid measures two variables and reports one number.

    Without this, a lemma cell would index and query `olla` -- a word in nearly
    every clause -- while the control cell does not, and every cell-to-cell delta
    would be lemmatisation *plus* the absence of stopping.
    """
    stopwords = db.snowball_stopwords(
        corpus, ["mitä", "on", "ja", "olla", "että", "kuinka", "usein", "monta", "biojäte"]
    )
    assert {"mitä", "on", "ja", "olla", "että"} <= stopwords
    assert stopwords & {"kuinka", "usein", "monta", "biojäte"} == set()


def test_the_original_21_questions_still_score_exactly_what_they_scored(
    grid: GridRun, golden: GoldenSet
) -> None:
    """The continuity guarantee, kept when the population changed under it.

    Slices 1-3 pinned this as "0.762 exactly; if this moves, the harness is broken,
    not improved". Slice 4 grows the set to 50 questions across two authorities, so
    the *pooled* headline legitimately moves and pinning it would assert nothing.
    What must not move is the measurement of the questions that already existed --
    so the control is now computed over exactly those 21, and it still gives
    16/21 and 18/21.

    This is also the evidence for the README's "not comparable to 0.762" note: the
    headline changed because the population changed, and provably not because
    anything in slices 1-3 was disturbed. A second authority adds **zero**
    distractors to an existing question -- the authority filter runs before
    ranking and `ts_rank` has no IDF -- so these numbers are identical, not merely
    close.
    """
    original = {q.id for q in golden.questions if q.authority == "lounais-suomi" and q.pair is None}
    assert len(original) == 21, "the slice-2 question set must still be identifiable"
    for cell, expected in (
        (Cell(Analyser.SNOWBALL, 0), 16),
        (Cell(Analyser.LEMMA_REASM, 1), 18),
    ):
        run = grid.cell(cell)
        subset = [r.outcome for r in run.runs if r.question.id in original]
        assert len(subset) == 21
        assert sum(1 for o in subset if o.complete) == expected, cell.name


def test_the_grid_scores_every_cell_over_exactly_the_same_questions(
    grid: GridRun, golden: GoldenSet
) -> None:
    """A cell-to-cell delta is only attributable if nothing else moved."""
    assert len(grid.cells) == len(GRID)
    assert {run.cell for run in grid.cells} == set(GRID)
    for run in grid.cells:
        assert run.metrics.questions == len(golden), run.cell.name
        assert [r.outcome.question_id for r in run.runs] == [q.id for q in golden.questions]


def test_lemmatisation_closes_every_zero_overlap_miss(grid: GridRun) -> None:
    """What this slice was for, stated as the miss diagnostic rather than a score.

    Slice 2 measured 4 of 6 misses as zero-overlap -- a required chunk sharing no
    lexeme at all with its question. The reassembling analyser takes that to zero:
    every remaining miss is now reachable and lost in the ranking, which is a
    different failure with a different fix.
    """
    by_analyser = {
        run.cell.analyser: run.metrics for run in grid.cells if run.cell.normalisation == 0
    }
    # Measured at N=50 over two authorities. Slice 2 saw 4 / 2 / 0 at N=21; the
    # control's count grew with the population and the reassembler still absorbs
    # all of it -- including the synonym fork between the two authorities, which
    # the slice-4 spec predicted it could not (see the refutation pinned below).
    assert by_analyser[Analyser.SNOWBALL].misses_zero_overlap == 6
    assert by_analyser[Analyser.LEMMA_BASEFORM].misses_zero_overlap == 2
    assert by_analyser[Analyser.LEMMA_REASM].misses_zero_overlap == 0
    assert (
        by_analyser[Analyser.SNOWBALL].misses_zero_overlap
        > by_analyser[Analyser.LEMMA_BASEFORM].misses_zero_overlap
        > by_analyser[Analyser.LEMMA_REASM].misses_zero_overlap
    )


def test_the_reassembler_earns_its_place_over_the_conservative_split(grid: GridRun) -> None:
    """D4's rule, and it is a rule with teeth: the reassembler is a hand-rolled
    linguistic component, and if it does not beat the conservative split by at
    least one whole question it is deleted rather than tuned.

    It wins in exactly one cell -- paired with length normalisation, where the
    conservative split loses. That pairing is the interaction the grid existed to
    find, and a sequential slice would have missed it.
    """
    best = {
        analyser: max(
            run.metrics.complete_set_recall for run in grid.cells if run.cell.analyser is analyser
        )
        for analyser in Analyser
    }
    questions = grid.published.metrics.questions
    assert best[Analyser.LEMMA_REASM] > best[Analyser.LEMMA_SAFE]
    margin = (best[Analyser.LEMMA_REASM] - best[Analyser.LEMMA_SAFE]) * questions
    # One whole question at N=21, three at N=50: the rule is "at least one", and
    # the margin grew rather than evaporating when the set tripled.
    assert margin >= 1.0, f"the reassembler wins by only {margin:.2f} questions"


def test_length_normalisation_costs_only_the_control_cell_now(grid: GridRun) -> None:
    """A SLICE-3 FINDING THAT DID NOT SURVIVE N=50. Recorded, not smoothed over.

    Slice 3 measured, at N=21, that dividing by document length cost the control
    and the unsplit lemma cell recall and *gained* it for the reassembled one, and
    called that sign flip "the interaction the grid existed to find".

    At N=50 the clean interaction is gone. Normalisation 1 now **helps**
    `lemma-baseform` (0.740 -> 0.780), is **neutral** for both split analysers
    (0.760 and 0.820 either way), and costs only the snowball control
    (0.680 -> 0.640).

    The slice-3 claim rested on a one-question gain at N=21 -- three discordant
    questions, p=0.25 -- which was never a result the instrument could resolve.
    This is the clearest thing the bigger question set bought: not a better score,
    but the retraction of a conclusion that was noise. The honest statement now is
    the narrow one: **length normalisation costs the control cell and does not
    clearly help any lemma cell.**
    """
    recall = {run.cell: run.metrics.complete_set_recall for run in grid.cells}
    assert recall[Cell(Analyser.SNOWBALL, 1)] < recall[Cell(Analyser.SNOWBALL, 0)]
    assert recall[Cell(Analyser.LEMMA_BASEFORM, 1)] > recall[Cell(Analyser.LEMMA_BASEFORM, 0)]
    for analyser in (Analyser.LEMMA_SAFE, Analyser.LEMMA_REASM):
        assert recall[Cell(analyser, 1)] == recall[Cell(analyser, 0)], analyser
    # Normalisation 2 is still ruinous everywhere, which was never in doubt.
    for analyser in Analyser:
        assert recall[Cell(analyser, 2)] < recall[Cell(analyser, 0)], analyser


def test_leakage_rises_under_lemmatisation_with_no_question_edited(grid: GridRun) -> None:
    """Why the gate had to become per-cell instead of being waived.

    Leakage is the share of a question's own vocabulary that its target chunk
    already contains, and it is gated to never *rise* -- a question edited to
    resemble its target inflates every score above it. Lemmatisation raises it
    without a single question changing, because words snowball stems apart are
    now the same lexeme. Comparing each cell against its own recorded leakage
    compares like with like; comparing across cells would fail the gate for a
    reason that has nothing to do with the golden set getting easier.
    """
    leakage = {run.cell.analyser: run.metrics.lexical_leakage for run in grid.cells}
    # 0.332 at N=50, against 0.372 at N=21: the 29 new questions are LESS leaky
    # than the 21 they joined, so the golden set got harder, not easier.
    assert leakage[Analyser.SNOWBALL] == pytest.approx(0.33204633204633205)
    assert (
        leakage[Analyser.SNOWBALL]
        < leakage[Analyser.LEMMA_BASEFORM]
        < leakage[Analyser.LEMMA_SAFE]
        < leakage[Analyser.LEMMA_REASM]
    )


def test_the_resident_vocabulary_gap_becomes_a_ranking_failure_not_a_reach(
    grid: GridRun,
) -> None:
    """The refinement lemmatisation forced on slice 2's headline finding.

    "taloyhtiö / asunto / keskusta are unreachable" was measured under snowball
    and is still true there. Under the reassembling analyser the two clauses
    become *reachable* -- `taloyhtiö` splits to `talo` + `yhtiö`, which the
    clauses do contain -- and are still not retrieved. So the gap is not purely
    lexical reach; it is that the words the resident uses carry no weight in the
    clause that answers them. That is a vector-layer argument, and a sharper one
    than "no shared stem".
    """
    question = "taloyhtio-kolme-asuntoa-biojate"
    for analyser, kinds in (
        (Analyser.SNOWBALL, {MissKind.ZERO_OVERLAP}),
        (Analyser.LEMMA_REASM, {MissKind.RANKED_OUT}),
    ):
        run = grid.cell(Cell(analyser, 0))
        outcome = next(r.outcome for r in run.runs if r.outcome.question_id == question)
        assert not outcome.complete, analyser
        assert {miss.kind for miss in outcome.misses} == kinds, analyser


# --------------------------------------------------------------------- slice 4
#
# What the second authority bought, pinned so a later change has to argue with it.


def test_a_paired_question_requires_different_chunks_per_authority(golden: GoldenSet) -> None:
    """AC6. Identical text, two jurisdictions, two different sets of rules."""
    by_pair: dict[str, list[Question]] = {}
    for question in golden.questions:
        if question.pair is not None:
            by_pair.setdefault(question.pair, []).append(question)
    assert len(by_pair) == 8, "D7 fixed the paired count at 8"
    for slug, (first, second) in by_pair.items():
        assert first.question == second.question, slug
        assert first.authority != second.authority, slug
        assert not set(first.required_addresses) & set(second.required_addresses), slug


@pytest.mark.requires_db
def test_the_authority_changes_the_answer_to_the_same_question(grid: GridRun) -> None:
    """`DESIGN.md:96`'s "answer differs between authorities" category, measured.

    Before this slice the category had zero questions, so nothing in the harness
    could tell an authority-sensitive answer from an authority-blind one. Now at
    least one paired question passes for one authority and fails for the other in
    the published cell -- the same words, a different jurisdiction, a different
    outcome.
    """
    published = grid.published
    outcomes = {r.question.id: r for r in published.runs}
    disagreeing = []
    for run in published.runs:
        if run.question.pair is None:
            continue
        other = next(
            r
            for r in published.runs
            if r.question.pair == run.question.pair and r.question.id != run.question.id
        )
        if run.outcome.complete != other.outcome.complete:
            disagreeing.append(run.question.pair)
    assert disagreeing, (
        "no paired question was decided differently by the two authorities, so the "
        "set cannot yet show that the jurisdiction changes the answer"
    )
    assert outcomes  # the matrix printed above is the evidence


@pytest.mark.requires_db
def test_the_synonym_fork_is_a_ranking_failure_not_a_reach_failure(grid: GridRun) -> None:
    """The slice-4 prediction that was REFUTED, pinned so it is not re-assumed.

    The spec predicted zero-overlap misses returning to 3-8 in `lemma-reasm/1`,
    because `keräysväline` and `jäteastia` share no stem and no analyser can
    bridge them. Measured: **zero**. The vocabulary fork is real -- a paired
    question genuinely passes for one authority and fails for the other -- but it
    surfaces as *ranked-out*, not as unreachable, because a question shares plenty
    of other lexemes with its target even when the key noun does not match.

    That distinction decides slice 5: embeddings address synonymy, and a miss that
    is already reachable is a ranking problem with a different fix.
    """
    for cell in (Cell(Analyser.LEMMA_REASM, 0), Cell(Analyser.LEMMA_REASM, 1)):
        metrics = grid.cell(cell).metrics
        assert metrics.misses_zero_overlap == 0, (
            f"{cell.name} has {metrics.misses_zero_overlap} zero-overlap misses; if the "
            "synonym fork has started making chunks unreachable, slice 5's mandate "
            "changes and the spec's decision rule must be re-read"
        )
        assert metrics.misses_ranked_out > 0, "every remaining miss is a ranking failure"


@pytest.mark.requires_db
def test_the_instrument_can_now_resolve_a_cell_difference_at_all(grid: GridRun) -> None:
    """The whole reason this slice preceded the vector layer.

    Two cells are scored on the same questions, so the comparison is paired and
    six discordant questions must flip one way for p<0.05. At N=21 the best cell
    had three failures, so no result *any* retrieval change could have produced
    would have registered. At N=50 at least one cell beats the published cell at
    p<0.05 on the exact McNemar test -- the instrument has power for the first
    time.
    """
    # The specific claim the published cell rests on: it beats the old snowball
    # control on the paired test. Pinned so it cannot quietly stop being true --
    # if this goes red, the published headline is no longer defensible and the
    # move recorded in ADR-0007 has to be revisited, not the test relaxed.
    control = grid.cell(Cell(Analyser.SNOWBALL, 0))
    against_control = discordance(
        [r.outcome for r in grid.published.runs], [r.outcome for r in control.runs]
    )
    assert grid.published.metrics.complete_set_recall > control.metrics.complete_set_recall
    assert against_control.p_value < 0.05, (
        f"the published cell beats the snowball control by "
        f"{against_control.discordant} discordant questions at p="
        f"{against_control.p_value:.3f}, which does not clear 0.05"
    )

    # And the general property: this instrument can resolve *some* difference in
    # the grid. At N=21 no pair of cells could, at any effect size.
    resolvable = [
        (a.cell.name, b.cell.name)
        for index, a in enumerate(grid.cells)
        for b in grid.cells[index + 1 :]
        if discordance([r.outcome for r in a.runs], [r.outcome for r in b.runs]).p_value < 0.05
    ]
    assert resolvable, (
        "no pair of cells differs at p<0.05, so this run cannot claim any retrieval "
        "difference is real -- which is the claim the golden set was grown to make possible"
    )

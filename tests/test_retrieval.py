"""End-to-end: the real corpus, indexed, and queried the way the eval queries it.

Every test here is an invariant of the *measurement*. A green run of the pure
unit tests says the arithmetic is right; these say the arithmetic is being done
over the corpus we think it is.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import psycopg
import pytest

from fi_rag_eval import db
from fi_rag_eval.addressing import ChunkAddress
from fi_rag_eval.evaluate import EvaluationError, evaluate
from fi_rag_eval.golden import GoldenSet
from fi_rag_eval.manifest import Manifest

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
    summary = db.corpus_summary(corpus)
    assert len(summary) == 1
    source = manifest.authority("lounais-suomi").sources[0]
    assert (summary[0].chunks, summary[0].definitions) == (
        source.expected.chunks,
        source.expected.definitions,
    )


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
    run = evaluate(corpus, manifest=manifest, golden=golden, k=5)
    by_id = {r.outcome.question_id: r.outcome for r in run.runs}

    resident = by_id["taloyhtio-kolme-asuntoa-biojate"]
    assert resident.leaked_lexemes == ()
    assert resident.lexical_leakage == 0.0

    # Every leaked stem must actually be present in that question's own targets.
    for outcome in by_id.values():
        target_lexemes = db.chunk_lexemes(corpus, outcome.required)
        assert set(outcome.leaked_lexemes) <= target_lexemes
        assert set(outcome.leaked_lexemes) <= set(outcome.query_lexemes)

    assert 0.0 < run.metrics.lexical_leakage < 1.0

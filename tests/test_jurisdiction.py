"""The authority hard filter: the product's #1 failure mode, proven both ways.

`DESIGN.md:15,67` asks for cross-municipality answers to be *structurally
impossible* rather than discouraged. Slice 1 could only prove the weak half of
that -- an authority with no corpus retrieves nothing -- because with one
authority loaded there was nothing to leak from. Slice 4 loads a second, so the
claim is testable for the first time.

Two tests carry the weight, and neither is worth anything without the other:

* the hazard is **real** -- with the filter removed, foreign chunks genuinely do
  enter the top k, so the filter is load-bearing rather than decorative;
* the check **fires** -- `evaluate.assert_one_authority` turns that leak into a
  failed run.

A note on what this does *not* prove, kept here because the spec's own
acceptance criterion is easy to misread. AC5 proposed seeing the assertion red
"by mislabelling a municipality". That cannot work: `golden._parse_question`
already rejects a question whose municipality resolves to one authority while its
labels point at another, so a mislabelled question never reaches `evaluate`. And
if it did, the search would simply run against the wrong authority and retrieve
that authority's own chunks -- every hit native, the assertion silent, the
question merely a miss. The assertion defends against a regression in the
**search**, not against a labelling error, and the only honest way to see it red
is to drop the filter. Recorded as a spec delta rather than papered over.
"""

from __future__ import annotations

from datetime import date

import pytest
from psycopg import Connection, sql

from fi_rag_eval import db
from fi_rag_eval.analyse import Analyser, Morphology
from fi_rag_eval.evaluate import (
    PUBLISHED,
    EvaluationError,
    assert_one_authority,
    evaluate,
)
from fi_rag_eval.golden import GoldenSet
from fi_rag_eval.manifest import Manifest, ManifestError

pytestmark = pytest.mark.requires_db


def _unfiltered_search(
    conn: Connection[tuple[object, ...]],
    *,
    tsquery: str,
    authority_key: str,
    effective_date: date,
    limit: int,
    analyser: Analyser = Analyser.SNOWBALL,
    normalisation: int = 0,
) -> list[db.Hit]:
    """`db.search` with the jurisdiction WHERE clause deleted, and nothing else.

    This is the regression being defended against, written out rather than
    described: the exact query `db.search` runs, minus
    ``authority_key = %s AND effective_date = %s``.
    """
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT address, citation, ts_rank({column}, query, %s) AS rank, "
                "authority_key FROM chunk, CAST(%s AS tsquery) AS query "
                "WHERE {column} @@ query "
                "ORDER BY rank DESC, address ASC LIMIT %s"
            ).format(column=sql.Identifier(analyser.column)),
            (normalisation, tsquery, limit),
        )
        return [
            db.Hit(
                position=position,
                address=str(row[0]),
                citation=str(row[1]),
                rank=float(str(row[2])),
                authority_key=str(row[3]),
            )
            for position, row in enumerate(cur.fetchall(), start=1)
        ]


def test_the_filter_is_load_bearing_not_decorative(
    corpus: Connection[tuple[object, ...]], golden: GoldenSet
) -> None:
    """Without the filter, foreign chunks really do reach the top k.

    If they did not, the assertion below would be green for a reason that has
    nothing to do with the filter working, and the whole check would be
    decoration. This is the test that stops that.
    """
    leaked: list[tuple[str, str]] = []
    for question in golden.questions:
        lexemes = db.query_lexemes(corpus, question.question)
        hits = _unfiltered_search(
            corpus,
            tsquery=db.or_tsquery(lexemes),
            authority_key=question.authority,
            effective_date=date(2024, 8, 1),
            limit=5,
        )
        leaked.extend(
            (question.id, hit.address) for hit in hits if hit.authority_key != question.authority
        )
    assert leaked, (
        "no question retrieved a foreign chunk even with the filter removed, so this "
        "corpus cannot demonstrate the hazard the filter exists to prevent"
    )


def test_evaluate_goes_red_when_the_authority_filter_is_dropped(
    corpus: Connection[tuple[object, ...]],
    manifest: Manifest,
    golden: GoldenSet,
    morphology: Morphology,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate seen red: drop the filter and the run refuses to report a number."""
    monkeypatch.setattr(db, "search", _unfiltered_search)
    with pytest.raises(EvaluationError, match="chunks from another authority"):
        evaluate(
            corpus,
            manifest=manifest,
            golden=golden,
            cell=PUBLISHED,
            morphology=morphology,
        )


def test_the_real_run_is_green_on_the_same_check(
    corpus: Connection[tuple[object, ...]],
    manifest: Manifest,
    golden: GoldenSet,
    morphology: Morphology,
) -> None:
    """And with the filter in place, every hit of every question is native."""
    run = evaluate(corpus, manifest=manifest, golden=golden, cell=PUBLISHED, morphology=morphology)
    for question_run in run.runs:
        assert {hit.authority_key for hit in question_run.hits} <= {question_run.authority_key}


def test_a_foreign_hit_is_named_in_the_failure() -> None:
    """The check itself, without a database: it must say which chunk leaked."""
    hits = [
        db.Hit(position=1, address="a@2024-08-01#1", citation="1 §", rank=1.0, authority_key="a"),
        db.Hit(position=2, address="b@2021-07-01#7", citation="7 §", rank=0.9, authority_key="b"),
    ]
    with pytest.raises(EvaluationError, match=r"b@2021-07-01#7"):
        assert_one_authority(hits, "a", "some-question")


def test_an_all_native_top_k_passes_the_check() -> None:
    hits = [
        db.Hit(position=1, address="a@2024-08-01#1", citation="1 §", rank=1.0, authority_key="a")
    ]
    assert_one_authority(hits, "a", "some-question")


@pytest.mark.parametrize("municipality", ["Sastamala", "sastamala", "SASTAMALA"])
def test_a_partially_covered_municipality_refuses_and_says_why(
    manifest: Manifest, municipality: str
) -> None:
    """AC8. Pirkanmaa's 1 § claims Sastamala only for Mouhijärvi and Suodenniemi.

    An honest refusal beats a confident wrong answer for the majority of the
    kunta's residents -- and the refusal has to name the partial coverage, or the
    next session reads it as "this kunta is not in the corpus" and adds it.
    """
    with pytest.raises(ManifestError, match="covered only in part"):
        manifest.resolve_municipality(municipality)
    # The manifest now carries the document's own Finnish rather than an English
    # paraphrase, because that string is quoted to a resident (SPEC-mvp-demo,
    # tracer 2). The fact under test is unchanged: the refusal names the areas.
    with pytest.raises(ManifestError, match="Mouhijärven ja Suodenniemen"):
        manifest.resolve_municipality(municipality)


def test_a_fully_covered_municipality_still_resolves(manifest: Manifest) -> None:
    assert manifest.resolve_municipality("Tampere").key == "pirkanmaa"
    assert manifest.resolve_municipality("Turku").key == "lounais-suomi"


def test_the_eval_output_shows_the_edition_a_reader_would_cite(
    corpus: Connection[tuple[object, ...]],
    manifest: Manifest,
    golden: GoldenSet,
    morphology: Morphology,
) -> None:
    """AC7. The address says 2021; the citation must say 1.5.2026.

    Pirkanmaa's text declares `47 § VOIMAANTULO: tulevat voimaan 1.7.2021` and is
    published as the 1.5.2026 edition after five amendments, so the address is
    true and misleading at once (ADR-0006). This is the line that fixes it where
    it is read, so it is checked rather than assumed.
    """
    from fi_rag_eval.report import format_citations

    run = evaluate(corpus, manifest=manifest, golden=golden, cell=PUBLISHED, morphology=morphology)
    printed = format_citations(run)
    assert "Kunnalliset jätehuoltomääräykset, 1.5.2026 alkaen" in printed
    pirkanmaa_line = next(
        line for line in printed.split("\n") if line.strip().startswith("pirkanmaa")
    )
    assert "2021" not in pirkanmaa_line, "the edition, not the Voimaantulo date"
    assert "lounais-suomi" in printed

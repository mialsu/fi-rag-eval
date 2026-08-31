"""The product surface: an arbitrary question, and everything that must be free.

This is the only module in the package a stranger can reach, so its tests are
weighted differently from the rest of the suite. The claim under test is not
mainly "does it answer" -- it is **"does it refuse without spending"**, because
the demo endpoint built on top of this is a public surface wired to a paid
provider.

Every test here injects an answerer that RAISES if it is called. A test that
merely asserted the refusal message would pass just as happily against a version
that paid for a completion and then threw the result away.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import psycopg
import pytest

from fi_rag_eval import db
from fi_rag_eval.analyse import Analyser, Morphology
from fi_rag_eval.answer import Answer, TokenBudget, Usage
from fi_rag_eval.ask import ASK_ID, AskError, ask, municipalities
from fi_rag_eval.manifest import Manifest
from fi_rag_eval.report import format_asked


class _Spent(AssertionError):
    """Raised by the stub answerer. Its existence in a traceback IS the failure."""


def never_answers(
    *,
    question_id: str,
    question: str,
    hits: Sequence[db.Hit],
    bodies: Mapping[str, str],
    budget: TokenBudget,
    model: str = "",
    reasoning: bool = True,
) -> Answer:
    raise _Spent(
        "the answerer was called, so this path costs money. Every refusal in "
        "ask.ask must happen before the model call."
    )


def canned(text: str, *, refused: bool, citations: tuple[str, ...] = ()) -> object:
    """An answerer that returns a fixed answer and records what it was given."""
    seen: dict[str, object] = {}

    def answerer(
        *,
        question_id: str,
        question: str,
        hits: Sequence[db.Hit],
        bodies: Mapping[str, str],
        budget: TokenBudget,
        model: str = "",
        reasoning: bool = True,
    ) -> Answer:
        seen["question_id"] = question_id
        seen["question"] = question
        seen["hits"] = tuple(hits)
        seen["bodies"] = dict(bodies)
        return Answer(
            question_id=question_id,
            text=text,
            refused=refused,
            citations=citations,
            model="stub",
            finish_reason="stop",
            usage=Usage(
                prompt_tokens=1,
                completion_tokens=1,
                reasoning_tokens=0,
                total_tokens=2,
                cost_usd=0.0,
            ),
        )

    answerer.seen = seen  # type: ignore[attr-defined]
    return answerer


class TestEveryRefusalIsFree:
    """No model call. Asserted by an answerer that raises, not by reading a message."""

    def test_an_empty_question_costs_nothing(
        self, corpus: psycopg.Connection[tuple[object, ...]], manifest: Manifest
    ) -> None:
        with pytest.raises(AskError, match="no question was asked"):
            ask(
                corpus,
                manifest=manifest,
                question="   ",
                municipality="Turku",
                answerer=never_answers,
            )

    def test_an_unknown_municipality_costs_nothing(
        self, corpus: psycopg.Connection[tuple[object, ...]], manifest: Manifest
    ) -> None:
        """AC14's other half: it must not silently pick one either."""
        with pytest.raises(AskError, match="Helsinki"):
            ask(
                corpus,
                manifest=manifest,
                question="Pitääkö mökillä olla jäteastia?",
                municipality="Helsinki",
                answerer=never_answers,
            )

    def test_a_partially_covered_municipality_costs_nothing_and_says_so(
        self, corpus: psycopg.Connection[tuple[object, ...]], manifest: Manifest
    ) -> None:
        """Sastamala. ADR-0002 as amended, reaching a user for the first time.

        Pirkanmaa claims Sastamala only for the former Mouhijärvi and Suodenniemi
        areas, so the map omits it and a resident is refused an answer that partly
        exists. Accepted, and the refusal names the partial coverage rather than
        pretending the municipality is unknown.
        """
        with pytest.raises(AskError, match="only in part"):
            ask(
                corpus,
                manifest=manifest,
                question="Pitääkö mökillä olla jäteastia?",
                municipality="Sastamala",
                answerer=never_answers,
            )

    def test_a_question_that_normalises_to_nothing_costs_nothing(
        self, corpus: psycopg.Connection[tuple[object, ...]], manifest: Manifest
    ) -> None:
        with pytest.raises(AskError, match="no searchable words"):
            ask(
                corpus,
                manifest=manifest,
                question="? ... §",
                municipality="Turku",
                answerer=never_answers,
            )

    def test_a_question_that_retrieves_nothing_costs_nothing(
        self, corpus: psycopg.Connection[tuple[object, ...]], manifest: Manifest
    ) -> None:
        """Real words, no match. There is no context, so there is nothing to answer from."""
        with pytest.raises(AskError, match="no context to answer from"):
            ask(
                corpus,
                manifest=manifest,
                question="fotosynteesi kloroplasti mitokondrio",
                municipality="Turku",
                answerer=never_answers,
            )


class TestItRetrievesTheWayTheHarnessMeasures:
    """A second retrieval behind the demo would drift from every published number."""

    def test_the_context_it_answers_from_is_the_published_cells_top_k(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
    ) -> None:
        answerer = canned("vastaus", refused=False)
        asked = ask(
            corpus,
            manifest=manifest,
            question="Kuinka usein sekajäteastia on tyhjennettävä?",
            municipality="Turku",
            morphology=morphology,
            answerer=answerer,  # type: ignore[arg-type]
        )
        assert asked.cell == "lemma-reasm/0"
        assert len(asked.hits) == 5
        assert [h.position for h in asked.hits] == [1, 2, 3, 4, 5]
        # The answerer saw a body for every retrieved chunk and nothing else: a
        # missing body would be answered from a truncated context, and a corpus-wide
        # dict would put chunks in scope the ranking never chose.
        seen = answerer.seen  # type: ignore[attr-defined]
        assert set(seen["bodies"]) == {h.address for h in asked.hits}

    def test_the_question_id_carries_no_part_of_the_question(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
    ) -> None:
        """ "No personal data, ever." A stranger's words must not become an id.

        `answer_question` puts the id in its error messages, so an id derived from
        the text would put the asker's own sentence into a log line the moment
        anything failed.
        """
        answerer = canned("vastaus", refused=False)
        ask(
            corpus,
            manifest=manifest,
            question="Naapurini Matti polttaa risuja, saako niin tehdä?",
            municipality="Turku",
            morphology=morphology,
            answerer=answerer,  # type: ignore[arg-type]
        )
        seen = answerer.seen  # type: ignore[attr-defined]
        assert seen["question_id"] == ASK_ID == "ask"
        assert "Matti" not in seen["question_id"]


class TestTheJurisdictionFilterHoldsOnTheNewSurface:
    """The #1 product failure mode, re-checked where a guard is likeliest to regress."""

    @pytest.mark.parametrize(
        ("municipality", "authority"),
        [("Turku", "lounais-suomi"), ("Tampere", "pirkanmaa")],
    )
    def test_every_retrieved_chunk_belongs_to_the_asked_authority(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
        municipality: str,
        authority: str,
    ) -> None:
        asked = ask(
            corpus,
            manifest=manifest,
            question="Kuinka usein jäteastia on tyhjennettävä?",
            municipality=municipality,
            morphology=morphology,
            answerer=canned("vastaus", refused=False),  # type: ignore[arg-type]
        )
        assert asked.authority_key == authority
        assert {hit.authority_key for hit in asked.hits} == {authority}
        assert all(hit.address.startswith(authority + "@") for hit in asked.hits)

    def test_the_same_question_gets_DIFFERENT_context_in_the_two_jurisdictions(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
    ) -> None:
        """Otherwise the filter could be inert and every test above would still pass."""
        question = "Kuinka usein jäteastia on tyhjennettävä?"
        turku = ask(
            corpus,
            manifest=manifest,
            question=question,
            municipality="Turku",
            morphology=morphology,
            answerer=canned("x", refused=False),  # type: ignore[arg-type]
        )
        tampere = ask(
            corpus,
            manifest=manifest,
            question=question,
            municipality="Tampere",
            morphology=morphology,
            answerer=canned("x", refused=False),  # type: ignore[arg-type]
        )
        assert {h.address for h in turku.hits}.isdisjoint({h.address for h in tampere.hits})


class TestTheMunicipalityList:
    def test_it_offers_every_covered_municipality_and_omits_sastamala(
        self, manifest: Manifest
    ) -> None:
        names = municipalities(manifest)
        assert "Turku" in names
        assert "Tampere" in names
        assert "Sastamala" not in names, "partial coverage: ADR-0002 as amended"
        assert list(names) == sorted(names)


class TestRendering:
    def test_a_refusal_still_prints_what_it_was_given(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
    ) -> None:
        """The demo's whole argument: a reader can check the refusal was honest."""
        asked = ask(
            corpus,
            manifest=manifest,
            question="Kuinka usein jäteastia on tyhjennettävä?",
            municipality="Turku",
            morphology=morphology,
            answerer=canned("En voi vastata otteiden perusteella.", refused=True),  # type: ignore[arg-type]
        )
        rendered = format_asked(asked)
        assert "REFUSED" in rendered
        for hit in asked.hits:
            assert hit.address in rendered


class TestTheAUTHORITYTermIsLoadBearingOnItsOwn:
    """Proving the filter this project calls its #1 defence, in isolation.

    Found on 31 Aug 2026 while trying to see the jurisdiction tests above go red:
    **they do not.** `db.search` filters on `authority_key` AND `effective_date`,
    and this corpus's two authorities have different dates (2024-08-01 and
    2021-07-01), so the DATE alone separates them. Delete the `authority_key`
    term and every other test in this file still passes.

    `CLAUDE.md` records the isolation assertion as *"seen red by deleting the WHERE
    clause"* -- true, and it removes both terms at once, so it never told the two
    apart. ADR-0006 anticipates a second edition per authority; on that day the
    dates stop separating and the authority term becomes load-bearing for the
    first time, having never been tested.

    So this test makes the dates USELESS as a separator: it plants one authority's
    chunk under the other's effective date, inside a transaction that is rolled
    back. Only the `authority_key` term can then keep it out.
    """

    def test_a_foreign_chunk_sharing_our_effective_date_is_still_not_retrievable(
        self, corpus: psycopg.Connection[tuple[object, ...]], morphology: Morphology
    ) -> None:
        planted = "pirkanmaa@2024-08-01#9999"
        body = (
            "9999 § ISTUTETTU PYKÄLÄ Jäteastia on tyhjennettävä neljän viikon välein "
            "ja jäteastian tyhjennysväli on neljä viikkoa."
        )
        lexemes = morphology.query_lexemes(
            "Kuinka usein jäteastia on tyhjennettävä?", Analyser.LEMMA_REASM, stopwords=frozenset()
        )
        try:
            with corpus.cursor() as cur:
                # Lounais-Suomi's date, Pirkanmaa's authority. The FK needs a
                # matching source row, so that is planted too.
                cur.execute(
                    "INSERT INTO source (authority_key, effective_date, title, url, sha256) "
                    "VALUES ('pirkanmaa', '2024-08-01', 'planted', 'planted', 'planted')"
                )
                cur.execute(
                    "INSERT INTO chunk (address, authority_key, effective_date, clause, "
                    "citation, body, content_sha256, lemma_reasm_tsv) "
                    "VALUES (%s, 'pirkanmaa', '2024-08-01', 9999, 'planted', %s, 'x', "
                    "to_tsvector('simple', %s))",
                    (planted, body, " ".join(lexemes)),
                )

            # The planted chunk IS reachable when asked for as Pirkanmaa under that
            # date -- otherwise this test could pass because the row never indexed.
            reachable = db.search(
                corpus,
                tsquery=db.or_tsquery(lexemes),
                authority_key="pirkanmaa",
                effective_date=date(2024, 8, 1),
                limit=5,
                analyser=Analyser.LEMMA_REASM,
                normalisation=0,
            )
            assert planted in {hit.address for hit in reachable}, (
                "the planted chunk did not index, so the assertion below would pass "
                "for the wrong reason"
            )

            # Same date, different authority. Only `authority_key` can exclude it now.
            got = db.search(
                corpus,
                tsquery=db.or_tsquery(lexemes),
                authority_key="lounais-suomi",
                effective_date=date(2024, 8, 1),
                limit=50,
                analyser=Analyser.LEMMA_REASM,
                normalisation=0,
            )
            assert planted not in {hit.address for hit in got}
            assert {hit.authority_key for hit in got} == {"lounais-suomi"}
        finally:
            # Session-scoped fixture: the corpus every other test shares must be
            # left exactly as found, so this is cleaned up rather than rolled back
            # at some outer boundary that may not exist.
            with corpus.cursor() as cur:
                cur.execute("DELETE FROM chunk WHERE address = %s", (planted,))
                cur.execute(
                    "DELETE FROM source WHERE authority_key = 'pirkanmaa' "
                    "AND effective_date = '2024-08-01'"
                )
            corpus.commit()

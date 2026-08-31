"""The demo surface: what must be free, what must be escaped, what must not drift.

`SPEC-mvp-demo` tracer 2, AD1-AD10. This is the only module in the package a
**stranger** will be able to reach, so its tests are weighted the way
`test_ask.py`'s are: the central claim is not "does it answer" but *"does it
refuse without spending, and is it still the measured pipeline underneath"*.

Every test that exercises the answering path injects an answerer that **raises**
if it is called, or a canned one that records what it was handed. A test that
merely asserted the page text would pass just as happily against a version that
paid for a completion and threw the result away.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import psycopg
import pytest
from starlette.testclient import TestClient

from fi_rag_eval import access, db, serve
from fi_rag_eval import ask as ask_module
from fi_rag_eval.analyse import Morphology
from fi_rag_eval.answer import Answer, AnswerError, ProxyError, TokenBudget, Usage
from fi_rag_eval.ask import AskError
from fi_rag_eval.evaluate import PUBLISHED
from fi_rag_eval.manifest import Manifest
from fi_rag_eval.serve import (
    MAX_BODY_BYTES,
    MAX_QUESTION_CHARS,
    Html,
    create_app,
    esc,
    load_template,
    page,
    render,
    retrieval_names_used,
)

SERVE_SOURCE = Path(serve.__file__)


class _Spent(AssertionError):
    """Raised by the stub answerer. Its presence in a traceback IS the failure."""


class _Touched(AssertionError):
    """Raised by the stub connect. `GET /` must not open a database connection."""


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
        "the answerer was called, so this request costs money. Every refusal on "
        "the demo surface must happen before the model call."
    )


def never_connects() -> psycopg.Connection[tuple[object, ...]]:
    raise _Touched("a database connection was opened on a path that must not need one")


def canned(text: str, *, refused: bool, citations: tuple[str, ...] = ()) -> object:
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

    return answerer


class TokenClient:
    """A `TestClient` that routes `/` and `/ask` through one live token.

    The demo is gated (ADR-0013): there is no ungated `/ask` any more. Rather than
    thread a token through every assertion about rendering, escaping and refusals,
    this rewrites exactly two paths and leaves everything else alone.

    **It hides nothing that is under test.** The gate has its own tests below
    (`TestNothingSpendsWithoutALiveToken`, `TestTheCapsBiteOnTheSurface`) and they
    use the raw paths with no wrapper, precisely so the gate is never proven by a
    helper that assumes it.
    """

    def __init__(self, client: TestClient, token: str) -> None:
        self._client = client
        self.token = token

    def _route(self, path: str) -> str:
        if path == "/":
            return f"/d/{self.token}"
        if path == "/ask":
            return f"/d/{self.token}/ask"
        return path

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return cast(httpx.Response, self._client.get(self._route(path), **kwargs))

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return cast(httpx.Response, self._client.post(self._route(path), **kwargs))


def a_link(store: psycopg.Connection[tuple[object, ...]], queries: int = 500) -> str:
    """A token generous enough that no test about something else hits a cap."""
    return access.issue(store, queries=queries, lifetime=timedelta(days=1)).token


def store_opener(url: str) -> serve.StoreConnect:
    """A fresh connection per call, because `serve` closes what it is given."""
    return lambda: access.connect(url)


def used(store: psycopg.Connection[tuple[object, ...]], token: str) -> int:
    """How many queries a token has spent, read after the app committed.

    The rollback is not cosmetic: this connection is not autocommit, so without
    ending its transaction the next SELECT reads the snapshot from before the
    request.
    """
    store.rollback()
    found = access.find(store, token)
    assert found is not None
    return found.queries_used


@pytest.fixture
def pure_client(
    manifest: Manifest, store: psycopg.Connection[tuple[object, ...]], store_url: str
) -> TokenClient:
    """An app with a real gate but NO corpus and NO analyser.

    Everything reachable through it is a path that must not touch either -- which
    is most of the point.
    """
    app = create_app(
        manifest=manifest,
        morphology=None,
        store_connect=store_opener(store_url),
        connect=never_connects,
        answerer=never_answers,
    )
    return TokenClient(TestClient(app), a_link(store))


@pytest.fixture
def live_client(
    corpus: psycopg.Connection[tuple[object, ...]],
    manifest: Manifest,
    morphology: Morphology,
    store: psycopg.Connection[tuple[object, ...]],
    store_url: str,
) -> TokenClient:
    """The real thing, minus the money.

    Depends on `corpus` for the ingest but lets the app open its OWN connections:
    psycopg's context manager closes the connection it is given, so handing over
    the session-scoped one would close the corpus fixture out from under the rest
    of the suite after the first request.
    """
    app = create_app(
        manifest=manifest,
        morphology=morphology,
        store_connect=store_opener(store_url),
        answerer=never_answers,
    )
    return TokenClient(TestClient(app), a_link(store))


# ---------------------------------------------------------------------------
# AD1 - the page and the municipality list
# ---------------------------------------------------------------------------


class TestThePage:
    def test_it_renders_and_touches_no_database(self, pure_client: TokenClient) -> None:
        response = pure_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_the_kunta_list_is_the_manifests_and_omits_sastamala(
        self, pure_client: TokenClient, manifest: Manifest
    ) -> None:
        body = pure_client.get("/").text
        for name in ask_module.municipalities(manifest):
            assert f'<option value="{name}"' in body
        assert "Sastamala" not in body, "partial coverage: ADR-0002 as amended"

    def test_it_opens_on_NOTHING_chosen(self, pure_client: TokenClient) -> None:
        """The load-bearing option.

        A dropdown defaulting to its first entry would make the harness pick a
        jurisdiction on the asker's behalf -- the one thing
        `manifest.resolve_municipality` exists to refuse, and what `CLAUDE.md`'s
        third verification layer forbids in as many words.
        """
        body = pure_client.get("/").text
        assert '<option value="" selected>' in body

    def test_no_internal_identifier_reaches_the_page(self, pure_client: TokenClient) -> None:
        """REVERSED on the Owner's instruction, 31 Aug 2026.

        This test previously asserted the OPPOSITE -- that the page names its cell,
        on the ground that "a demo that hides its configuration is a demo of an
        unnamed pipeline". That argument was about a reviewer reading the
        repository, and it put `lemma-reasm/0` in front of a resident.
        `CLAUDE.md`'s definition of done forbids raw IDs on a surface, so the cell
        and the authority key are gone from the page and stay in the `serve`
        startup banner, where an operator looks for them.

        Chunk addresses are deliberately NOT covered: they are the citation a
        reader checks, which is the demo's whole argument.
        """
        body = pure_client.get("/").text
        assert PUBLISHED.name == "lemma-reasm/0"
        assert PUBLISHED.name not in body
        for internal in ("lemma-reasm", "snowball", "lemma-baseform", "ts_rank"):
            assert internal not in body, f"internal identifier {internal!r} on the page"

    def test_the_footer_speaks_finnish_and_not_jargon(self, pure_client: TokenClient) -> None:
        """The enforcer for the defect the Owner found by READING the page.

        The footer used to say `mittausharnessissa` -- an invented compound around
        an English word with no Finnish currency -- plus `analysaattori` and the
        cell name, all of it written for a code reviewer and set in a resident's
        page. 518 green tests said nothing about it, because none of them could.

        This cannot check that the Finnish is GOOD; nothing automated can, and
        `REVIEW-DEBT.md` says so. It pins the specific words that were wrong, so
        they cannot come back unnoticed.
        """
        body = pure_client.get("/").text
        for jargon in ("harness", "analysaattori", "normalisointi", "cell", "retrieval"):
            assert jargon not in body.lower(), f"jargon {jargon!r} is back on the page"
        # And the thing the footer must say, because a resident could act on this.
        assert "ei virallinen neuvo" in body
        assert "Kysymyksiä ei tallenneta" in body


# ---------------------------------------------------------------------------
# AD7, AD10 - the transport, and the one refusal that needs no corpus
# ---------------------------------------------------------------------------


class TestTheTransport:
    def test_the_question_cannot_travel_in_a_url(self, pure_client: TokenClient) -> None:
        """AD7. A GET would put a resident's words in three logs nobody controls."""
        assert pure_client.get("/ask").status_code == 405

    def test_an_over_long_question_is_refused_before_anything_is_opened(
        self, pure_client: TokenClient
    ) -> None:
        """AD10. The prompt carries the question verbatim, so length is spend.

        Refused before the connection **and** before the answerer: the stub for
        each of those raises, so this passing means neither was reached.
        """
        response = pure_client.post(
            "/ask",
            data={"kysymys": "ä" * (MAX_QUESTION_CHARS + 1), "kunta": "Turku"},
        )
        assert response.status_code == 400
        assert "liian pitkä" in response.text

    def test_an_over_large_body_is_refused_while_still_streaming(
        self, pure_client: TokenClient
    ) -> None:
        """A body cap, not a question cap. The two are different limits.

        `MAX_QUESTION_CHARS` bounds what reaches the model; this bounds what
        reaches memory, and it is checked chunk by chunk so a body with no
        `Content-Length` cannot grow without bound.
        """
        response = pure_client.post(
            "/ask",
            content=b"kysymys=" + b"a" * (MAX_BODY_BYTES + 1),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 413
        assert "liian suuri" in response.text

    def test_a_multipart_body_yields_none_of_the_named_fields(self) -> None:
        """One form, one parser. `python-multipart` is not a dependency, and a
        file-upload parser has no business behind this surface.

        `parse_qsl` does not *reject* a multipart body -- it produces one junk key
        from it. That is worth knowing, so this asserts the property that actually
        matters instead of an empty dict: **the named fields are absent**, so a
        multipart request lands on the empty-question refusal. Nor can such a body
        smuggle a question in, because its fields arrive as `name="kysymys"` and
        never as `kysymys=`.
        """
        multipart = b'--x\r\nContent-Disposition: form-data; name="kysymys"\r\n\r\nhei\r\n--x--'
        fields = serve.form_fields(multipart)
        assert "kysymys" not in fields
        assert "kunta" not in fields

    def test_the_kunta_field_survives_being_blank(self) -> None:
        """`keep_blank_values`. Dropping it turns "nothing chosen" into a missing
        key, and the refusal message would then be the wrong one."""
        assert serve.form_fields(b"kysymys=hei&kunta=") == {"kysymys": "hei", "kunta": ""}

    def test_a_question_at_the_limit_is_not_refused_for_length(
        self, pure_client: TokenClient
    ) -> None:
        """The boundary, from the other side: at the cap it proceeds and hits the
        stub connection. Without this, the cap could be off by any amount."""
        with pytest.raises(_Touched):
            pure_client.post("/ask", data={"kysymys": "ä" * MAX_QUESTION_CHARS, "kunta": "Turku"})


# ---------------------------------------------------------------------------
# AD8 - escaping, made structural
# ---------------------------------------------------------------------------


class TestEscaping:
    def test_a_question_containing_markup_is_escaped_on_the_page(self, manifest: Manifest) -> None:
        rendered = page(
            load_template(),
            names=ask_module.municipalities(manifest),
            question='</textarea><script>alert("xss")</script>',
        )
        assert "<script>alert" not in rendered
        assert "&lt;script&gt;alert" in rendered
        assert "</textarea><script" not in rendered

    def test_a_municipality_name_is_escaped_in_the_option_value(self) -> None:
        rendered = serve.options(['" onfocus="x'], chosen="")
        assert 'onfocus="x' not in rendered.text.replace("&quot;", "\x00")
        assert "&quot;" in rendered.text

    def test_the_renderer_accepts_only_pre_escaped_html(self) -> None:
        """The guarantee is a mypy error, not a convention.

        `render` takes `Mapping[str, Html]`, so a raw `str` slot fails the
        typecheck gate. This test pins the runtime half: an `Html` is not a `str`,
        so the two cannot be confused by accident either.
        """
        assert not isinstance(esc("<b>"), str)
        assert esc("<b>") == Html("&lt;b&gt;")

    def test_the_template_and_the_slots_must_agree_exactly(self) -> None:
        """A partially rendered page would ship `{{RESULT}}` to a reader."""
        with pytest.raises(ValueError, match="missing"):
            render("{{A}}{{B}}", {"A": Html("x")})
        with pytest.raises(ValueError, match="extra"):
            render("{{A}}", {"A": Html("x"), "B": Html("y")})
        with pytest.raises(ValueError, match="unclosed"):
            render("{{A", {})
        assert render("<p>{{A}}</p>", {"A": Html("&amp;")}) == "<p>&amp;</p>"

    def test_the_shipped_template_is_exactly_what_page_fills(self, manifest: Manifest) -> None:
        """Guards the two files drifting apart: a slot added to the HTML with no
        value in `page` raises rather than shipping a literal `{{...}}`."""
        rendered = page(load_template(), names=ask_module.municipalities(manifest))
        assert "{{" not in rendered


# ---------------------------------------------------------------------------
# AD6 - one retrieval, enforced
# ---------------------------------------------------------------------------


class TestThereIsOnlyOneRetrieval:
    def test_the_default_asker_IS_the_harnesss_ask(self) -> None:
        """By identity, not by resemblance.

        A demo on its own retrieval would drift from every published number and
        both would still look fine (`CLAUDE.md`).
        """
        default = inspect.signature(create_app).parameters["asker"].default
        assert default is ask_module.ask

    def test_serve_py_names_no_retrieval_primitive(self) -> None:
        used = retrieval_names_used(SERVE_SOURCE.read_text(encoding="utf-8"))
        assert used == frozenset(), (
            f"serve.py references retrieval primitives {sorted(used)}. Retrieval "
            "belongs to ask.ask, which the harness measures."
        )

    def test_the_check_itself_can_go_red(self) -> None:
        """Otherwise the assertion above is a check that cannot fail."""
        assert retrieval_names_used("from fi_rag_eval.db import search") == {"search"}
        assert retrieval_names_used("db.search(conn)") == {"search"}
        assert retrieval_names_used("x = or_tsquery(y)") == {"or_tsquery"}
        assert retrieval_names_used("ask(conn)") == frozenset()

    def test_ask_py_names_them_all_so_the_list_is_not_stale(self) -> None:
        """The forbidden list is only meaningful if `ask.ask` really uses them."""
        used = retrieval_names_used(Path(ask_module.__file__).read_text(encoding="utf-8"))
        assert used == serve.FORBIDDEN_NAMES


# ---------------------------------------------------------------------------
# AD3, AD4 - every refusal is free, on the new surface too
# ---------------------------------------------------------------------------


class TestEveryRefusalIsFree:
    """The answerer raises. Reaching it is the failure, not a wrong message."""

    @pytest.mark.parametrize(
        ("question", "kunta", "expected"),
        [
            ("   ", "Turku", "Kysymys puuttuu"),
            ("Pitääkö mökillä olla jäteastia?", "Helsinki", "Helsinki"),
            ("Pitääkö mökillä olla jäteastia?", "Sastamala", "vain osittain"),
            ("? ... §", "Turku", "ei löytynyt yhtään hakusanaa"),
            ("fotosynteesi kloroplasti mitokondrio", "Turku", "kieltäytyminen, ei virhe"),
        ],
        ids=["empty", "unknown-kunta", "partial-coverage", "no-lexemes", "no-hits"],
    )
    def test_it_refuses_without_spending(
        self, live_client: TokenClient, question: str, kunta: str, expected: str
    ) -> None:
        response = live_client.post("/ask", data={"kysymys": question, "kunta": kunta})
        assert response.status_code == 400
        assert expected in response.text

    def test_no_kunta_chosen_never_reaches_the_answerer(self, live_client: TokenClient) -> None:
        """AD4, and `CLAUDE.md`'s layer 3: it must not silently pick one."""
        response = live_client.post(
            "/ask", data={"kysymys": "Kuinka usein jäteastia on tyhjennettävä?", "kunta": ""}
        )
        assert response.status_code == 400
        assert "Kuntaa ei ole valittu" in response.text

    def test_a_multipart_request_refuses_as_an_empty_question(
        self, live_client: TokenClient
    ) -> None:
        """The HTTP half of the parser decision, and it needs the live client.

        Not the pure one, and the reason is a real property of the design: the
        empty-question guard lives in `ask.ask`, **after** the connection is
        opened. So a refusal here is free of the *model* -- the only thing that
        costs money, asserted by the raising answerer -- but not of one local
        Postgres connection. `serve` does not duplicate the guard to change that:
        a second copy of the check would ship a second refusal message, and
        tracer 3's token check lands in front of all of this anyway. Confessed.
        """
        response = live_client.post(
            "/ask",
            content=b'--x\r\nContent-Disposition: form-data; name="kysymys"\r\n\r\nhei\r\n--x--',
            headers={"content-type": "multipart/form-data; boundary=x"},
        )
        assert response.status_code == 400
        assert "Kysymys puuttuu" in response.text

    def test_a_refusal_page_still_offers_the_form_and_keeps_the_question(
        self, live_client: TokenClient
    ) -> None:
        """A dead end is not an honest empty state."""
        response = live_client.post("/ask", data={"kysymys": "? ... §", "kunta": "Turku"})
        assert "? ... §" in response.text
        assert '<option value="Turku" selected>' in response.text

    def test_markup_in_a_refused_question_is_escaped(self, live_client: TokenClient) -> None:
        """AD8 through HTTP, not only through `page`."""
        response = live_client.post(
            "/ask",
            data={"kysymys": '<script>alert("xss")</script>', "kunta": "Helsinki"},
        )
        assert response.status_code == 400
        assert "<script>alert" not in response.text
        assert "&lt;script&gt;" in response.text


# ---------------------------------------------------------------------------
# AD2, AD5 - it answers, and the jurisdiction still forks
# ---------------------------------------------------------------------------


class TestItAnswers:
    def test_the_page_shows_the_jurisdiction_the_excerpts_the_answer_and_the_price(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        client = TokenClient(
            TestClient(
                create_app(
                    manifest=manifest,
                    morphology=morphology,
                    store_connect=store_opener(store_url),
                    answerer=canned(  # type: ignore[arg-type]
                        "Neljän viikon välein [#26].",
                        refused=False,
                        citations=("lounais-suomi@2024-08-01#26",),
                    ),
                )
            ),
            a_link(store),
        )
        response = client.post(
            "/ask",
            data={"kysymys": "Kuinka usein sekajäteastia on tyhjennettävä?", "kunta": "Turku"},
        )
        assert response.status_code == 200
        body = response.text
        assert "Lounais-Suomen jätehuoltolautakunta" in body
        assert "(lounais-suomi)" not in body, "the authority KEY is an internal id"
        assert PUBLISHED.name not in body, "the cell is an internal id"
        assert "VASTAUS" in body
        assert "Neljän viikon välein" in body
        assert "lounais-suomi@2024-08-01#26" in body
        assert "$0.0000" in body and "mitattu, ei arvioitu" in body
        # Five retrieved addresses, each with its citation, on the page.
        assert body.count('<span class="addr">lounais-suomi@2024-08-01#') >= 5

    def test_a_refusal_shows_the_excerpts_it_declined_to_answer_from(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        """The demo's whole argument: a reader can check the refusal was honest."""
        client = TokenClient(
            TestClient(
                create_app(
                    manifest=manifest,
                    morphology=morphology,
                    store_connect=store_opener(store_url),
                    answerer=canned(  # type: ignore[arg-type]
                        "En voi vastata otteiden perusteella.", refused=True
                    ),
                )
            ),
            a_link(store),
        )
        response = client.post(
            "/ask",
            data={"kysymys": "Kuinka usein jäteastia on tyhjennettävä?", "kunta": "Turku"},
        )
        assert response.status_code == 200, "a refusal is an answer, not an HTTP error"
        assert "EI VASTAUSTA" in response.text
        assert response.text.count('<span class="addr">lounais-suomi@2024-08-01#') >= 5
        assert "ei viittauksia" in response.text


class TestTheJurisdictionForkSurvivesTheHttpLayer:
    def test_the_same_question_retrieves_DISJOINT_excerpts_in_the_two_kunnat(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        """AD5. The #1 product failure mode, re-checked where a guard regresses."""
        client = TokenClient(
            TestClient(
                create_app(
                    manifest=manifest,
                    morphology=morphology,
                    store_connect=store_opener(store_url),
                    answerer=canned("x", refused=False),  # type: ignore[arg-type]
                )
            ),
            a_link(store),
        )
        question = "Kuinka usein jäteastia on tyhjennettävä?"
        pages = {}
        for kunta in ("Turku", "Tampere"):
            response = client.post("/ask", data={"kysymys": question, "kunta": kunta})
            assert response.status_code == 200
            pages[kunta] = response.text

        turku = _addresses(pages["Turku"])
        tampere = _addresses(pages["Tampere"])
        assert turku and tampere
        assert turku.isdisjoint(tampere)
        assert all(a.startswith("lounais-suomi@") for a in turku)
        assert all(a.startswith("pirkanmaa@") for a in tampere)
        assert "pirkanmaa" not in pages["Turku"]
        assert "lounais-suomi" not in pages["Tampere"]


class TestTheCopyIsInTheAskersLanguage:
    """`CLAUDE.md`'s definition of done: copy is in the user's language.

    Found by running the page for real: the chrome was Finnish and every refusal
    a resident could provoke was English, because `AskError`'s message was written
    for a CLI its maintainer reads. Both texts now live at the raise site.
    """

    @pytest.mark.parametrize(
        ("question", "kunta", "finnish", "english_that_must_not_appear"),
        [
            ("   ", "Turku", "Kysymys puuttuu", "no question was asked"),
            (
                "Pitääkö mökillä olla jäteastia?",
                "",
                "Kuntaa ei ole valittu",
                "no municipality was given",
            ),
            (
                "Pitääkö mökillä olla jäteastia?",
                "Helsinki",
                "ei ole tässä aineistossa",
                "no authority in the manifest",
            ),
            (
                "Pitääkö mökillä olla jäteastia?",
                "Sastamala",
                "vain osittain",
                "covered only in part",
            ),
            (
                "fotosynteesi kloroplasti mitokondrio",
                "Turku",
                "kieltäytyminen, ei virhe",
                "This is a refusal, not an error",
            ),
        ],
        ids=["empty", "no-kunta", "unknown-kunta", "partial-coverage", "no-hits"],
    )
    def test_a_refusal_reads_in_finnish_and_leaks_no_maintainer_english(
        self,
        live_client: TokenClient,
        question: str,
        kunta: str,
        finnish: str,
        english_that_must_not_appear: str,
    ) -> None:
        response = live_client.post("/ask", data={"kysymys": question, "kunta": kunta})
        assert response.status_code == 400
        assert finnish in response.text
        assert english_that_must_not_appear not in response.text

    def test_the_authority_name_is_never_hand_inflected(self, live_client: TokenClient) -> None:
        """The first live run rendered "jätehuoltolautakuntan".

        The genitive of `lautakunta` is `lautakunnan` -- consonant gradation, the
        exact hazard this project uses voikko for. A demo is not the place to
        hand-roll a second morphology, so the name stays in the nominative. This
        pins the specific wrong form, and the general rule beside it.
        """
        response = live_client.post(
            "/ask",
            data={"kysymys": "fotosynteesi kloroplasti mitokondrio", "kunta": "Turku"},
        )
        assert "jätehuoltolautakuntan" not in response.text

    def test_the_authority_name_is_rendered_UNINFLECTED_where_it_appears(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        """The positive half, moved 31 Aug 2026 after the refusal stopped naming it.

        The no-hits refusal used to end `Viranomainen: Lounais-Suomen
        jätehuoltolautakunta.` -- bolted on precisely because I was dodging the
        genitive that had already bitten once. The Owner's copy pass deleted it, so
        the *negative* assertion above still guards that path while the name itself
        is now only on an answered page. Asserting it there keeps both halves alive
        instead of quietly dropping the one that proves the name is rendered at all.
        """
        client = TokenClient(
            TestClient(
                create_app(
                    manifest=manifest,
                    morphology=morphology,
                    store_connect=store_opener(store_url),
                    answerer=canned("vastaus", refused=False),  # type: ignore[arg-type]
                )
            ),
            a_link(store),
        )
        response = client.post(
            "/ask",
            data={"kysymys": "Kuinka usein jäteastia on tyhjennettävä?", "kunta": "Turku"},
        )
        assert "Turku &rarr; Lounais-Suomen jätehuoltolautakunta" in response.text
        assert "jätehuoltolautakuntan" not in response.text
        assert "jätehuoltolautakunnan" not in response.text, (
            "even the CORRECT genitive means something is inflecting the name"
        )

    def test_the_finnish_refusal_carries_no_english_prose(self, live_client: TokenClient) -> None:
        """Sastamala's coverage detail was English inside a Finnish sentence.

        The manifest now carries the authority's own Finnish, so the resident reads
        the document's words rather than a translation of a paraphrase.
        """
        response = live_client.post(
            "/ask",
            data={"kysymys": "Pitääkö mökillä olla jäteastia?", "kunta": "Sastamala"},
        )
        body = response.text
        assert "Mouhijärven ja Suodenniemen osalta" in body
        for english in ("covers only", "the former", "areas only"):
            assert english not in body, f"English prose {english!r} reached the page"

    def test_sastamalas_partial_coverage_survives_the_translation(
        self, live_client: TokenClient
    ) -> None:
        """ADR-0002 as amended is the nuance most easily lost in a second text.

        The Finnish must still name *which* parts are covered, or the refusal has
        become vaguer than the English it replaced.
        """
        response = live_client.post(
            "/ask", data={"kysymys": "Pitääkö mökillä olla jäteastia?", "kunta": "Sastamala"}
        )
        assert "Mouhijärv" in response.text and "Suodenniem" in response.text

    def test_every_ask_error_must_supply_finnish(self) -> None:
        """Required, not defaulted: mypy names a new raise site that forgets it."""
        with pytest.raises(TypeError):
            AskError("english only")  # type: ignore[call-arg]


class TestInternalMessagesNeverReachThePage:
    """`db.connect` puts the database URL, credentials and all, in its message.

    Found while translating the refusals: that message was being rendered. This
    page is reachable by someone who must not read it.
    """

    def test_a_database_failure_discloses_no_url_and_no_password(
        self,
        manifest: Manifest,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        secret = "postgresql://fi_rag_eval:s3cr3t-p4ss@db.internal:5434/fi_rag_eval"

        def broken() -> psycopg.Connection[tuple[object, ...]]:
            raise db.DatabaseError(f"cannot reach Postgres at {secret}: refused")

        client = TokenClient(
            TestClient(
                create_app(
                    manifest=manifest,
                    morphology=None,
                    store_connect=store_opener(store_url),
                    connect=broken,
                    answerer=never_answers,
                )
            ),
            a_link(store),
        )
        response = client.post("/ask", data={"kysymys": "Kysymys?", "kunta": "Turku"})
        assert response.status_code == 503
        for leak in ("s3cr3t-p4ss", "db.internal", "postgresql://", "fi_rag_eval"):
            assert leak not in response.text, f"the page disclosed {leak!r}"
        assert "ei ole juuri nyt käytettävissä" in response.text

    def test_a_gateway_failure_discloses_nothing_either(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        """Needs the live corpus: a gateway error can only happen once retrieval
        has succeeded, so a stubbed connection would never reach the answerer and
        the test would pass for the wrong reason."""

        def explodes(
            *,
            question_id: str,
            question: str,
            hits: Sequence[db.Hit],
            bodies: Mapping[str, str],
            budget: TokenBudget,
            model: str = "",
            reasoning: bool = True,
        ) -> Answer:
            raise ProxyError("LiteLLM at http://localhost:4010 said: key sk-abc123 denied")

        client = TokenClient(
            TestClient(
                create_app(
                    manifest=manifest,
                    morphology=morphology,
                    store_connect=store_opener(store_url),
                    answerer=explodes,
                )
            ),
            a_link(store),
        )
        response = client.post(
            "/ask",
            data={"kysymys": "Kuinka usein jäteastia on tyhjennettävä?", "kunta": "Turku"},
        )
        assert response.status_code == 502
        assert "sk-abc123" not in response.text
        assert "localhost:4010" not in response.text
        assert "tekninen häiriö, ei kieltäytyminen" in response.text

    def test_the_types_whose_messages_are_withheld_are_named_not_remembered(self) -> None:
        assert (db.DatabaseError, AnswerError) == serve.INTERNAL_MESSAGES_NEVER_RENDERED
        assert issubclass(ProxyError, AnswerError)


class TestNothingSpendsWithoutALiveToken:
    """AD12. Raw paths, no `TokenClient` -- the gate is never proven by a helper
    that already assumes it.

    Every client here injects an answerer that RAISES and a database connection
    that RAISES, so reaching either is the failure.
    """

    @pytest.fixture
    def raw(
        self, manifest: Manifest, store: psycopg.Connection[tuple[object, ...]], store_url: str
    ) -> TestClient:
        return TestClient(
            create_app(
                manifest=manifest,
                morphology=None,
                store_connect=store_opener(store_url),
                connect=never_connects,
                answerer=never_answers,
            )
        )

    def test_there_is_NO_ungated_ask_route_at_all(self, raw: TestClient) -> None:
        """Tracer 2 had one. A route that does not exist cannot be reached by a
        forgotten bookmark, and removing it beats guarding it."""
        assert raw.post("/ask", data={"kysymys": "Kysymys?", "kunta": "Turku"}).status_code == 404
        assert raw.get("/ask").status_code == 404

    def test_the_landing_page_offers_no_usable_form(self, raw: TestClient) -> None:
        response = raw.get("/")
        assert response.status_code == 200
        assert "<form" in response.text, "the shell is still one file"
        assert " hidden>" in response.text, "but the form is not usable without a link"
        assert "henkilökohtaisella linkillä" in response.text
        for banned in ("coming soon", "tulossa", "ei tuettu"):
            assert banned not in response.text.lower()

    def test_an_unknown_token_never_reaches_the_answerer(self, raw: TestClient) -> None:
        response = raw.post("/d/ZZZZ-ZZZZ/ask", data={"kysymys": "Kysymys?", "kunta": "Turku"})
        assert response.status_code == 403
        assert "ei kelpaa" in response.text

    def test_an_unknown_token_renders_no_form_either(self, raw: TestClient) -> None:
        response = raw.get("/d/ZZZZ-ZZZZ")
        assert response.status_code == 403
        assert " hidden>" in response.text

    def test_a_token_shaped_like_an_injection_is_just_a_miss(self, raw: TestClient) -> None:
        """The token reaches SQL as a parameter, never as text."""
        response = raw.post(
            "/d/x'%20OR%201=1--/ask", data={"kysymys": "Kysymys?", "kunta": "Turku"}
        )
        assert response.status_code == 403

    def test_a_token_is_never_echoed_into_the_page_unescaped(self, raw: TestClient) -> None:
        assert "<script>" not in raw.get("/d/%3Cscript%3Ex%3C/script%3E").text


class TestTheCapsBiteOnTheSurface:
    """AD13-AD16 and AD18, through HTTP. The store tests prove the SQL; these
    prove the route actually consults it."""

    def app(
        self,
        manifest: Manifest,
        store_url: str,
        *,
        clock: access.Clock = access.utc_now,
        queries_per_day: int = access.QUERIES_PER_DAY,
        dollars_per_month: float = access.DOLLARS_PER_MONTH,
    ) -> TestClient:
        return TestClient(
            create_app(
                manifest=manifest,
                morphology=None,
                store_connect=store_opener(store_url),
                connect=never_connects,
                answerer=never_answers,
                clock=clock,
                queries_per_day=queries_per_day,
                dollars_per_month=dollars_per_month,
            )
        )

    def test_an_EXPIRED_link_never_answers(
        self,
        manifest: Manifest,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        one = access.issue(store, queries=5, lifetime=timedelta(hours=1))
        after = one.expires_at + timedelta(seconds=1)
        client = self.app(manifest, store_url, clock=lambda: after)
        response = client.post(
            f"/d/{one.token}/ask", data={"kysymys": "Kysymys?", "kunta": "Turku"}
        )
        assert response.status_code == 403
        assert "voimassaolo on päättynyt" in response.text
        assert used(store, one.token) == 0

    def test_an_OVER_CAP_link_never_answers(
        self,
        manifest: Manifest,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        one = access.issue(store, queries=1)
        client = self.app(manifest, store_url)
        body = {"kysymys": "   ", "kunta": "Turku"}  # a free refusal, so it refunds
        # Spend the one query on something that is NOT refunded: a question the
        # gate accepts and the harness then fails to serve would refund, so this
        # drives the counter through the store instead, which is the same column.
        access.reserve(store, one.token)
        store.commit()
        response = client.post(f"/d/{one.token}/ask", data=body)
        assert response.status_code == 403
        assert "kysymystä on käytetty" in response.text

    def test_a_REVOKED_link_never_answers(
        self,
        manifest: Manifest,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        one = access.issue(store, queries=5)
        access.revoke(store, one.token)
        client = self.app(manifest, store_url)
        response = client.post(
            f"/d/{one.token}/ask", data={"kysymys": "Kysymys?", "kunta": "Turku"}
        )
        assert response.status_code == 403
        assert "peruutettu" in response.text
        assert used(store, one.token) == 0

    def test_the_GLOBAL_DAILY_ceiling_stops_a_fresh_link(
        self,
        manifest: Manifest,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        spent = access.issue(store, queries=5)
        fresh = access.issue(store, queries=5)
        access.reserve(store, spent.token, queries_per_day=1)
        store.commit()
        client = self.app(manifest, store_url, queries_per_day=1)
        response = client.post(
            f"/d/{fresh.token}/ask", data={"kysymys": "Kysymys?", "kunta": "Turku"}
        )
        assert response.status_code == 403
        assert "päivittäinen kysymysmäärä on täynnä" in response.text
        assert used(store, fresh.token) == 0

    def test_the_MONTHLY_DOLLAR_ceiling_stops_a_fresh_link(
        self,
        manifest: Manifest,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        """The enforcer that guards the money, reached through HTTP."""
        spent = access.issue(store, queries=5)
        fresh = access.issue(store, queries=5)
        got = access.reserve(store, spent.token, dollars_per_month=0.01)
        access.record_spend(store, got, 0.0161)
        store.commit()
        client = self.app(manifest, store_url, dollars_per_month=0.01)
        response = client.post(
            f"/d/{fresh.token}/ask", data={"kysymys": "Kysymys?", "kunta": "Turku"}
        )
        assert response.status_code == 403
        assert "budjetti on käytetty" in response.text
        assert used(store, fresh.token) == 0


class TestAQueryIsChargedOnceAndRefundedWhenNothingWasSpent:
    """AD18. The reserve-then-refund contract, observed from outside."""

    def test_a_free_refusal_costs_the_visitor_NOTHING(
        self, live_client: TokenClient, store: psycopg.Connection[tuple[object, ...]]
    ) -> None:
        before = used(store, live_client.token)
        response = live_client.post("/ask", data={"kysymys": "   ", "kunta": "Turku"})
        assert response.status_code == 400
        assert used(store, live_client.token) == before, (
            "the visitor was charged for the harness declining"
        )
        assert "ei kuluttanut kysymystä" in response.text

    def test_an_ANSWERED_query_costs_exactly_one(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        token = a_link(store, queries=4)
        client = TestClient(
            create_app(
                manifest=manifest,
                morphology=morphology,
                store_connect=store_opener(store_url),
                answerer=canned("vastaus", refused=False),  # type: ignore[arg-type]
            )
        )
        for expected in (1, 2, 3):
            response = client.post(
                f"/d/{token}/ask",
                data={"kysymys": "Kuinka usein jäteastia on tyhjennettävä?", "kunta": "Turku"},
            )
            assert response.status_code == 200
            assert used(store, token) == expected
        # And the page tells the visitor what is left, before they ask again.
        assert "1</strong> kysymystä jäljellä" in response.text

    def test_a_MODEL_REFUSAL_still_costs_one_because_it_was_generated(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        """The distinction that matters: a refusal the MODEL produced was paid
        for, and a refusal the harness produced before any call was not."""
        token = a_link(store, queries=3)
        client = TestClient(
            create_app(
                manifest=manifest,
                morphology=morphology,
                store_connect=store_opener(store_url),
                answerer=canned("En voi vastata.", refused=True),  # type: ignore[arg-type]
            )
        )
        response = client.post(
            f"/d/{token}/ask",
            data={"kysymys": "Kuinka usein jäteastia on tyhjennettävä?", "kunta": "Turku"},
        )
        assert response.status_code == 200
        assert used(store, token) == 1

    def test_the_DISPLAYED_count_matches_the_stored_one_on_both_paths(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
        store: psycopg.Connection[tuple[object, ...]],
        store_url: str,
    ) -> None:
        """The reservation was once subtracted TWICE.

        `find` runs after `reserve`, so the row already excludes this query;
        subtracting again made the page say 2 left of 4 after a single answer.
        The refund path is the one that adds. Pinned on both, because a count a
        visitor reads and cannot verify is worse than none.
        """
        token = a_link(store, queries=4)
        client = TestClient(
            create_app(
                manifest=manifest,
                morphology=morphology,
                store_connect=store_opener(store_url),
                answerer=canned("vastaus", refused=False),  # type: ignore[arg-type]
            )
        )
        answered = client.post(
            f"/d/{token}/ask",
            data={"kysymys": "Kuinka usein jäteastia on tyhjennettävä?", "kunta": "Turku"},
        )
        assert used(store, token) == 1
        assert "<strong>3</strong> kysymystä jäljellä 4:stä" in answered.text

        refused = client.post(f"/d/{token}/ask", data={"kysymys": "   ", "kunta": "Turku"})
        assert used(store, token) == 1, "a free refusal charged a query"
        assert "<strong>3</strong> kysymystä jäljellä 4:stä" in refused.text

    def test_the_page_shows_what_the_link_is_still_worth_BEFORE_asking(
        self, pure_client: TokenClient
    ) -> None:
        body = pure_client.get("/").text
        assert "kysymystä jäljellä" in body
        assert "voimassa vielä noin" in body


class TestTheJurisdictionFilterStillRefusesOnTheGatedSurface:
    """AD17. The #1 product failure mode, re-checked once more where a new layer
    could have swallowed it."""

    def test_an_out_of_jurisdiction_question_refuses_with_a_valid_token(
        self, live_client: TokenClient
    ) -> None:
        response = live_client.post(
            "/ask", data={"kysymys": "Pitääkö mökillä olla jäteastia?", "kunta": "Helsinki"}
        )
        assert response.status_code == 400
        assert "ei ole tässä aineistossa" in response.text

    def test_a_valid_token_does_not_let_a_kunta_be_skipped(self, live_client: TokenClient) -> None:
        """A token grants queries, never a jurisdiction."""
        response = live_client.post(
            "/ask", data={"kysymys": "Kuinka usein jäteastia on tyhjennettävä?", "kunta": ""}
        )
        assert response.status_code == 400
        assert "Kuntaa ei ole valittu" in response.text


def _addresses(body: str) -> frozenset[str]:
    """Every chunk address the page rendered, read back out of the HTML."""
    out: set[str] = set()
    marker = '<span class="addr">'
    cursor = 0
    while (start := body.find(marker, cursor)) != -1:
        start += len(marker)
        end = body.find("</span>", start)
        out.add(body[start:end])
        cursor = end
    return frozenset(out)

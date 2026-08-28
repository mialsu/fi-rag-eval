"""The answering boundary's contract, with no network and no spend.

Deliberately **no live model call anywhere in this file.** `make gate` runs the
suite before every commit, and a test that spends money on every commit is a
test that gets deleted the first time it is inconvenient. The live exercise is
`fi-rag-eval answer`, run by a human -- which is confessed in REVIEW-DEBT.md
rather than papered over here.

What is covered is the part that must never be wrong: the harness's contract
with itself. A broken envelope stops the run; a bad citation does not.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from fi_rag_eval import db, gateway
from fi_rag_eval.answer import (
    ANSWERER,
    JUDGE,
    AnswerError,
    BudgetExceededError,
    MalformedAnswerError,
    TokenBudget,
    Usage,
    _envelope,
    format_context,
    master_key,
    proxy_url,
    reasoning_effort,
)

GOOD = json.dumps({"refused": False, "answer": "Kyllä [a@2024-08-01#1].", "citations": ["x"]})


def _usage(total: int = 100, cost: float = 0.001) -> Usage:
    return Usage(
        prompt_tokens=total // 2,
        completion_tokens=total - total // 2,
        reasoning_tokens=0,
        total_tokens=total,
        cost_usd=cost,
    )


def _hit(address: str, position: int = 1) -> db.Hit:
    return db.Hit(
        position=position,
        address=address,
        citation=f"{position} § Testipykälä",
        rank=1.0,
        authority_key="lounais-suomi",
    )


class TestEnvelope:
    """AC3: a malformed response is a hard error, never a skip."""

    def test_accepts_the_agreed_shape(self) -> None:
        refused, answer, citations = _envelope(GOOD, question_id="q", model="m")
        assert refused is False
        assert citations == ("x",)
        assert "Kyllä" in answer

    @pytest.mark.parametrize(
        ("raw", "because"),
        [
            ("", "empty content"),
            ("   ", "whitespace only"),
            ("not json at all", "not JSON"),
            ("[1, 2, 3]", "a JSON array, not an object"),
            ('"a string"', "a bare JSON string"),
            ('{"answer": "a", "citations": []}', "no `refused`"),
            ('{"refused": false, "citations": []}', "no `answer`"),
            ('{"refused": false, "answer": "a"}', "no `citations`"),
            ('{"refused": "no", "answer": "a", "citations": []}', "`refused` not a boolean"),
            ('{"refused": 0, "answer": "a", "citations": []}', "`refused` an int, not a bool"),
            ('{"refused": false, "answer": 7, "citations": []}', "`answer` not a string"),
            ('{"refused": false, "answer": "a", "citations": "x"}', "`citations` not a list"),
            ('{"refused": false, "answer": "a", "citations": [1]}', "`citations` not strings"),
        ],
    )
    def test_rejects_a_broken_envelope(self, raw: str, because: str) -> None:
        with pytest.raises(MalformedAnswerError):
            _envelope(raw, question_id="q", model="m")

    def test_the_question_id_and_model_are_in_the_message(self) -> None:
        """A run that stops must say which question and which model stopped it."""
        with pytest.raises(MalformedAnswerError) as caught:
            _envelope("nonsense", question_id="biojate-1", model="qwen/x")
        assert "biojate-1" in str(caught.value)
        assert "qwen/x" in str(caught.value)

    def test_a_citation_that_is_not_an_address_is_DATA_not_an_error(self) -> None:
        """The distinction this module exists to keep straight.

        A citation pointing at no chunk is the behaviour under measurement --
        `citation accuracy` is the metric that counts it. Raising here would
        delete exactly the failures the metric exists to find, and would turn a
        badly-behaved model into a broken harness.
        """
        raw = json.dumps(
            {"refused": False, "answer": "a", "citations": ["ei-ole-osoite", "42", ""]}
        )
        refused, _, citations = _envelope(raw, question_id="q", model="m")
        assert refused is False
        assert citations == ("ei-ole-osoite", "42", "")

    def test_a_refusal_is_read_from_the_field_never_from_the_prose(self) -> None:
        """Prose that sounds like an answer, with `refused` true, is a Refusal."""
        raw = json.dumps(
            {"refused": True, "answer": "Otteet eivät riitä vastaukseen.", "citations": []}
        )
        refused, _, citations = _envelope(raw, question_id="q", model="m")
        assert refused is True
        assert citations == ()


class TestTokenBudget:
    """AC6 / D8 enforcer #1: the ceiling that lives in our own code."""

    def test_records_tokens_cost_and_calls(self) -> None:
        budget = TokenBudget(ceiling=1_000)
        budget.record(_usage(total=100, cost=0.002))
        budget.record(_usage(total=250, cost=0.003))
        assert budget.tokens == 350
        assert budget.calls == 2
        assert budget.cost_usd == pytest.approx(0.005)

    def test_stays_quiet_below_the_ceiling(self) -> None:
        budget = TokenBudget(ceiling=100)
        budget.record(_usage(total=100))
        assert budget.tokens == 100

    def test_hard_fails_over_the_ceiling(self) -> None:
        budget = TokenBudget(ceiling=100)
        with pytest.raises(BudgetExceededError):
            budget.record(_usage(total=101))

    def test_a_ceiling_of_one_token_stops_the_very_first_call(self) -> None:
        """The shape AC6 is proven red with."""
        budget = TokenBudget(ceiling=1)
        with pytest.raises(BudgetExceededError) as caught:
            budget.record(_usage(total=5_000, cost=0.02))
        assert "1" in str(caught.value)
        assert "5000" in str(caught.value)

    def test_the_message_says_what_was_spent(self) -> None:
        budget = TokenBudget(ceiling=10)
        with pytest.raises(BudgetExceededError) as caught:
            budget.record(_usage(total=99, cost=0.5))
        message = str(caught.value)
        assert "0.5" in message
        assert "stopped" in message


class TestReasoningEffort:
    """The per-model vocabulary shim, measured in tracer slice 1."""

    def test_qwen_gets_the_only_words_it_accepts(self) -> None:
        assert reasoning_effort(ANSWERER, enabled=True) in {"default", "none"}
        assert reasoning_effort(ANSWERER, enabled=False) == "none"

    def test_gpt_oss_never_gets_none(self) -> None:
        """`none` is not in gpt-oss's vocabulary; sending it is an HTTP 400."""
        assert reasoning_effort(JUDGE, enabled=True) in {"low", "medium", "high"}
        assert reasoning_effort(JUDGE, enabled=False) in {"low", "medium", "high"}

    def test_the_two_models_do_not_share_a_vocabulary(self) -> None:
        assert reasoning_effort(ANSWERER, enabled=True) != reasoning_effort(JUDGE, enabled=True)


class TestFormatContext:
    def test_labels_each_excerpt_with_its_own_address(self) -> None:
        """So a cited address is checkable directly, with no lookup table between."""
        text = format_context(
            [_hit("lounais-suomi@2024-08-01#15")],
            {"lounais-suomi@2024-08-01#15": "Biojäte on lajiteltava."},
        )
        assert "[lounais-suomi@2024-08-01#15]" in text
        assert "Biojäte on lajiteltava." in text

    def test_a_retrieved_chunk_with_no_body_stops_the_run(self) -> None:
        with pytest.raises(AnswerError, match="no body"):
            format_context([_hit("lounais-suomi@2024-08-01#15")], {})

    def test_keeps_the_hits_in_rank_order(self) -> None:
        text = format_context(
            [_hit("a@2024-08-01#1", 1), _hit("a@2024-08-01#2", 2)],
            {"a@2024-08-01#1": "eka", "a@2024-08-01#2": "toka"},
        )
        assert text.index("eka") < text.index("toka")


class TestGateway:
    """That the gateway is wired -- proven without spending a token.

    Listing models costs nothing, so this can run in `make gate`. It skips
    loudly when the gateway is down, on the same terms as the database-backed
    tests: a skipped integration test proves nothing.
    """

    def _models(self) -> set[str]:
        try:
            key = master_key()
        except AnswerError as exc:
            pytest.skip(f"no gateway credentials, so the boundary tests did not run: {exc}")
        request = urllib.request.Request(
            f"{proxy_url()}/v1/models", headers={"Authorization": f"Bearer {key}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            pytest.skip(
                f"no LiteLLM gateway at {proxy_url()}, so the boundary tests did not run "
                f"({exc}). Start it with `make services-up`."
            )
        return {entry["id"] for entry in payload["data"]}

    def test_the_answerer_is_served(self) -> None:
        assert ANSWERER in self._models()

    def test_the_judge_is_served(self) -> None:
        """CONTEXT.md:59 -- the judge must be a different model family than the answerer."""
        assert JUDGE in self._models()
        assert JUDGE.split("/")[0] != ANSWERER.split("/")[0]


class TestSpendingKey:
    """The budgeted virtual key, without touching the gateway.

    `gateway.ensure_budgeted_key` itself is exercised live by `fi-rag-eval
    answer`; what is pinned here is the property that makes the budget work at
    all -- that the key is the *same* key every run.
    """

    def test_the_key_is_stable_for_one_master_key(self) -> None:
        """A fresh key per run would reset the spend, and the budget would never trip."""
        assert gateway.spending_key_id("master") == gateway.spending_key_id("master")

    def test_a_different_master_key_derives_a_different_key(self) -> None:
        """Rotating the master key rotates this one, rather than orphaning a live budget."""
        assert gateway.spending_key_id("master") != gateway.spending_key_id("other")

    def test_the_key_is_not_the_master_key(self) -> None:
        """The whole point: the gateway does not enforce budgets on its master key."""
        assert gateway.spending_key_id("sk-master") != "sk-master"

    def test_the_key_is_recognisably_this_project(self) -> None:
        assert gateway.spending_key_id("master").startswith(f"sk-{gateway.ALIAS}-")

    def test_the_budget_mirrors_the_owners_provider_cap(self) -> None:
        """$25/month, set by the Owner at Groq on 27 Aug 2026 (D8 enforcer #3)."""
        assert gateway.MONTHLY_BUDGET_USD == 25.0
        assert gateway.BUDGET_DURATION == "30d"

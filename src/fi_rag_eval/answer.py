"""The answering layer's boundary: retrieved chunks in, a Conditional answer out.

Everything this project sends to a model goes through here, and through the
LiteLLM gateway `compose.yaml` runs (ADR-0009). The module owns three jobs that
the rest of the harness must not have to think about.

**A broken envelope is a hard error, never a skip.** `evaluate` has no skip path
because a metric averaged over a silently reduced N is the worst output this
harness could produce; the answer layer inherits that rule unchanged. If the
model returns something that is not the agreed JSON object, the run stops.

**A bad citation is data, not an error.** The distinction is load-bearing and
easy to get backwards. The *envelope* is the harness's contract with itself, so
a violation is a bug. What the model puts *inside* it -- a citation that points
at no chunk, a refusal of an answerable question, a flattened conditional -- is
the behaviour under measurement. Raising on a malformed citation would delete
exactly the failures `citation accuracy` exists to count.

**Tokens are counted against a ceiling.** The cost ceiling's first and most
important enforcer (SPEC-slice-5 D8) lives here rather than in a dashboard,
because a runaway -- a retry storm, an accidental loop -- outruns a monthly cap
long before a human reads a billing page.

Cost is **read back from the gateway**, never computed here. LiteLLM keeps the
provider price table; a second copy in this repository would be a price list
nobody updates, and a stale price list makes the ceiling silently wrong.
"""

from __future__ import annotations

import functools
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import litellm

from fi_rag_eval import db, gateway

ANSWERER = "qwen/qwen3.6-27b"
"""The system under test.

Chosen in tracer slice 1 by measurement, not by specification: `gpt-oss-20b` was
disqualified for inverting `15 §`'s composting exemption **with the required
chunk retrieved**, which would have made comprehension failures and retrieval
failures indistinguishable and prediction 5 untestable.
"""

JUDGE = "openai/gpt-oss-120b"
"""The judge. A different model **family** than the answerer, by CONTEXT.md:59.

A same-family judge shares the answerer's blind spots and rubber-stamps the
fabrications it exists to catch (ADR-0008).
"""

PROXY_URL_ENV = "LITELLM_PROXY_URL"
DEFAULT_PROXY_URL = "http://localhost:4010"
PROXY_KEY_ENV = "LITELLM_MASTER_KEY"

TOKEN_CEILING = 600_000
"""D8's figure, kept as the **floor** the ceiling can never fall below.

Deliberately counted in tokens rather than dollars: token counts are a property
of what the harness did, while dollars are a property of a price list that can
change under it. The dollar figure is recorded beside it, from the gateway, and
is the number reported.
"""

MEASURED_TOKENS_PER_CALL = 10_900
"""One answer with reasoning on, measured at the gateway in tracer slice 2.

    reasoning off   ~4,900 prompt + ~350 completion   = ~5,250 tokens, $0.0040
    reasoning on    ~4,900 prompt + ~6,000 completion = ~10,900 tokens, $0.0210

Reasoning is on because prediction 7 makes it a **correctness** knob rather than
a cost one: with it off, `qwen/qwen3.6-27b` reproduced the same inversion of
`17 §` that disqualified `gpt-oss-20b`. So the expensive row is the legitimate
one, and the ceiling has to be derived from it.
"""

CEILING_HEADROOM = 2
"""How far past a legitimate run the ceiling sits.

The ceiling exists to stop a runaway -- a retry storm, an accidental loop -- not
to second-guess a planned run, so it scales with the number of calls the run
actually intends to make rather than being a constant that has to be revised
every time the question set grows.
"""


def ceiling_for(calls: int) -> int:
    """The token ceiling for a run of `calls` completions.

    **This replaces a constant that was measured to be wrong, and the arithmetic
    is written down rather than the answer.** D8 set 600K as "roughly 2x a
    legitimate run", derived before tracer slice 1 established that both models
    are reasoning models whose hidden reasoning bills as output. At 64 questions
    with reasoning on, a legitimate run is ~700K tokens -- so the constant made a
    *correct* run trip its own enforcer, which is the one thing a ceiling must
    never do.

    Fitting a new constant to one run would have bought the same problem again at
    the next question count. The formula is `headroom x calls x measured tokens
    per call`, floored at D8's number so a one-question run keeps its ceiling, and
    every input is a figure this project measured and can re-measure.
    """
    if calls < 1:
        raise AnswerError(f"a run makes at least one call, not {calls}")
    return max(TOKEN_CEILING, CEILING_HEADROOM * calls * MEASURED_TOKENS_PER_CALL)


TIMEOUT_SECONDS = 120
RETRIES = 3
"""Retry-with-backoff is LiteLLM's (tenacity-backed), per D10.

The half this project writes is the other one: when the retries are exhausted the
question **fails the run** rather than being skipped.
"""


class AnswerError(RuntimeError):
    """The answer could not be obtained honestly, so it was not obtained at all."""


class ProxyError(AnswerError):
    """The LiteLLM gateway could not be reached, or refused the request."""


class MalformedAnswerError(AnswerError):
    """The model returned something that is not the agreed envelope."""


class BudgetExceededError(AnswerError):
    """The run passed its token ceiling and was stopped."""


JSON_RETRIES = 4
"""How many times a *stochastic* JSON-mode failure is retried before the run dies.

Separate from `RETRIES` because LiteLLM's backoff does not cover this one. Groq's
JSON mode validates the generation server-side and returns HTTP **400**
`json_validate_failed` with an empty `failed_generation` when the model emits
something that is not valid JSON. LiteLLM treats 400 as a client error and does
not retry it -- correctly, in general: a 400 usually means the request is wrong,
and retrying an unchanged wrong request is a waste.

Here the request is not wrong. `temperature=0` becomes `1e-8` at Groq (ADR-0008),
so generation is not deterministic, and the same question that failed can succeed
unchanged on the next attempt. Measured: `tapahtuman-jatehuoltosuunnitelma` killed
a 64-question run at the 29th answer and then succeeded twice in a row on the
identical request, at both an 8k and a 16k cap, using 2,557 reasoning tokens
either way -- so it was never the token cap that tracer slice 2 diagnosed for the
same error code.

**Retrying is not skipping.** The question is still answered and still scored, and
if the retries run out the run still fails rather than reporting 63 of 64. What
would be dishonest is hiding how often it happened, so the count is carried on the
run's budget and printed.

A failed generation is billed at zero tokens -- confirmed in the gateway's spend
ledger -- so the retries cost wall-clock and nothing else.
"""


def _is_stochastic_json_failure(exc: Exception) -> bool:
    """Groq's server-side JSON validation rejected the generation.

    Matched on the provider's own error code rather than on the exception class,
    because every 400 arrives here as the same `BadRequestError`. Fragile in the
    same way as the budget/rate-limit discrimination below, and confessed with it.
    """
    return "json_validate_failed" in str(exc)


SYSTEM_PROMPT = (
    "Olet Suomen kunnallisten jätehuoltomääräysten neuvoja. Vastaat VAIN annettujen "
    "pykäläotteiden perusteella. Jos otteet eivät riitä vastaukseen, älä arvaa: "
    "kieltäydy vastaamasta. Vastaa suomeksi ja tiiviisti.\n"
    "\n"
    "Jos velvoite on ehdollinen, kerro jokainen ehto erikseen — älä litistä "
    "ehdollista sääntöä yhdeksi luvuksi. Jos jokin ehto riippuu tiedosta jota "
    "otteissa ei ole, sano se ääneen äläkä valitse arvoa puolesta.\n"
    "\n"
    "Merkitse jokaisen väitteen perään sen lähteen tunnus hakasulkeissa, "
    "esimerkiksi [lounais-suomi@2024-08-01#15].\n"
    "\n"
    "Palauta VAIN JSON-objekti, jossa on täsmälleen nämä kentät:\n"
    '  "refused"   (boolean) — true jos et vastaa, false jos vastaat\n'
    '  "answer"    (merkkijono) — vastaus suomeksi, tai kieltäytymisen perustelu\n'
    '  "citations" (lista merkkijonoja) — ne lähdetunnukset joihin vastaus nojaa\n'
)
"""The answerer's instructions, in the language the answers are read in.

The bracketed-address convention and the per-branch demand are carried unchanged
from tracer slice 1, where `qwen/qwen3.6-27b` reproduced all three of a
question's required branches with each one cited by address. The JSON envelope is
new: a Refusal must be a field the harness reads, never a string match on prose,
because string-matching a refusal fails silently and mis-scores the metric this
slice exists to produce.
"""


@dataclass(frozen=True, slots=True)
class Usage:
    """What one call cost, in the gateway's own accounting."""

    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    """Billed as output. Reported separately because it is invisible in the answer
    and was the reason tracer slice 1's first probe returned empty content."""
    total_tokens: int
    cost_usd: float


@dataclass(frozen=True, slots=True)
class Answer:
    """One model response to one question, parsed but **not** judged."""

    question_id: str
    model: str
    refused: bool
    text: str
    citations: tuple[str, ...]
    """As emitted, unvalidated. An address that resolves to no chunk is a
    measurement (citation accuracy), not a harness failure."""
    usage: Usage
    finish_reason: str


@dataclass(slots=True)
class TokenBudget:
    """The run's token ceiling, and what it has spent so far.

    Recorded **after** each call rather than predicted before one: the token cost
    of a response is not knowable until it exists, so the honest guarantee is
    "one call of overshoot, then nothing", not "never a token over". That is
    enough to stop a runaway, which is what the ceiling is for.
    """

    ceiling: int = TOKEN_CEILING
    tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    json_validation_retries: int = 0
    """How many calls the provider rejected with `json_validate_failed` and were retried.

    Carried here because this is the one object threaded through every call in a
    run. It is reported rather than swallowed: "the answerer failed to emit valid
    JSON on n of 64 questions" is a fact about the model under test, and a silent
    retry would delete it.
    """

    @classmethod
    def for_run(cls, calls: int) -> TokenBudget:
        """A budget sized for a run that intends to make `calls` completions."""
        return cls(ceiling=ceiling_for(calls))

    def record(self, usage: Usage) -> None:
        self.tokens += usage.total_tokens
        self.cost_usd += usage.cost_usd
        self.calls += 1
        if self.tokens > self.ceiling:
            raise BudgetExceededError(
                f"token ceiling exceeded: {self.tokens} tokens over {self.calls} calls "
                f"(ceiling {self.ceiling}, ${self.cost_usd:.4f} spent). The run was "
                "stopped rather than allowed to keep spending."
            )


def proxy_url() -> str:
    return os.environ.get(PROXY_URL_ENV, DEFAULT_PROXY_URL)


def master_key() -> str:
    """The gateway's admin credential. Used to administer it, never to spend."""
    key = os.environ.get(PROXY_KEY_ENV)
    if not key:
        raise ProxyError(
            f"{PROXY_KEY_ENV} is not set, so the gateway cannot be reached.\n"
            "Copy .env.example to .env and fill it in, then `make services-up`."
        )
    return key


@functools.cache
def spending_key() -> str:
    """The budgeted virtual key every completion is charged to.

    Not the master key, and the distinction is the difference between a real
    enforcer and a decorative one: the gateway does **not** apply budgets to its
    master key, which was measured by watching a $0.001 budget serve a request
    against $0.0749 of spend. See `gateway`.

    Cached because provisioning is one idempotent round-trip and a run makes
    dozens of calls.
    """
    try:
        return gateway.ensure_budgeted_key(proxy_url=proxy_url(), master_key=master_key())
    except gateway.GatewayError as exc:
        raise ProxyError(str(exc)) from exc


def reasoning_effort(model: str, *, enabled: bool) -> str:
    """The per-model spelling of "think about it first".

    The two models do not share a vocabulary here: `gpt-oss` accepts
    `low|medium|high`, and `qwen` returns HTTP 400 for anything but
    `none|default`. Measured in tracer slice 1, on the second call this project
    ever made. Normalising it is precisely the boundary's job.
    """
    if model.startswith("openai/"):
        return "medium" if enabled else "low"
    return "default" if enabled else "none"


def format_context(hits: Sequence[db.Hit], bodies: Mapping[str, str]) -> str:
    """The retrieved chunks, addressed the way the answer must cite them.

    Each excerpt is labelled with the address itself rather than a position or an
    invented `[1]`, so a citation the model emits is directly checkable against
    the corpus with no lookup table in between -- and so a hallucinated citation
    looks like a hallucinated citation rather than an off-by-one.
    """
    parts = []
    for hit in hits:
        body = bodies.get(hit.address)
        if body is None:
            raise AnswerError(
                f"chunk {hit.address} was retrieved but has no body in the corpus map; "
                "the answer would have been generated from a hole."
            )
        parts.append(f"[{hit.address}] {hit.citation}\n{body}")
    return "\n\n".join(parts)


def _envelope(raw: str, *, question_id: str, model: str) -> tuple[bool, str, tuple[str, ...]]:
    """Parse the agreed JSON object, or fail the run.

    Every raise here is a broken contract with the harness, never a judgement
    about answer quality.
    """
    text = raw.strip()
    if not text:
        raise MalformedAnswerError(
            f"{question_id}: {model} returned empty content. If the finish reason is "
            "`length`, the token cap was consumed by hidden reasoning before any "
            "answer was emitted."
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedAnswerError(
            f"{question_id}: {model} did not return JSON ({exc}): {text[:200]!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise MalformedAnswerError(
            f"{question_id}: {model} returned a {type(payload).__name__}, not a JSON object"
        )
    missing = {"refused", "answer", "citations"} - set(payload)
    if missing:
        raise MalformedAnswerError(
            f"{question_id}: {model} omitted {sorted(missing)} from the envelope; "
            f"got keys {sorted(payload)}"
        )
    refused = payload["refused"]
    if not isinstance(refused, bool):
        raise MalformedAnswerError(
            f"{question_id}: `refused` must be a boolean, got {refused!r}. A Refusal is "
            "read from this field and never string-matched out of the prose."
        )
    answer = payload["answer"]
    if not isinstance(answer, str):
        raise MalformedAnswerError(
            f"{question_id}: `answer` must be a string, got {type(answer).__name__}"
        )
    citations = payload["citations"]
    if not isinstance(citations, list) or not all(isinstance(c, str) for c in citations):
        raise MalformedAnswerError(
            f"{question_id}: `citations` must be a list of strings, got {citations!r}"
        )
    return refused, answer, tuple(citations)


def _usage(response: Any) -> Usage:
    """Token counts and the gateway's own cost figure.

    The cost is read from LiteLLM's `response_cost`, which is what the gateway
    charged against the budget -- so the number the harness reports and the
    number the enforcer acts on are the same number.
    """
    usage = response.usage
    details = getattr(usage, "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None) or 0
    hidden = getattr(response, "_hidden_params", None) or {}
    cost = hidden.get("response_cost")
    if cost is None:
        raise AnswerError(
            "the gateway returned no response_cost, so this run cannot report a measured "
            "cost. Refusing to substitute an estimate: the project does not publish a "
            "number it did not compute."
        )
    return Usage(
        prompt_tokens=int(usage.prompt_tokens),
        completion_tokens=int(usage.completion_tokens),
        reasoning_tokens=int(reasoning),
        total_tokens=int(usage.total_tokens),
        cost_usd=float(cost),
    )


def complete(
    *,
    model: str,
    messages: list[dict[str, str]],
    budget: TokenBudget,
    max_tokens: int = 8000,
    reasoning: bool = True,
    response_format: dict[str, str] | None = None,
) -> tuple[str, Usage, str]:
    """One call through the gateway. Returns `(content, usage, finish_reason)`.

    `max_tokens` defaults high because both models are reasoning models and the cap
    covers reasoning **and** answer together. Measured, not guessed: on a real
    five-chunk context one question needed 5,143 reasoning tokens before emitting
    any answer, and a 3,000-token cap failed as Groq `json_validate_failed` with an
    empty `failed_generation`.

    **`json_validate_failed` has two causes and tracer slice 2 only found one.**
    That slice attributed the error code to the token cap, which was right for the
    case it had. Tracer slice 3 hit the identical code with an ample cap, on a
    question that then succeeded twice on the unchanged request using 2,557
    reasoning tokens. The cap is one cause; **non-determinism is the other**, and
    `JSON_RETRIES` above exists for it. Read a `json_validate_failed` as "the model
    emitted invalid JSON", not as "the cap was too small".

    With reasoning off the model stops at ~350 completion tokens regardless, so the
    high default costs nothing there.
    """
    for attempt in range(1, JSON_RETRIES + 1):
        try:
            return _complete_once(
                model=model,
                messages=messages,
                budget=budget,
                max_tokens=max_tokens,
                reasoning=reasoning,
                response_format=response_format,
            )
        except MalformedAnswerError:
            raise
        except ProxyError as exc:
            if not _is_stochastic_json_failure(exc) or attempt == JSON_RETRIES:
                raise
            budget.json_validation_retries += 1
    raise AnswerError("unreachable: the retry loop always returns or raises")


def _complete_once(
    *,
    model: str,
    messages: list[dict[str, str]],
    budget: TokenBudget,
    max_tokens: int,
    reasoning: bool,
    response_format: dict[str, str] | None,
) -> tuple[str, Usage, str]:
    try:
        response = litellm.completion(
            model=f"litellm_proxy/{model}",
            messages=messages,
            api_base=proxy_url(),
            api_key=spending_key(),
            # Groq silently rewrites 0 to 1e-8, so this buys near-determinism
            # rather than bit-determinism. Recorded so nobody later reads a
            # changed answer as a changed pipeline.
            temperature=0,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort(model, enabled=reasoning),
            # Keeps the model's chain of thought out of `content`. Qwen through
            # Groq otherwise emits a `<think>` block inline, which would land in
            # the answer text the judge scores.
            reasoning_format="hidden",
            response_format=response_format,
            timeout=TIMEOUT_SECONDS,
            num_retries=RETRIES,
        )
    except litellm.exceptions.RateLimitError as exc:
        # A spent budget and a rate limit are the same HTTP 429 at this boundary,
        # separated only by the gateway's message. The distinction matters: a rate
        # limit is worth retrying and an exhausted budget never is, so retrying it
        # would burn the run's wall-clock discovering the same refusal. String
        # matching is fragile and is confessed as such in REVIEW-DEBT.md.
        if "budget has been exceeded" in str(exc).lower():
            raise BudgetExceededError(
                f"the gateway refused {model}: the project's key is over its "
                f"${gateway.MONTHLY_BUDGET_USD} budget ({exc}). This is the cost "
                "ceiling's second enforcer, and it is not retried."
            ) from exc
        raise ProxyError(
            f"the gateway at {proxy_url()} rate-limited {model} past {RETRIES} retries: "
            f"{exc}\nThe run is stopped rather than continued over a reduced question set."
        ) from exc
    except litellm.exceptions.BudgetExceededError as exc:
        raise BudgetExceededError(
            f"the gateway refused {model}: its own budget is spent ({exc}). This is the "
            "cost ceiling's second enforcer firing at the gateway rather than in our "
            "code, which is what it is there for."
        ) from exc
    except Exception as exc:
        # Deliberately broad. LiteLLM raises `openai`'s exception hierarchy, whose
        # common ancestor this project does not import (`litellm.exceptions.OpenAIError`
        # is a different class and covers none of them), and an exception type nobody
        # anticipated must not become a skipped question. The type name is carried into
        # the message so a plain programming error here still reads as one instead of
        # being reported as a gateway fault.
        raise ProxyError(
            f"the gateway at {proxy_url()} could not serve {model} after {RETRIES} "
            f"retries -- {type(exc).__name__}: {exc}\nThe run is stopped rather than "
            "continued over a reduced question set."
        ) from exc
    usage = _usage(response)
    budget.record(usage)
    choice = response.choices[0]
    return (choice.message.content or ""), usage, str(choice.finish_reason)


def answer_question(
    *,
    question_id: str,
    question: str,
    hits: Sequence[db.Hit],
    bodies: Mapping[str, str],
    budget: TokenBudget,
    model: str = ANSWERER,
    reasoning: bool = True,
) -> Answer:
    """Answer one question from one cell's retrieved chunks, or fail the run."""
    context = format_context(hits, bodies)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"PYKÄLÄOTTEET:\n\n{context}\n\nKYSYMYS: {question}"},
    ]
    content, usage, finish_reason = complete(
        model=model,
        messages=messages,
        budget=budget,
        reasoning=reasoning,
        response_format={"type": "json_object"},
    )
    refused, text, citations = _envelope(content, question_id=question_id, model=model)
    return Answer(
        question_id=question_id,
        model=model,
        refused=refused,
        text=text,
        citations=citations,
        usage=usage,
        finish_reason=finish_reason,
    )

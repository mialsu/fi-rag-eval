"""The judge's boundary: one answer in, every unit verdict out.

ADR-0010 settled the shape and this module is that shape. One call per answer
returns a verdict for each of the question's required branches and each of its
forbidden claims -- 199 units in 50 calls over the full golden set, counted, not
estimated.

Four properties this module exists to hold.

**The judge never enumerates the units.** They are handed to it, numbered, from
the hand-written golden entry. `CONTEXT.md:43` chose hand enumeration so the
groundedness denominator is explicit rather than inferred; a judge that decided
for itself what the claims were would move the denominator every run and make a
hand label incomparable to it.

**A verdict the judge cannot quote is not a verdict.** Every `stated` branch and
every `asserted` forbidden claim must come with the exact substring of the answer
that carries it, and that substring is checked against the answer text here. This
is the only validation the layer has before judge-human agreement exists, it
costs nothing, and it catches the judge's most likely failure -- agreeing that a
claim is present because it *should* be.

**A broken envelope is a hard error, never a skip**, exactly as in `answer.py`.
An incoherent *verdict* inside a well-formed envelope is different: it is
normalised and **counted**, on the same logic that counts `json_validate_failed`
rather than swallowing it. How often the judge contradicts itself is a fact about
the judge under validation.

**Nothing here decides what may be published.** D11's rule -- groundedness never
appears without judge-human agreement beside it -- lives where the table is
rendered. This module produces numbers; `report.py` refuses them a headline.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fi_rag_eval import db
from fi_rag_eval.answer import (
    CEILING_HEADROOM,
    JUDGE,
    TOKEN_CEILING,
    AnswerError,
    MalformedAnswerError,
    TokenBudget,
    Usage,
    complete,
)
from fi_rag_eval.metrics import BranchVerdict, ForbiddenVerdict, JudgedAnswer, MetricsError

MEASURED_JUDGE_TOKENS_PER_CALL = 11_000
"""Placeholder until tracer slice 4 measures it, and deliberately not a prediction.

Prediction 6 put the answer phase within 2x of $0.067 and it came in at 11x. So
this figure exists only to size a ceiling before the first call, is set equal to
the *answerer's* measured per-call cost as the nearest available anchor, and is
replaced by measurement in the same commit that produces one.
"""


class JudgementError(AnswerError):
    """The judge's verdict could not be read honestly, so it was not read at all."""


class MalformedJudgementError(MalformedAnswerError):
    """The judge returned something that is not the agreed envelope."""


SYSTEM_PROMPT = (
    "You are validating a Finnish waste-regulation assistant's answer against the exact "
    "excerpts that assistant was shown. You are not answering the question, and you are "
    "not improving the answer. You make narrow yes/no calls about a fixed, numbered list.\n"
    "\n"
    "You will be given:\n"
    "  EXCERPTS  — the regulation chunks the assistant was shown, each labelled with its "
    "address\n"
    "  QUESTION  — the resident's question\n"
    "  ANSWER    — what the assistant replied, verbatim\n"
    "  BRANCHES  — a numbered list of claims a correct answer MUST state\n"
    "  FORBIDDEN — a numbered list of claims a correct answer must NOT make\n"
    "\n"
    "For each BRANCH decide:\n"
    "  stated    — does the ANSWER assert this claim? A paraphrase counts; different "
    "wording for the same rule counts. A claim the ANSWER only gestures at, or states "
    "with its condition removed, is NOT stated.\n"
    "  supported — is the claim, as the ANSWER states it, carried by the text of an "
    "excerpt the ANSWER cites for it? If the ANSWER states it with no citation, or cites "
    "an address that is not in EXCERPTS, supported is false. If the claim is not stated, "
    "supported is false.\n"
    "  quote     — the exact substring of the ANSWER that states the claim, copied "
    'character for character from the ANSWER. Required when stated is true, "" '
    "otherwise. If you cannot find words in the ANSWER to copy, the claim is NOT stated.\n"
    "\n"
    "For each FORBIDDEN item decide:\n"
    "  asserted  — does the ANSWER make this claim?\n"
    "  quote     — the exact substring of the ANSWER that makes it, copied character for "
    'character. Required when asserted is true, "" otherwise.\n'
    "\n"
    "The rules that decide the hard cases:\n"
    "  - Judge ONLY against EXCERPTS. A claim that is true of Finnish waste law but "
    "absent from the excerpts you were given is NOT supported.\n"
    "  - An ANSWER that declines to answer states NOTHING. Every branch is stated: "
    "false.\n"
    '  - "The excerpts do not say X" is not a claim that X. Naming what the excerpts '
    "DO cover is not an over-claim.\n"
    "  - A conditional rule stated as one unconditional value is NOT the branch; it is "
    "usually a forbidden claim.\n"
    "  - Ignore style, length, tone and politeness. They are not what you measure.\n"
    "\n"
    "Return ONLY a JSON object with exactly these fields:\n"
    '  "branches"  — a list with one object per BRANCH, in order: '
    '{"index": int, "stated": bool, "supported": bool, "quote": string}\n'
    '  "forbidden" — a list with one object per FORBIDDEN item, in order: '
    '{"index": int, "asserted": bool, "quote": string}\n'
)
"""The judge's instructions.

**English instructions, Finnish content** (ADR-0010 decision 6). The corpus, the
question, the answer and the claims reach the judge verbatim in Finnish; only the
task vocabulary is English, because that is harness vocabulary rather than
user-facing copy and `gpt-oss-120b` follows English instructions more reliably.
Recorded as a re-measurable knob: if agreement lands low in tracer slice 5, this
is the first thing to try changing.

The `quote` requirement is the load-bearing part. Without it a judge can agree
that a branch is present because it *ought* to be, and nothing catches it until a
human labels 199 units. With it, the claim is checkable by string search.
"""

WEAK_SYSTEM_PROMPT = (
    "You are reviewing a Finnish waste-regulation assistant's answer. The assistant is "
    "generally reliable and its answers are usually correct and well-cited.\n"
    "\n"
    "For each BRANCH, say whether the answer covers the topic (stated) and whether it "
    "looks properly cited (supported). For each FORBIDDEN item, say whether the answer "
    "obviously and egregiously makes that claim (asserted). Give the assistant the "
    "benefit of the doubt: if a claim is roughly in the right area, count it as stated "
    "and supported.\n"
    "\n"
    "Return ONLY a JSON object with exactly these fields:\n"
    '  "branches"  — a list with one object per BRANCH, in order: '
    '{"index": int, "stated": bool, "supported": bool, "quote": string}\n'
    '  "forbidden" — a list with one object per FORBIDDEN item, in order: '
    '{"index": int, "asserted": bool, "quote": string}\n'
)
"""A deliberately credulous judge, kept so the control can be watched failing.

`PRINCIPLES` #2: a gate you have not seen fail is not a gate. AC10 requires the
8/8 known-bad control to be **seen red**, and the honest way to do that is to
weaken the judge -- which means the weakened judge has to exist somewhere. Kept in
the code rather than applied as a throwaway edit for the same reason
`--token-ceiling` exists: a red proof that can be re-run is worth more than one
that was performed once and reverted.

Every weakening here is a real-world failure mode, not a strawman: it asserts the
system under test is reliable, replaces "states this claim" with "covers the
topic", replaces "carried by the cited excerpt" with "looks properly cited",
requires over-claims to be "obvious and egregious", and instructs charity. This is
what a judge prompt written without adversarial intent actually looks like.
"""


def _words(text: str) -> list[str]:
    """The quote's word tokens, for the splice-against-invention split.

    Deliberately crude -- lowercase, split on non-word characters. It is answering
    "does the answer contain this word at all", not "is this the same word form",
    so Finnish morphology is irrelevant here: a judge copying a claim does not
    inflect it differently, and one that does is quoting badly either way.
    """
    return [word for word in re.split(r"[^0-9A-Za-z\u00c0-\u024f#@.-]+", text.lower()) if word]


def quote_words_present(quote: str, answer_text: str) -> float:
    """Share of the quote's words that appear in the answer at all.

    Multiset containment, not set containment: a judge repeating a word the answer
    uses once has still gone beyond the text. `1.0` for an empty quote, which is
    harmless because an empty quote is only ever paired with a negative verdict.
    """
    words = _words(quote)
    if not words:
        return 1.0
    available: dict[str, int] = {}
    for word in _words(answer_text):
        available[word] = available.get(word, 0) + 1
    present = 0
    for word in words:
        if available.get(word, 0) > 0:
            available[word] -= 1
            present += 1
    return present / len(words)


def _normalise(text: str) -> str:
    """Collapse whitespace so a quote check is not defeated by line wrapping.

    The answers arrive with newlines and bullet markers; a judge copying a claim
    out of one routinely re-flows it. Whitespace is the only thing normalised --
    case and punctuation are left alone, because a "quote" that matches only after
    those are discarded is a paraphrase, and the whole point of the field is that
    it is not one.
    """
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True, slots=True)
class Judgement:
    """One judged answer, with what the call cost and how the judge misbehaved."""

    judged: JudgedAnswer
    usage: Usage
    model: str
    incoherent_verdicts: int
    """Verdicts saying `supported` without `stated`, normalised and counted.

    Not raised on: one incoherent unit must not destroy a 50-call run. Not
    swallowed either -- it is a fact about the judge, and the judge is the thing
    being validated here.
    """


def format_excerpts(
    hits: Sequence[str], bodies: Mapping[str, str], citations: Mapping[str, str]
) -> str:
    """The chunks the answerer saw, addressed the way it was told to cite them.

    Byte-identical in shape to `answer.format_context` on purpose: the judge is
    asked whether a citation is carried by an excerpt, so it must see the excerpt
    the answerer saw, labelled the way the answerer was told to label it. A
    different rendering here would make some disagreements artifacts of the
    harness.
    """
    parts = []
    for address in hits:
        body = bodies.get(address)
        if body is None:
            raise JudgementError(
                f"chunk {address} was in the answer's context but has no body in the "
                "corpus map; the judge would be scoring a citation against a hole. "
                "Re-ingest, or judge a run recorded against this corpus."
            )
        label = citations.get(address, address)
        parts.append(f"[{address}] {label}\n{body}")
    return "\n\n".join(parts)


def format_task(
    *,
    question: str,
    answer_text: str,
    refused: bool,
    cited: Sequence[str],
    branches: Sequence[str],
    forbidden: Sequence[str],
) -> str:
    """The numbered units, and the answer they are judged against."""
    if not branches:
        raise JudgementError(
            "a question with no required branches has nothing to judge. Groundedness' "
            "denominator would be empty and branch coverage undefined."
        )
    lines = [
        f"QUESTION: {question}",
        "",
        f"ANSWER (refused={'true' if refused else 'false'}, "
        f"citations={', '.join(cited) if cited else 'none'}):",
        answer_text,
        "",
        "BRANCHES — claims a correct answer MUST state:",
    ]
    lines += [f"  {index}. {claim}" for index, claim in enumerate(branches, start=1)]
    if forbidden:
        lines.append("")
        lines.append("FORBIDDEN — claims a correct answer must NOT make:")
        lines += [f"  {index}. {claim}" for index, claim in enumerate(forbidden, start=1)]
    else:
        # Said out loud rather than left as an empty section: an absent heading
        # would read to the judge as a truncated prompt and invite it to invent
        # items to fill.
        lines.append("")
        lines.append("FORBIDDEN — none for this question. Return an empty list.")
    return "\n".join(lines)


def _units(payload: Any, key: str, *, question_id: str, expected: int) -> list[Mapping[str, Any]]:
    raw = payload.get(key)
    if not isinstance(raw, list):
        raise MalformedJudgementError(
            f"{question_id}: `{key}` must be a list, got {type(raw).__name__}"
        )
    if not all(isinstance(item, Mapping) for item in raw):
        raise MalformedJudgementError(f"{question_id}: every entry in `{key}` must be an object")
    if len(raw) != expected:
        raise MalformedJudgementError(
            f"{question_id}: {len(raw)} verdicts under `{key}` for {expected} units. Every "
            "unit is judged or the metric is computed over a silently reduced N."
        )
    return list(raw)


def _flag(item: Mapping[str, Any], field: str, *, question_id: str, key: str) -> bool:
    value = item.get(field)
    if not isinstance(value, bool):
        raise MalformedJudgementError(
            f"{question_id}: `{key}[].{field}` must be a boolean, got {value!r}. A verdict "
            "is read from this field and never inferred from prose."
        )
    return value


def _quote(item: Mapping[str, Any], *, question_id: str, key: str) -> str:
    value = item.get("quote", "")
    if not isinstance(value, str):
        raise MalformedJudgementError(
            f"{question_id}: `{key}[].quote` must be a string, got {type(value).__name__}"
        )
    return value


def _verdict[V: (BranchVerdict, ForbiddenVerdict)](
    kind: type[V], *, question_id: str, **fields: Any
) -> V:
    """Build one verdict, translating a metrics-layer refusal into a judge one.

    The verdict dataclasses enforce their own coherence -- `supported` without
    `stated`, `asserted` with no quote -- and they raise `MetricsError`. That is
    the right place for the rule and the wrong exception to let out of here: the
    CLI handles the answer-layer family, and a `MetricsError` escaping this module
    would reach the user as a traceback about a metric while the actual fault is a
    judge that returned something incoherent.
    """
    try:
        return kind(**fields)
    except MetricsError as exc:
        raise MalformedJudgementError(f"{question_id}: {exc}") from exc


def parse_verdicts(
    raw: str,
    *,
    question_id: str,
    refused: bool,
    answer_text: str,
    branch_count: int,
    forbidden_count: int,
) -> tuple[JudgedAnswer, int]:
    """Parse the judge's envelope into verdicts. Returns `(judged, incoherent)`.

    Every raise here is a broken contract with the harness. What the judge *says*
    -- a wrong verdict, a fabricated quote -- is the behaviour under measurement
    and is recorded, never raised on.
    """
    text = raw.strip()
    if not text:
        raise MalformedJudgementError(
            f"{question_id}: the judge returned empty content. If the finish reason is "
            "`length`, hidden reasoning consumed the cap before any verdict was emitted."
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedJudgementError(
            f"{question_id}: the judge did not return JSON ({exc}): {text[:200]!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise MalformedJudgementError(
            f"{question_id}: the judge returned a {type(payload).__name__}, not an object"
        )
    missing = {"branches", "forbidden"} - set(payload)
    if missing:
        raise MalformedJudgementError(
            f"{question_id}: the judge omitted {sorted(missing)}; got keys {sorted(payload)}"
        )

    haystack = _normalise(answer_text)
    incoherent = 0
    branch_items = _units(payload, "branches", question_id=question_id, expected=branch_count)
    branches: list[BranchVerdict] = []
    for index, item in enumerate(branch_items, start=1):
        stated = _flag(item, "stated", question_id=question_id, key="branches")
        supported = _flag(item, "supported", question_id=question_id, key="branches")
        if supported and not stated:
            # Normalised rather than raised: `stated` is the field with the
            # quote behind it, so it is the one that can be checked, and one
            # incoherent unit must not cost a 50-call run.
            incoherent += 1
            supported = False
        quote = _quote(item, question_id=question_id, key="branches")
        if refused:
            # The answerer's own envelope says it declined. A judge that reads a
            # branch out of a refusal is judging text that is not there, and the
            # `refused` field is the more trustworthy of the two: it is a boolean
            # the answerer emitted about itself, not an inference.
            if stated:
                incoherent += 1
            stated = False
            supported = False
            quote = ""
        branches.append(
            _verdict(
                BranchVerdict,
                question_id=question_id,
                index=index,
                stated=stated,
                supported=supported,
                quote=quote,
                quote_found=bool(quote) and _normalise(quote) in haystack,
                quote_words_present=quote_words_present(quote, answer_text),
            )
        )

    forbidden_items = _units(
        payload, "forbidden", question_id=question_id, expected=forbidden_count
    )
    forbidden: list[ForbiddenVerdict] = []
    for index, item in enumerate(forbidden_items, start=1):
        asserted = _flag(item, "asserted", question_id=question_id, key="forbidden")
        quote = _quote(item, question_id=question_id, key="forbidden")
        if refused and asserted:
            # A refusal asserts nothing, by the same argument as above.
            incoherent += 1
            asserted = False
            quote = ""
        forbidden.append(
            _verdict(
                ForbiddenVerdict,
                question_id=question_id,
                index=index,
                asserted=asserted,
                quote=quote,
                quote_found=bool(quote) and _normalise(quote) in haystack,
                quote_words_present=quote_words_present(quote, answer_text),
            )
        )

    try:
        judged = JudgedAnswer(
            question_id=question_id,
            refused=refused,
            required_branches=branch_count,
            branches=tuple(branches),
            forbidden=tuple(forbidden),
        )
    except MetricsError as exc:
        # A verdict that survived parsing but cannot be counted. Raised as a
        # malformed judgement rather than leaking the metrics layer's exception,
        # so the CLI's error handling covers it.
        raise MalformedJudgementError(f"{question_id}: {exc}") from exc
    return judged, incoherent


def judge_answer(
    *,
    question_id: str,
    question: str,
    answer_text: str,
    refused: bool,
    cited: Sequence[str],
    retrieved: Sequence[str],
    bodies: Mapping[str, str],
    labels: Mapping[str, str],
    branches: Sequence[str],
    forbidden: Sequence[str],
    budget: TokenBudget,
    model: str = JUDGE,
    weak: bool = False,
) -> Judgement:
    """Judge one answer's every unit in one call, or fail the run."""
    excerpts = format_excerpts(retrieved, bodies, labels)
    task = format_task(
        question=question,
        answer_text=answer_text,
        refused=refused,
        cited=cited,
        branches=branches,
        forbidden=forbidden,
    )
    messages = [
        {"role": "system", "content": WEAK_SYSTEM_PROMPT if weak else SYSTEM_PROMPT},
        {"role": "user", "content": f"EXCERPTS:\n\n{excerpts}\n\n{task}"},
    ]
    content, usage, _finish = complete(
        model=model,
        messages=messages,
        budget=budget,
        reasoning=True,
        response_format={"type": "json_object"},
    )
    judged, incoherent = parse_verdicts(
        content,
        question_id=question_id,
        refused=refused,
        answer_text=answer_text,
        branch_count=len(branches),
        forbidden_count=len(forbidden),
    )
    return Judgement(
        judged=judged,
        usage=usage,
        model=model,
        incoherent_verdicts=incoherent,
    )


def chunk_labels(hits: Sequence[db.Hit]) -> dict[str, str]:
    """The human-readable citation line per address, as `format_context` renders it."""
    return {hit.address: hit.citation for hit in hits}


def judge_ceiling_for(calls: int) -> int:
    """The token ceiling for a judge run of `calls` completions.

    Separate from `answer.ceiling_for` rather than shared, even though the two
    figures are currently within 1% of each other. They are measurements of
    different models doing different work, and a ceiling derived from the wrong
    one would be a number that looks measured and is not -- which is exactly how
    D8's 600K constant came to make a legitimate run trip its own enforcer.
    """
    if calls < 1:
        raise JudgementError(f"a judge run makes at least one call, not {calls}")
    return max(TOKEN_CEILING, CEILING_HEADROOM * calls * MEASURED_JUDGE_TOKENS_PER_CALL)

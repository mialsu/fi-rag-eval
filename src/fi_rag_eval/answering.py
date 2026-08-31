"""The answer phase: both populations, one pass, no skip path.

`evaluate` is the offline half -- 50 answerable questions x 12 cells, arithmetic
only, deterministic, gated at zero tolerance. This is the networked half. It runs
on the **published cell only** (`lemma-reasm/0`): 12 cells x 64 questions would be
768 model calls per run, unaffordable and diagnostically pointless, and
`evaluate.PUBLISHED` exists so that decision is made once.

Three rules the module exists to hold.

**The two populations are used together and never merged.** Refusal precision's
denominator is every refusal the system emitted, which spans all 63 questions, so
both populations have to be in scope at once. They stay separate types the whole
way through -- `Question` and `RefusalQuestion` in, `AnswerOutcome` and
`RefusalOutcome` out -- so the arithmetic that must not pool them cannot.

**A question that cannot be scored fails the run.** There is no try/except around
a question here and there must not be one: retries live inside the boundary, and
when they are exhausted the run stops. A table over a silently reduced N is the
one output this project says destroys it.

**Every refusal question's claim is checked against the corpus first**, before a
single token is spent. A refusal question asserts that a topic is not answerable
where it was asked; if that has stopped being true, the run would score correct
answers as missed refusals and read as the answerer regressing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import psycopg

from fi_rag_eval import db
from fi_rag_eval.analyse import Morphology
from fi_rag_eval.answer import ANSWERER, Answer, AnswerError, TokenBudget, answer_question
from fi_rag_eval.evaluate import (
    DEFAULT_K,
    PUBLISHED,
    Cell,
    assert_refusal_absences,
    evaluate,
    question_stopwords,
    retrieve_refusals,
)
from fi_rag_eval.golden import GoldenSet, RefusalKind, RefusalQuestion
from fi_rag_eval.manifest import Manifest
from fi_rag_eval.metrics import (
    AnswerOutcome,
    RefusalMetrics,
    RefusalOutcome,
    refusal_metrics,
)
from fi_rag_eval.metrics import RefusalKind as MetricsRefusalKind


@dataclass(frozen=True, slots=True)
class ScoredAnswer:
    """One model response, kept with enough of its question to be read later.

    The answer texts are carried whole because tracer 5 freezes them for the
    hand-labelled agreement sample, and a sample re-generated from a later model
    is not the sample that was labelled.
    """

    question_id: str
    question: str
    municipality: str
    authority_key: str
    retrieved: tuple[str, ...]
    answer: Answer


@dataclass(frozen=True, slots=True)
class AnswerRun:
    """One answer phase over both populations."""

    cell: Cell
    k: int
    model: str
    reasoning: bool
    answerable: tuple[ScoredAnswer, ...]
    refusals: tuple[ScoredAnswer, ...]
    refusal_kinds: dict[str, RefusalKind]
    metrics: RefusalMetrics
    tokens: int
    cost_usd: float
    ceiling: int
    json_validation_retries: int
    """Times the provider rejected a generation as invalid JSON and it was retried.

    Reported rather than swallowed: it is a fact about the model under test.
    """

    @property
    def calls(self) -> int:
        return len(self.answerable) + len(self.refusals)


def _kind(kind: RefusalKind) -> MetricsRefusalKind:
    """Translate the golden set's vocabulary into the metrics module's.

    `metrics` deliberately imports nothing from `golden`, so the two enums are
    separate. Crossing the boundary explicitly here -- rather than passing strings
    -- is what makes a drift between them a type error instead of a silent
    mis-bucketing of the population whose split carries prediction 3.
    """
    return MetricsRefusalKind(kind.value)


def run(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    manifest: Manifest,
    golden: GoldenSet,
    budget: TokenBudget,
    k: int = DEFAULT_K,
    cell: Cell = PUBLISHED,
    morphology: Morphology | None = None,
    model: str = ANSWERER,
    reasoning: bool = True,
    progress: Callable[[str], None] | None = None,
) -> AnswerRun:
    """Answer every question in both populations, then score refusal behaviour.

    `progress` is called once per answered question. A run of this size takes the
    better part of an hour, and the first version printed nothing until it was
    over -- which meant a failure on question 29 arrived as a stack trace with no
    way to tell which question it was. An expensive long-running command that
    reports nothing is unusable for the thing it exists to do.
    """
    report = progress or (lambda line: None)
    if not golden.refusals:
        # An AnswerError rather than a bare ValueError: the CLI handles this family
        # and prints it, where an unhandled type would reach the user as a traceback.
        raise AnswerError(
            "the answer phase needs the refusal population: without it there is no "
            "refusal recall, and refusal precision would be computed over the answerable "
            "questions alone, where every refusal is by definition wrong."
        )
    if cell.analyser.lemmatising and morphology is None:
        morphology = Morphology.open()

    # Before a token is spent: the refusal questions still say what they claim.
    assert_refusal_absences(conn, manifest=manifest, refusals=golden.refusals)

    stopwords = question_stopwords(conn, golden, morphology) if morphology else frozenset()
    scored = evaluate(
        conn,
        manifest=manifest,
        golden=golden,
        k=k,
        cell=cell,
        morphology=morphology,
        stopwords=stopwords,
    )
    retrieved_refusals = retrieve_refusals(
        conn,
        manifest=manifest,
        refusals=golden.refusals,
        k=k,
        cell=cell,
        morphology=morphology,
        stopwords=stopwords,
    )
    bodies = dict(db.chunk_bodies(conn))

    total = len(scored.runs) + len(retrieved_refusals)
    answerable: list[ScoredAnswer] = []
    for index, question_run in enumerate(scored.runs, start=1):
        answerable.append(
            ScoredAnswer(
                question_id=question_run.question.id,
                question=question_run.question.question,
                municipality=question_run.question.municipality,
                authority_key=question_run.authority_key,
                retrieved=tuple(hit.address for hit in question_run.hits),
                answer=answer_question(
                    question_id=question_run.question.id,
                    question=question_run.question.question,
                    hits=question_run.hits,
                    bodies=bodies,
                    budget=budget,
                    model=model,
                    reasoning=reasoning,
                ),
            )
        )
        report(
            f"  [{index}/{total}] answerable  {question_run.question.id}  "
            f"refused={answerable[-1].answer.refused}  ${budget.cost_usd:.4f}"
        )

    refused: list[ScoredAnswer] = []
    for offset, refusal_run in enumerate(retrieved_refusals, start=1):
        refusal: RefusalQuestion = refusal_run.refusal
        refused.append(
            ScoredAnswer(
                question_id=refusal.id,
                question=refusal.question,
                municipality=refusal.municipality,
                authority_key=refusal_run.authority_key,
                retrieved=tuple(hit.address for hit in refusal_run.hits),
                answer=answer_question(
                    question_id=refusal.id,
                    question=refusal.question,
                    hits=refusal_run.hits,
                    bodies=bodies,
                    budget=budget,
                    model=model,
                    reasoning=reasoning,
                ),
            )
        )
        report(
            f"  [{len(answerable) + offset}/{total}] {refusal.kind.value:<20} "
            f"{refusal.id}  refused={refused[-1].answer.refused}  ${budget.cost_usd:.4f}"
        )

    kinds = {r.refusal.id: r.refusal.kind for r in retrieved_refusals}
    metrics = refusal_metrics(
        refusals=[
            RefusalOutcome(
                question_id=one.question_id,
                kind=_kind(kinds[one.question_id]),
                refused=one.answer.refused,
                citations=one.answer.citations,
                retrieved=one.retrieved,
            )
            for one in refused
        ],
        answerable=[
            AnswerOutcome(question_id=one.question_id, refused=one.answer.refused)
            for one in answerable
        ],
    )
    return AnswerRun(
        cell=cell,
        k=k,
        model=model,
        reasoning=reasoning,
        answerable=tuple(answerable),
        refusals=tuple(refused),
        refusal_kinds=kinds,
        metrics=metrics,
        tokens=budget.tokens,
        cost_usd=budget.cost_usd,
        ceiling=budget.ceiling,
        json_validation_retries=budget.json_validation_retries,
    )

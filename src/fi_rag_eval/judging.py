"""The judge phase: a frozen answer file in, unit verdicts and their arithmetic out.

`answering.py` is the phase that spends money generating answers. This is the
phase that scores them, and ADR-0010 keeps the two in separate commands for three
reasons, of which the first is the one that matters: **a judge prompt is developed
by iteration, and iteration needs an input that cannot move underneath it.**
`temperature=0` becomes `1e-8` at Groq, so re-answering between two judge prompts
means a changed verdict cannot be attributed to the prompt.

Two guards live here rather than in a document.

**The recorded run must still describe today's corpus.** Every answerable
question's retrieved set is re-retrieved from the published cell and compared. A
run judged against a corpus that has since been re-ingested would score citations
against excerpts the answerer never saw, and the resulting groundedness would look
like an answerer problem. Same discipline as the golden set's `absent_lexeme`: the
claim cannot rot silently.

**The judged population is the 50 answerable questions and nothing else.** The 13
refusal questions carry no `required_branches`, so groundedness has no denominator
over them and branch coverage no numerator; their behaviour is already measured by
refusal precision and recall, with no judge and no floor. Enforced by only ever
reading the `answerable` half of the file.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import yaml

from fi_rag_eval import db
from fi_rag_eval.analyse import Morphology
from fi_rag_eval.answer import ANSWERER, JUDGE, AnswerError, TokenBudget
from fi_rag_eval.citations import AddressValidity, CitationCheck, address_validity, check
from fi_rag_eval.evaluate import DEFAULT_K, PUBLISHED, Cell, QuestionRun, evaluate
from fi_rag_eval.golden import GoldenSet, Question
from fi_rag_eval.judge import Judgement, judge_answer
from fi_rag_eval.manifest import Manifest
from fi_rag_eval.metrics import (
    AnswerOutcome,
    JudgedMetrics,
    RefusalMetrics,
    RefusalOutcome,
    judged_metrics,
    refusal_metrics,
)
from fi_rag_eval.metrics import RefusalKind as MetricsRefusalKind

DEFAULT_CONTROL = Path("corpus/control/known-bad.yaml")
SUPPORTED_CONTROL_VERSION = 1

SHAPES = ("wrong-citation", "fabricated-claim", "flattened-conditional", "cross-authority")
"""The four failure shapes the control must cover, per ADR-0010 decision 5."""


class JudgingError(AnswerError):
    """The judge phase was asked for something it cannot produce honestly."""


# ---------------------------------------------------------------------------
# Reading a recorded answer run
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecordedAnswer:
    """One answer read back from a run file, exactly as it was written."""

    question_id: str
    population: str
    question: str
    municipality: str
    authority_key: str
    retrieved: tuple[str, ...]
    refused: bool
    text: str
    citations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecordedRun:
    """A run of the answer phase, frozen on disk.

    `commit` is carried and printed rather than checked, because the run this
    project has is stamped `4b75dfd-dirty` -- produced from an uncommitted tree.
    Refusing to judge it would be the wrong trade: the answers are real, they are
    the ones already published, and the honest response is to say so on every
    table rather than to pretend the provenance is better than it is.
    """

    source: Path
    cell: str
    k: int
    model: str
    reasoning: bool
    commit: str
    tokens: int
    cost_usd: float
    answers: tuple[RecordedAnswer, ...]

    @property
    def answerable(self) -> tuple[RecordedAnswer, ...]:
        return tuple(a for a in self.answers if a.population == "answerable")

    @property
    def refusals(self) -> tuple[RecordedAnswer, ...]:
        return tuple(a for a in self.answers if a.population == "refusal")

    @property
    def dirty_provenance(self) -> bool:
        return self.commit.endswith("-dirty") or not self.commit


def _field(payload: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in payload:
        raise JudgingError(f"{where}: the run file has no {key!r}")
    return payload[key]


def load_run(path: Path) -> RecordedRun:
    """Read a run written by `answer --all --out`, or fail.

    Deliberately strict about the answer *text*: an empty one would be judged as
    an answer that states nothing, which is indistinguishable from a refusal and
    would quietly move branch coverage.
    """
    if not path.is_file():
        raise JudgingError(
            f"no answer run at {path}. Produce one with "
            "`fi-rag-eval answer --all --out eval/runs/<name>.json` -- which spends "
            "real money and takes about an hour -- or point at an existing file."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise JudgingError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise JudgingError(f"{path}: expected a JSON object at the top level")
    where = str(path)
    raw_answers = _field(payload, "answers", where)
    if not isinstance(raw_answers, list) or not raw_answers:
        raise JudgingError(f"{where}: `answers` must be a non-empty list")

    answers: list[RecordedAnswer] = []
    for index, one in enumerate(raw_answers):
        if not isinstance(one, Mapping):
            raise JudgingError(f"{where}: answer {index} is not an object")
        question_id = str(_field(one, "question_id", where))
        population = str(_field(one, "population", where))
        if population not in ("answerable", "refusal"):
            raise JudgingError(
                f"{where}: {question_id} has population {population!r}. The two "
                "populations are never pooled and an unknown third would be."
            )
        text = str(_field(one, "text", where))
        if not text.strip():
            raise JudgingError(
                f"{where}: {question_id} has an empty answer text. An empty answer "
                "judges as stating nothing, which is not distinguishable from a "
                "refusal and would move branch coverage silently."
            )
        answers.append(
            RecordedAnswer(
                question_id=question_id,
                population=population,
                question=str(_field(one, "question", where)),
                municipality=str(_field(one, "municipality", where)),
                authority_key=str(_field(one, "authority_key", where)),
                retrieved=tuple(str(a) for a in _field(one, "retrieved", where)),
                refused=bool(_field(one, "refused", where)),
                text=text,
                citations=tuple(str(c) for c in one.get("citations") or ()),
            )
        )
    ids = [a.question_id for a in answers]
    if len(set(ids)) != len(ids):
        raise JudgingError(
            f"{where}: duplicate question ids "
            f"{sorted({i for i in ids if ids.count(i) > 1})}. An id is how a verdict is "
            "attached to a question; a collision attaches it to two."
        )
    return RecordedRun(
        source=path,
        cell=str(payload.get("cell", "")),
        k=int(payload.get("k", 0)),
        model=str(payload.get("model", ANSWERER)),
        reasoning=bool(payload.get("reasoning", True)),
        # `answered_at_commit` is the frozen sample's spelling and `commit` is a
        # live run's. Reading only the latter left every provenance line on the
        # committed sample reading "(none recorded)" and every label file writing
        # an empty `sample_answered_at_commit` -- the exact field ADR-0011
        # decision 5 moved the provenance INTO, on the grounds that a filename
        # cannot be checked. It reported dirty provenance correctly by accident,
        # because an empty commit is also dirty.
        commit=str(payload.get("commit") or payload.get("answered_at_commit") or ""),
        tokens=int(payload.get("tokens", 0)),
        cost_usd=float(payload.get("cost_usd", 0.0)),
        answers=tuple(answers),
    )


def assert_run_matches_corpus(
    run: RecordedRun,
    *,
    retrieval: Sequence[QuestionRun],
    cell: Cell,
) -> None:
    """The recorded contexts must be the ones this corpus produces today.

    Compared as **sets** rather than in rank order: from the judge's position the
    context is a set of excerpts, and a `ts_rank` tie reordering two chunks would
    otherwise fail a run for a difference that changes no verdict. A genuinely
    different context -- a re-ingest, a different cell, a changed analyser -- still
    fails, which is the whole purpose.
    """
    if run.cell and run.cell != cell.name:
        raise JudgingError(
            f"{run.source} was answered in cell {run.cell!r} and would be judged against "
            f"{cell.name!r}. The judged metrics would then describe a cell the retrieval "
            "headline does not."
        )
    recorded = {a.question_id: set(a.retrieved) for a in run.answerable}
    today = {r.question.id: {hit.address for hit in r.hits} for r in retrieval}
    missing = sorted(set(today) - set(recorded))
    if missing:
        raise JudgingError(
            f"{run.source} has no answer for {missing}. Every golden question is judged "
            "or the metric is computed over a reduced N."
        )
    extra = sorted(set(recorded) - set(today))
    if extra:
        raise JudgingError(
            f"{run.source} answers {extra}, which are not in today's golden set. Judging "
            "it would score answers to questions the set no longer asks."
        )
    drifted = sorted(qid for qid, addresses in recorded.items() if addresses != today[qid])
    if drifted:
        first = drifted[0]
        raise JudgingError(
            f"the corpus has moved under {run.source}: {len(drifted)} question(s) now "
            f"retrieve a different context, e.g. {first} recorded "
            f"{sorted(recorded[first])} and today retrieves {sorted(today[first])}.\n"
            "Judging it would score citations against excerpts the answerer never saw, "
            "and the difference would read as an answerer failure. Re-run the answer "
            "phase against this corpus, or judge a run recorded against it."
        )


# ---------------------------------------------------------------------------
# Judging a run
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JudgeRun:
    """One judge pass over one frozen answer run.

    Carries `agreement` nowhere on purpose. Judge-human agreement is tracer slice
    5's and does not exist yet, and D11 makes it the thing that decides whether
    groundedness may be published. A field holding `None` here would invite a
    table to print a blank beside a number; its absence makes the report state
    plainly that the judge is unvalidated.
    """

    source: Path
    source_commit: str
    dirty_provenance: bool
    cell: Cell
    k: int
    answerer: str
    judge_model: str
    weak: bool
    judged: tuple[Judgement, ...]
    metrics: JudgedMetrics
    checks: tuple[CitationCheck, ...]
    validity: AddressValidity
    tokens: int
    cost_usd: float
    ceiling: int
    json_validation_retries: int
    available: int
    """How many answerable answers the run file held."""

    @property
    def partial(self) -> bool:
        """True when fewer answers were judged than the file holds.

        Carried so the table can refuse to be read as a result. A judged metric
        over a reduced N is the defect this project says destroys it, and `--limit`
        exists only to buy one measured call before a batch -- never to produce a
        cheaper number.
        """
        return len(self.judged) < self.available

    @property
    def calls(self) -> int:
        return len(self.judged)

    @property
    def incoherent_verdicts(self) -> int:
        return sum(one.incoherent_verdicts for one in self.judged)


def judge_run(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    manifest: Manifest,
    golden: GoldenSet,
    run: RecordedRun,
    budget: TokenBudget,
    cell: Cell = PUBLISHED,
    morphology: Morphology | None = None,
    model: str = JUDGE,
    weak: bool = False,
    limit: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> JudgeRun:
    """Judge every answerable answer in a recorded run. No skip path.

    There is no try/except around a question here and there must not be one. The
    retries live inside the boundary; when they are exhausted the run stops. A
    judged table over a silently reduced N is the same defect as a retrieval table
    over one.
    """
    report = progress or (lambda line: None)
    if cell.analyser.lemmatising and morphology is None:
        morphology = Morphology.open()

    # Retrieval only -- offline, deterministic, no spend. Its purpose here is the
    # drift check and the chunk labels, not the metrics. `k` comes from the run
    # rather than from a default: retrieving a different depth than the answerer
    # was given would fail the drift check for a reason nobody chose.
    retrieval = evaluate(
        conn,
        manifest=manifest,
        golden=golden,
        k=run.k or DEFAULT_K,
        cell=cell,
        morphology=morphology,
    )
    assert_run_matches_corpus(run, retrieval=retrieval.runs, cell=cell)

    questions: dict[str, Question] = {q.id: q for q in golden.questions}
    contexts: dict[str, QuestionRun] = {r.question.id: r for r in retrieval.runs}
    bodies = dict(db.chunk_bodies(conn))

    available = list(run.answerable)
    if limit is not None and limit < 1:
        raise JudgingError(f"a limited run judges at least one answer, not {limit}")
    # A limit truncates deliberately and visibly. It is not a skip path: every
    # answer it does judge is judged, and `JudgeRun.partial` makes the table say
    # the run is not a result.
    recorded = available if limit is None else available[:limit]
    total = len(recorded)
    judged: list[Judgement] = []
    checks: list[CitationCheck] = []
    for index, answer in enumerate(recorded, start=1):
        question = questions[answer.question_id]
        context = contexts[answer.question_id]
        labels = {hit.address: hit.citation for hit in context.hits}
        # The retrieved set is taken from TODAY's retrieval, not from the file:
        # `assert_run_matches_corpus` has already proved they are the same set, and
        # taking it from the live side means the excerpts and their labels come
        # from one place.
        retrieved = tuple(hit.address for hit in context.hits)
        checks.append(
            check(
                question_id=answer.question_id,
                citations=answer.citations,
                retrieved=retrieved,
                authority=context.authority_key,
            )
        )
        judgement = judge_answer(
            question_id=answer.question_id,
            question=answer.question,
            answer_text=answer.text,
            refused=answer.refused,
            cited=answer.citations,
            retrieved=retrieved,
            bodies=bodies,
            labels=labels,
            branches=[branch.claim for branch in question.required_branches],
            forbidden=list(question.forbidden),
            budget=budget,
            model=model,
            weak=weak,
        )
        judged.append(judgement)
        one = judgement.judged
        report(
            f"  [{index}/{total}] {answer.question_id:<44} "
            f"stated {one.stated}/{one.required_branches}  "
            f"supported {one.supported}  over-claims {one.over_claims}  "
            f"${budget.cost_usd:.4f}"
        )

    if len(judged) != total:  # pragma: no cover - the loop cannot skip
        raise JudgingError(f"judged {len(judged)} of {total} answers")
    return JudgeRun(
        source=run.source,
        source_commit=run.commit,
        dirty_provenance=run.dirty_provenance,
        cell=cell,
        k=retrieval.k,
        answerer=run.model,
        judge_model=model,
        weak=weak,
        judged=tuple(judged),
        metrics=judged_metrics([one.judged for one in judged]),
        checks=tuple(checks),
        validity=address_validity(checks),
        tokens=budget.tokens,
        cost_usd=budget.cost_usd,
        ceiling=budget.ceiling,
        json_validation_retries=budget.json_validation_retries,
        available=len(available),
    )


# ---------------------------------------------------------------------------
# The known-bad control
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ControlExpectation:
    """One verdict the judge must return for a control case to count as caught."""

    unit: str
    index: int
    field: str
    expect: bool

    def render(self) -> str:
        return f"{self.unit} {self.index} {self.field}={str(self.expect).lower()}"


@dataclass(frozen=True, slots=True)
class ControlCase:
    """One hand-authored bad answer, and what the judge must say about it."""

    id: str
    question_id: str
    shape: str
    answer: str
    citations: tuple[str, ...]
    must_catch: tuple[ControlExpectation, ...]
    why: str


def _expectation(raw: Mapping[str, Any], where: str) -> ControlExpectation:
    unit = str(raw.get("unit", ""))
    if unit not in ("branch", "forbidden"):
        raise JudgingError(f"{where}: unit must be 'branch' or 'forbidden', got {unit!r}")
    field = str(raw.get("field", ""))
    allowed = ("stated", "supported") if unit == "branch" else ("asserted",)
    if field not in allowed:
        raise JudgingError(f"{where}: a {unit} verdict has fields {allowed}, got {field!r}")
    index = raw.get("index")
    if not isinstance(index, int) or index < 1:
        raise JudgingError(f"{where}: index must be a positive integer, got {index!r}")
    expect = raw.get("expect")
    if not isinstance(expect, bool):
        raise JudgingError(f"{where}: expect must be a boolean, got {expect!r}")
    return ControlExpectation(unit=unit, index=index, field=field, expect=expect)


def load_control(path: Path, golden: GoldenSet) -> tuple[ControlCase, ...]:
    """Load the control, and check it against the golden set it points at.

    The checks are the reason this is a loader rather than a literal in the code.
    A control case that names a branch index the golden entry does not have would
    fail forever, look like a broken judge, and take an afternoon to find.
    """
    if not path.is_file():
        raise JudgingError(f"no known-bad control at {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise JudgingError(f"{path}: expected a mapping at the top level")
    if document.get("version") != SUPPORTED_CONTROL_VERSION:
        raise JudgingError(
            f"{path}: control version {document.get('version')!r}, "
            f"expected {SUPPORTED_CONTROL_VERSION}"
        )
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise JudgingError(f"{path}: `cases` must be a non-empty list")

    questions = {q.id: q for q in golden.questions}
    cases: list[ControlCase] = []
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, Mapping):
            raise JudgingError(f"{path}: case {index} is not a mapping")
        case_id = str(raw.get("id", ""))
        where = f"{path}: {case_id or f'case {index}'}"
        if not case_id:
            raise JudgingError(f"{where}: every case needs an id")
        question_id = str(raw.get("question_id", ""))
        question = questions.get(question_id)
        if question is None:
            raise JudgingError(
                f"{where}: question_id {question_id!r} is not in the golden set. A control "
                "case is judged against a real question's real retrieved context."
            )
        shape = str(raw.get("shape", ""))
        if shape not in SHAPES:
            raise JudgingError(f"{where}: shape must be one of {SHAPES}, got {shape!r}")
        answer = str(raw.get("answer", "")).strip()
        if not answer:
            raise JudgingError(f"{where}: a control case is an authored answer; this one is empty")
        raw_expectations = raw.get("must_catch")
        if not isinstance(raw_expectations, list) or not raw_expectations:
            raise JudgingError(
                f"{where}: must_catch is required and non-empty. A case with nothing to "
                "check would pass any judge, including one that returns nothing."
            )
        expectations = tuple(
            _expectation(one, where) for one in raw_expectations if isinstance(one, Mapping)
        )
        if len(expectations) != len(raw_expectations):
            raise JudgingError(f"{where}: every must_catch entry must be a mapping")
        for expectation in expectations:
            limit = (
                len(question.required_branches)
                if expectation.unit == "branch"
                else len(question.forbidden)
            )
            if expectation.index > limit:
                raise JudgingError(
                    f"{where}: {expectation.render()} but {question_id} has {limit} "
                    f"{expectation.unit} item(s). The case would fail forever and read as "
                    "a broken judge."
                )
        cases.append(
            ControlCase(
                id=case_id,
                question_id=question_id,
                shape=shape,
                answer=answer,
                citations=tuple(str(c) for c in raw.get("citations") or ()),
                must_catch=expectations,
                why=str(raw.get("why", "")).strip(),
            )
        )

    ids = [case.id for case in cases]
    if len(set(ids)) != len(ids):
        raise JudgingError(
            f"{path}: duplicate case ids {sorted({i for i in ids if ids.count(i) > 1})}"
        )
    covered = {(case.shape, questions[case.question_id].authority) for case in cases}
    authorities = {questions[case.question_id].authority for case in cases}
    expected = {(shape, authority) for shape in SHAPES for authority in authorities}
    uncovered = sorted(expected - covered)
    if len(authorities) < 2 or uncovered:
        raise JudgingError(
            f"{path}: the control must cover every failure shape on every authority it "
            f"touches, and at least two authorities. Missing: {uncovered or 'a second authority'}. "
            "A judge that reads one authority's prose well and another's badly shows as a "
            "healthy aggregate."
        )
    return tuple(cases)


@dataclass(frozen=True, slots=True)
class ControlOutcome:
    """What the judge said about one control case, and whether that caught it."""

    case: ControlCase
    judgement: Judgement
    failures: tuple[str, ...]

    @property
    def caught(self) -> bool:
        return not self.failures


@dataclass(frozen=True, slots=True)
class ControlRun:
    """The control, run. `passed` is the 8/8 floor and nothing softer."""

    judge_model: str
    weak: bool
    outcomes: tuple[ControlOutcome, ...]
    tokens: int
    cost_usd: float
    json_validation_retries: int

    @property
    def caught(self) -> int:
        return sum(1 for one in self.outcomes if one.caught)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def passed(self) -> bool:
        """A floor, not a proportion: every shape or none.

        A judge that catches three of four shapes cannot be trusted on the fourth,
        so a 7/8 is not a 0.875 -- it is a judge with a known blind spot and a
        number that would hide it.
        """
        return self.caught == self.total and self.total > 0


def _verdict_value(judged: Any, expectation: ControlExpectation) -> bool:
    units = judged.branches if expectation.unit == "branch" else judged.forbidden
    verdict = units[expectation.index - 1]
    value = getattr(verdict, expectation.field)
    if not isinstance(value, bool):  # pragma: no cover - the dataclasses are typed
        raise JudgingError(f"{expectation.render()} did not read a boolean")
    return value


def run_control(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    manifest: Manifest,
    golden: GoldenSet,
    cases: Sequence[ControlCase],
    budget: TokenBudget,
    cell: Cell = PUBLISHED,
    morphology: Morphology | None = None,
    model: str = JUDGE,
    weak: bool = False,
    progress: Callable[[str], None] | None = None,
) -> ControlRun:
    """Judge every control case against its question's real retrieved context.

    Offline retrieval, live judging. Nothing here reads a run file, so the control
    is reproducible from a clean clone -- which the judged metrics are not, and
    that asymmetry is the point: the claim "the judge works" should not depend on
    a gitignored artifact.
    """
    report = progress or (lambda line: None)
    if cell.analyser.lemmatising and morphology is None:
        morphology = Morphology.open()
    retrieval = evaluate(conn, manifest=manifest, golden=golden, cell=cell, morphology=morphology)
    contexts = {r.question.id: r for r in retrieval.runs}
    questions = {q.id: q for q in golden.questions}
    bodies = dict(db.chunk_bodies(conn))

    outcomes: list[ControlOutcome] = []
    for index, case in enumerate(cases, start=1):
        context = contexts[case.question_id]
        question = questions[case.question_id]
        judgement = judge_answer(
            question_id=case.id,
            question=question.question,
            answer_text=case.answer,
            refused=False,
            cited=case.citations,
            retrieved=tuple(hit.address for hit in context.hits),
            bodies=bodies,
            labels={hit.address: hit.citation for hit in context.hits},
            branches=[branch.claim for branch in question.required_branches],
            forbidden=list(question.forbidden),
            budget=budget,
            model=model,
            weak=weak,
        )
        failures = tuple(
            f"{expectation.render()} but the judge said "
            f"{str(_verdict_value(judgement.judged, expectation)).lower()}"
            for expectation in case.must_catch
            if _verdict_value(judgement.judged, expectation) is not expectation.expect
        )
        outcomes.append(ControlOutcome(case=case, judgement=judgement, failures=failures))
        report(
            f"  [{index}/{len(cases)}] {case.id:<32} {case.shape:<22} "
            f"{'CAUGHT' if not failures else 'MISSED'}  ${budget.cost_usd:.4f}"
        )

    return ControlRun(
        judge_model=model,
        weak=weak,
        outcomes=tuple(outcomes),
        tokens=budget.tokens,
        cost_usd=budget.cost_usd,
        json_validation_retries=budget.json_validation_retries,
    )


# ---------------------------------------------------------------------------
# Scoring the refusal population OFFLINE (31 Aug 2026)
#
# Until today the only path to refusal recall and precision ran through
# `answering.run`, which answers 63 questions through a live model: ~50 minutes,
# ~$0.76, and a different set of answers every time, because `temperature=0`
# becomes `1e-8` at Groq (ADR-0008). Re-measuring the population after a label
# changed therefore meant re-publishing every other number in it.
#
# The frozen sample already holds `refused` for every answer. Recomputing the
# arithmetic over it costs nothing and calls nothing, which makes the refusal
# numbers reproducible from a COMMITTED artifact for the first time.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OfflineRefusalRun:
    """Refusal metrics recomputed from a frozen run, with what it had to leave out."""

    metrics: RefusalMetrics
    source: Path
    source_commit: str
    model: str
    cell: str
    reasoning: bool
    scored: tuple[str, ...]
    not_in_golden: tuple[str, ...]
    """Refusal answers in the file for questions the golden set no longer asks.

    Never silently dropped. A frozen sample and a living golden set diverge the
    moment an entry moves -- `ooc-autonrenkaiden-vastaanotto` was removed on
    31 Aug 2026 and its answer is still in the sample, paid for and real. Reporting
    the exclusion is the difference between a measurement over 13 and a
    measurement over 14 that quietly calls itself 13.
    """

    @property
    def dirty_provenance(self) -> bool:
        return self.source_commit.endswith("-dirty") or not self.source_commit


def score_refusals_offline(run: RecordedRun, *, golden: GoldenSet) -> OfflineRefusalRun:
    """Recompute the refusal population's arithmetic from a recorded run.

    Refuses rather than reports when the run is missing a question the golden set
    asks: this harness must never publish a table over a silently reduced N, and a
    refusal population short one question is exactly that.

    Retrieval completeness is read from each answer's own recorded context, so the
    restricted precision reading describes the run being scored rather than what
    the retriever would return today.
    """
    asked = {r.id: r for r in golden.refusals}
    answered = {a.question_id: a for a in run.refusals}
    unanswered = sorted(set(asked) - set(answered))
    if unanswered:
        raise JudgingError(
            f"{run.source} has no answer for refusal questions {unanswered}. Refusal "
            "recall over the remainder would be a measurement of a smaller population "
            "wearing this one's name."
        )
    not_in_golden = tuple(sorted(set(answered) - set(asked)))

    required = {q.id: {str(a) for a in q.required_chunks} for q in golden.questions}
    answerable = []
    for one in run.answerable:
        if one.question_id not in required:
            raise JudgingError(
                f"{run.source}: {one.question_id} is answered as answerable but is not in "
                "the golden set. Precision's denominator would count a refusal of a "
                "question nobody is scoring."
            )
        answerable.append(
            AnswerOutcome(
                question_id=one.question_id,
                refused=one.refused,
                retrieval_complete=required[one.question_id] <= set(one.retrieved),
            )
        )

    metrics = refusal_metrics(
        refusals=[
            RefusalOutcome(
                question_id=one.question_id,
                # From the GOLDEN SET, never from the file: the kind is the label,
                # and a stale run file must not be able to assert one.
                kind=MetricsRefusalKind(asked[one.question_id].kind.value),
                refused=one.refused,
                citations=one.citations,
                retrieved=one.retrieved,
            )
            for one in run.refusals
            if one.question_id in asked
        ],
        answerable=answerable,
    )
    return OfflineRefusalRun(
        metrics=metrics,
        source=run.source,
        source_commit=run.commit,
        model=run.model,
        cell=run.cell,
        reasoning=run.reasoning,
        scored=tuple(sorted(asked)),
        not_in_golden=not_in_golden,
    )

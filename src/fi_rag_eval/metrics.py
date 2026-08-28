"""Retrieval metrics. Arithmetic only -- no model is involved anywhere here.

That is deliberate and it is why these are the numbers to trust most: when the
retrieval layer and a later judge disagree, these win the argument.

The headline is **complete-set recall@k** (ADR-0003): binary per question, did
the top k contain *every* chunk the answer depends on. Per-chunk recall and MRR
are diagnostics. Per-chunk recall awards partial credit for a retrieval that
produces a confidently wrong answer -- missing the composting exemption scores
0.67 and reads as "mostly fine" while the system tells a composting household to
buy a bin -- so it must never be the headline.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class MetricsError(ValueError):
    """A metric was asked for over a question set that cannot support it."""


class MissKind(StrEnum):
    """Why a required chunk was not retrieved. This is what decides slice 3."""

    ZERO_OVERLAP = "zero-overlap"
    """Shares no stemmed token with the query: unreachable. Morphology failure."""

    RANKED_OUT = "ranked-out"
    """Matched the query but ranked below k. Ranking failure -- IDF territory."""


@dataclass(frozen=True, slots=True)
class Miss:
    address: str
    kind: MissKind


@dataclass(frozen=True, slots=True)
class QuestionOutcome:
    """One question's retrieval result, with every miss classified."""

    question_id: str
    required: tuple[str, ...]
    retrieved: tuple[str, ...]
    """Top-k addresses, in rank order."""
    misses: tuple[Miss, ...]
    query_lexemes: tuple[str, ...] = ()
    """The question's stemmed content words, as the index would see them."""
    leaked_lexemes: tuple[str, ...] = ()
    """The subset of those already present in the question's own target chunks."""

    def __post_init__(self) -> None:
        if not self.required:
            raise MetricsError(
                f"{self.question_id}: no required chunks. A question with nothing to "
                "retrieve would score a vacuous 1.0 and inflate the headline; refusal "
                "cases arrive with the answering slice, where they can be scored."
            )
        if not set(self.leaked_lexemes) <= set(self.query_lexemes):
            raise MetricsError(
                f"{self.question_id}: leaked lexemes must be a subset of the query's; "
                f"{sorted(set(self.leaked_lexemes) - set(self.query_lexemes))} is not."
            )
        missed = {miss.address for miss in self.misses}
        found = set(self.required) & set(self.retrieved)
        if missed | found != set(self.required):
            raise MetricsError(
                f"{self.question_id}: every required chunk must be either retrieved or "
                f"classified as a miss; {sorted(set(self.required) - (missed | found))} "
                "is neither."
            )

    @property
    def found(self) -> tuple[str, ...]:
        return tuple(a for a in self.retrieved if a in set(self.required))

    @property
    def complete(self) -> bool:
        return set(self.required) <= set(self.retrieved)

    @property
    def lexical_leakage(self) -> float | None:
        """Share of this question's stemmed words that its target chunks contain.

        ``None`` when the question stemmed to nothing measurable, so a missing
        value is never silently averaged in as a zero.
        """
        if not self.query_lexemes:
            return None
        return len(self.leaked_lexemes) / len(self.query_lexemes)

    @property
    def reciprocal_rank(self) -> float:
        for position, address in enumerate(self.retrieved, start=1):
            if address in set(self.required):
                return 1.0 / position
        return 0.0


@dataclass(frozen=True, slots=True)
class Metrics:
    k: int
    questions: int
    required_chunks: int
    complete_set_recall: float
    per_chunk_recall: float
    mean_reciprocal_rank: float
    misses_zero_overlap: int
    misses_ranked_out: int
    lexical_leakage: float
    """How much of the golden set's own vocabulary is handed to it by its targets.

    Not a retrieval metric -- a metric *of the golden set*, reported beside the
    others because the headline is uninterpretable without it. High leakage means
    the questions were written from the source text, so the harness is easier
    than the task and cannot see the vocabulary gap it exists to measure. It is
    a diagnostic, not a target to drive to zero: a resident asking about
    bio-waste will say "biojäte" because that is what it is called. The reference
    point is the leakage of real questions harvested from the authority's own
    resident-facing pages.
    """
    leakage_lexemes: int
    """Denominator for the above: total stemmed question words considered."""

    @property
    def misses(self) -> int:
        return self.misses_zero_overlap + self.misses_ranked_out


def compute(outcomes: Sequence[QuestionOutcome], *, k: int) -> Metrics:
    """Compute the metric set over every outcome. Never over a subset.

    A metric averaged over a silently reduced N is this harness's worst possible
    output, so the caller is required to hand over one outcome per golden-set
    question; there is no skip path.
    """
    if not outcomes:
        raise MetricsError("refusing to compute metrics over zero questions")
    if k < 1:
        raise MetricsError(f"k must be at least 1, got {k}")
    intruders = sorted({type(o).__name__ for o in outcomes if not isinstance(o, QuestionOutcome)})
    if intruders:
        raise MetricsError(
            f"refusing to compute retrieval metrics over {intruders}. "
            "Only the answerable population has required chunks; a refusal question "
            "pooled in here would contribute a vacuous 1.0 to complete-set recall and "
            "move the published headline for a reason nobody chose. The two populations "
            "are separate types precisely so this cannot happen by accident."
        )

    ids = [outcome.question_id for outcome in outcomes]
    if len(set(ids)) != len(ids):
        raise MetricsError("outcomes contain duplicate question ids")

    required_total = sum(len(outcome.required) for outcome in outcomes)
    found_total = sum(len(outcome.found) for outcome in outcomes)
    complete = sum(1 for outcome in outcomes if outcome.complete)
    misses = [miss for outcome in outcomes for miss in outcome.misses]

    lexemes_total = sum(len(outcome.query_lexemes) for outcome in outcomes)
    leaked_total = sum(len(outcome.leaked_lexemes) for outcome in outcomes)

    return Metrics(
        k=k,
        questions=len(outcomes),
        required_chunks=required_total,
        complete_set_recall=complete / len(outcomes),
        per_chunk_recall=found_total / required_total,
        mean_reciprocal_rank=sum(o.reciprocal_rank for o in outcomes) / len(outcomes),
        misses_zero_overlap=sum(1 for m in misses if m.kind is MissKind.ZERO_OVERLAP),
        misses_ranked_out=sum(1 for m in misses if m.kind is MissKind.RANKED_OUT),
        lexical_leakage=leaked_total / lexemes_total if lexemes_total else 0.0,
        leakage_lexemes=lexemes_total,
    )


@dataclass(frozen=True, slots=True)
class Discordance:
    """How two cells disagree question by question, and whether that can register.

    Two cells are scored on the **same** questions, so comparing them is a
    *paired* test and the absolute-difference interval is the wrong instrument.
    Only the questions where the two disagree carry information: `a_only` passed
    in the first cell and failed in the second, `b_only` the reverse. Questions
    both cells pass, or both fail, tell you nothing about which is better.

    This is why slice 4 exists. At N=21 the best cell has three failures, so
    fixing *every remaining miss* yields three discordant questions and p=0.25 --
    there was no result the vector layer could have produced that would register
    at all. Reported per run so a reader is never left to assume a small delta
    means something.
    """

    a_only: int
    """Passed in cell A, failed in cell B."""

    b_only: int
    """Failed in cell A, passed in cell B."""

    @property
    def discordant(self) -> int:
        """``d``: how many questions the two cells disagree about."""
        return self.a_only + self.b_only

    @property
    def p_value(self) -> float:
        """Exact two-sided McNemar p: a binomial sign test over the discordant pairs.

        Under the null the two cells are equally good, so each discordant question
        is a fair coin. No normal approximation and no continuity correction --
        both are unusable at this N, which is the whole point of reporting it.

        With every discordant question flipping the same way this reduces to
        ``2 x 0.5^d``: d=5 gives 0.062 and d=6 gives 0.031, so **six questions
        must flip for a paired win at p<0.05.**
        """
        n = self.discordant
        if n == 0:
            return 1.0
        tail = sum(math.comb(n, i) for i in range(min(self.a_only, self.b_only) + 1))
        return min(1.0, float(2.0 * tail / 2**n))


def discordance(a: Sequence[QuestionOutcome], b: Sequence[QuestionOutcome]) -> Discordance:
    """Compare two cells' outcomes over the same questions, in the same order.

    Requires the same question ids in the same order: a paired test over two
    different populations is not a paired test, and silently zipping mismatched
    lists is how that mistake would be made.
    """
    if len(a) != len(b):
        raise MetricsError(
            f"cannot pair {len(a)} outcomes against {len(b)}: a paired test needs the "
            "same questions on both sides"
        )
    mismatched = [
        (left.question_id, right.question_id)
        for left, right in zip(a, b, strict=True)
        if left.question_id != right.question_id
    ]
    if mismatched:
        raise MetricsError(
            f"outcomes are not in the same question order: {mismatched[:3]}. Pairing "
            "two cells on position requires they scored the same set, in order."
        )
    return Discordance(
        a_only=sum(1 for x, y in zip(a, b, strict=True) if x.complete and not y.complete),
        b_only=sum(1 for x, y in zip(a, b, strict=True) if y.complete and not x.complete),
    )


# ---------------------------------------------------------------------------
# The refusal population (slice 5, tracer 3)
#
# Kept in this module because it is arithmetic and no model is involved, which is
# what makes it trustworthy for the same reason recall@k is. The judge scores
# groundedness; nothing here needs one.
# ---------------------------------------------------------------------------


class RefusalKind(StrEnum):
    """Mirrors `golden.RefusalKind` so metrics never import the golden set.

    Two enums for one concept would normally be the "two formats for one artifact"
    anti-pattern. This one is deliberate and narrow: `metrics` is the layer with
    no dependencies -- it knows about outcomes, not about YAML, manifests or
    corpora -- and the boundary test pins the two vocabularies equal, so they
    cannot drift silently.
    """

    OUT_OF_CORPUS = "out-of-corpus"
    OUT_OF_JURISDICTION = "out-of-jurisdiction"


@dataclass(frozen=True, slots=True)
class RefusalOutcome:
    """What the answerer did with one question that should have been refused."""

    question_id: str
    kind: RefusalKind
    refused: bool
    """Read from the envelope's `refused` field, never string-matched from prose."""

    citations: tuple[str, ...] = ()
    """A refusal that cites anything is a defect, counted rather than raised."""


@dataclass(frozen=True, slots=True)
class AnswerOutcome:
    """What the answerer did with one question that *was* answerable.

    Present in this module for exactly one reason: refusal **precision** cannot be
    computed without it. Its denominator is every refusal the system emitted, and
    the wrong ones are emitted over here.
    """

    question_id: str
    refused: bool


@dataclass(frozen=True, slots=True)
class Interval:
    """A Wilson score interval for a proportion, and the n it was computed at.

    Wilson rather than Wald because Wald is unusable at these counts: at 14
    questions it runs past 0 and 1, and at a perfect 14/14 it reports a width of
    zero, which would publish certainty this population cannot buy.

    **This corrects D5.** The spec quotes "±0.13" for refusal recall at R=14, which
    is one standard error (sqrt(0.25/14) = 0.134), not an interval. The 95%
    interval at 7/14 is roughly [0.25, 0.75]. This project has already been burned
    once by an interval that was the wrong statistic -- the ±0.18 slice 3 used --
    so the number is computed here and the spec is corrected rather than quoted.
    """

    point: float
    low: float
    high: float
    n: int

    def render(self) -> str:
        return f"{self.point:.3f} [{self.low:.2f}, {self.high:.2f}] n={self.n}"


def wilson(successes: int, n: int, *, z: float = 1.959963985) -> Interval:
    """The 95% Wilson score interval. Pure arithmetic, no approximation warnings."""
    if n <= 0:
        raise MetricsError("refusing to compute an interval over zero observations")
    if not 0 <= successes <= n:
        raise MetricsError(f"{successes} successes out of {n} is not a proportion")
    p = successes / n
    denominator = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denominator
    spread = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominator
    return Interval(
        point=p,
        low=max(0.0, centre - spread),
        high=min(1.0, centre + spread),
        n=n,
    )


@dataclass(frozen=True, slots=True)
class RefusalMetrics:
    """Refusal behaviour, computed with no judge and no network.

    Recall is reported **with its interval inline and never as a headline** (D5).
    Fourteen questions cannot support a published figure; what they can support is
    a floor and a direction, and the per-kind split is the part that carries the
    information -- out-of-corpus is the easy refusal and out-of-jurisdiction is the
    one the hard filter's debt turns on.
    """

    recall: Interval
    """Correct refusals over the refusal population. The diagnostic."""

    precision: Interval
    """Correct refusals over every refusal the system emitted, both populations.

    This is the metric that punishes cowardice at the population level: an
    answerer that refuses everything scores a perfect recall and a precision of
    14/64. Branch coverage does the same job question by question.
    """

    by_kind: tuple[tuple[RefusalKind, Interval], ...]
    """Prediction 3 lives here: out-of-corpus >= 7/8 against out-of-jurisdiction <= 4/6."""

    wrongly_refused: tuple[str, ...]
    """Answerable questions the system declined. Named, not just counted."""

    missed: tuple[str, ...]
    """Refusal questions the system answered anyway. Named, not just counted."""

    refusals_with_citations: tuple[str, ...]
    """Refusals that emitted a citation.

    A defect by decision, not by taste: a refusal asserts that the retrieved
    context does not support an answer, so a citation attached to it points at a
    chunk that supports nothing. Counted arithmetically because it can be, and
    reported because a judge would never see it.
    """


def refusal_metrics(
    *,
    refusals: Sequence[RefusalOutcome],
    answerable: Sequence[AnswerOutcome],
) -> RefusalMetrics:
    """Score the refusal population against the answerable one.

    Two separately-typed arguments rather than one pooled sequence, and that is
    the enforcement `metrics.py` was asked for: there is no argument you can pass
    that mixes them, because the wrong type in either slot is rejected here and by
    mypy before that. Precision genuinely needs both populations -- refusals are
    emitted over all 64 questions -- so the two are *used* together and never
    *merged*.
    """
    if not refusals:
        raise MetricsError("refusing to compute refusal metrics over zero refusal questions")
    if not answerable:
        raise MetricsError(
            "refusal precision needs the answerable population too: its denominator is "
            "every refusal the system emitted, and the wrong ones are emitted there. "
            "Computing it over the refusal population alone would report a vacuous 1.0."
        )
    misplaced = [o for o in refusals if not isinstance(o, RefusalOutcome)]
    misplaced += [o for o in answerable if not isinstance(o, AnswerOutcome)]  # type: ignore[misc]
    if misplaced:
        raise MetricsError(
            f"refusing to pool populations: {sorted({type(o).__name__ for o in misplaced})} "
            "was passed where the other population was expected. A question is either "
            "answerable or a refusal case, and one scored as the other silently changes "
            "both metrics."
        )
    ids = [o.question_id for o in refusals] + [o.question_id for o in answerable]
    if len(set(ids)) != len(ids):
        raise MetricsError(
            "the same question id appears in both populations, or twice in one. An id is "
            "how a verdict is attached to a question; a collision attaches it to two."
        )

    correct = [o for o in refusals if o.refused]
    wrongly_refused = tuple(o.question_id for o in answerable if o.refused)
    emitted = len(correct) + len(wrongly_refused)

    by_kind: list[tuple[RefusalKind, Interval]] = []
    for kind in RefusalKind:
        population = [o for o in refusals if o.kind is kind]
        if population:
            by_kind.append((kind, wilson(sum(1 for o in population if o.refused), len(population))))

    return RefusalMetrics(
        recall=wilson(len(correct), len(refusals)),
        # An answerer that never refuses has no precision rather than a zero: 0/0
        # is undefined, and reporting it as 0.0 would read as "every refusal it
        # emitted was wrong" when it emitted none.
        precision=wilson(len(correct), emitted) if emitted else Interval(0.0, 0.0, 1.0, 0),
        by_kind=tuple(by_kind),
        wrongly_refused=wrongly_refused,
        missed=tuple(o.question_id for o in refusals if not o.refused),
        refusals_with_citations=tuple(o.question_id for o in correct if o.citations),
    )

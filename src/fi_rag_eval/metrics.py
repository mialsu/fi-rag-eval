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

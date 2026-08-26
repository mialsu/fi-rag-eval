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

    def __post_init__(self) -> None:
        if not self.required:
            raise MetricsError(
                f"{self.question_id}: no required chunks. A question with nothing to "
                "retrieve would score a vacuous 1.0 and inflate the headline; refusal "
                "cases arrive with the answering slice, where they can be scored."
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

    return Metrics(
        k=k,
        questions=len(outcomes),
        required_chunks=required_total,
        complete_set_recall=complete / len(outcomes),
        per_chunk_recall=found_total / required_total,
        mean_reciprocal_rank=sum(o.reciprocal_rank for o in outcomes) / len(outcomes),
        misses_zero_overlap=sum(1 for m in misses if m.kind is MissKind.ZERO_OVERLAP),
        misses_ranked_out=sum(1 for m in misses if m.kind is MissKind.RANKED_OUT),
    )

import pytest

from fi_rag_eval.metrics import (
    MetricsError,
    Miss,
    MissKind,
    QuestionOutcome,
    compute,
)


def outcome(
    question_id: str,
    required: tuple[str, ...],
    retrieved: tuple[str, ...],
    misses: tuple[Miss, ...] = (),
) -> QuestionOutcome:
    return QuestionOutcome(
        question_id=question_id,
        required=required,
        retrieved=retrieved,
        misses=misses,
    )


def test_complete_set_recall_is_binary_per_question() -> None:
    """Partial retrieval scores zero on the headline, by design (ADR-0003)."""
    outcomes = [
        outcome("all", ("a", "b"), ("a", "b", "z")),
        outcome("partial", ("c", "d"), ("c", "z"), (Miss("d", MissKind.RANKED_OUT),)),
    ]
    metrics = compute(outcomes, k=5)
    assert metrics.complete_set_recall == 0.5
    assert metrics.per_chunk_recall == 0.75


def test_per_chunk_recall_is_micro_averaged_over_chunks_not_questions() -> None:
    outcomes = [
        outcome(
            "one-of-three",
            ("a", "b", "c"),
            ("a",),
            (Miss("b", MissKind.RANKED_OUT), Miss("c", MissKind.ZERO_OVERLAP)),
        ),
        outcome("one-of-one", ("d",), ("d",)),
    ]
    metrics = compute(outcomes, k=5)
    assert metrics.required_chunks == 4
    assert metrics.per_chunk_recall == 0.5
    assert metrics.complete_set_recall == 0.5


def test_mrr_uses_the_first_required_chunk() -> None:
    outcomes = [
        outcome("second", ("b",), ("a", "b")),
        outcome("nothing", ("z",), ("a", "b"), (Miss("z", MissKind.ZERO_OVERLAP),)),
    ]
    metrics = compute(outcomes, k=5)
    assert metrics.mean_reciprocal_rank == pytest.approx(0.25)


def test_miss_breakdown_separates_morphology_from_ranking() -> None:
    outcomes = [
        outcome(
            "q",
            ("a", "b", "c"),
            ("a",),
            (Miss("b", MissKind.ZERO_OVERLAP), Miss("c", MissKind.RANKED_OUT)),
        ),
    ]
    metrics = compute(outcomes, k=5)
    assert (metrics.misses_zero_overlap, metrics.misses_ranked_out) == (1, 1)
    assert metrics.misses == 2


def test_refuses_to_score_a_question_with_no_required_chunks() -> None:
    with pytest.raises(MetricsError, match=r"vacuous 1\.0"):
        outcome("empty", (), ("a",))


def test_refuses_an_outcome_whose_misses_do_not_account_for_every_required_chunk() -> None:
    with pytest.raises(MetricsError, match="is neither"):
        outcome("sloppy", ("a", "b"), ("a",))


def test_refuses_to_compute_over_zero_questions() -> None:
    with pytest.raises(MetricsError, match="zero questions"):
        compute([], k=5)


def test_refuses_duplicate_question_ids() -> None:
    with pytest.raises(MetricsError, match="duplicate question ids"):
        compute([outcome("q", ("a",), ("a",)), outcome("q", ("b",), ("b",))], k=5)

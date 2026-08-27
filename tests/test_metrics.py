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


def test_lexical_leakage_is_micro_averaged_over_stems() -> None:
    outcomes = [
        QuestionOutcome(
            question_id="leaky",
            required=("a",),
            retrieved=("a",),
            misses=(),
            query_lexemes=("biojät", "tyhjennettäv", "kesäaik", "kuink"),
            leaked_lexemes=("biojät", "tyhjennettäv", "kesäaik"),
        ),
        QuestionOutcome(
            question_id="clean",
            required=("b",),
            retrieved=("b",),
            misses=(),
            query_lexemes=("taloyhtiö", "asunto", "keskust", "kolm"),
            leaked_lexemes=(),
        ),
    ]
    metrics = compute(outcomes, k=5)
    assert metrics.leakage_lexemes == 8
    assert metrics.lexical_leakage == pytest.approx(3 / 8)
    assert outcomes[0].lexical_leakage == pytest.approx(0.75)
    assert outcomes[1].lexical_leakage == 0.0


def test_a_question_with_no_stems_reports_no_leakage_rather_than_zero() -> None:
    """A missing value must not be averaged in as if it were measured."""
    only = QuestionOutcome(question_id="q", required=("a",), retrieved=("a",), misses=())
    assert only.lexical_leakage is None
    assert compute([only], k=5).lexical_leakage == 0.0
    assert compute([only], k=5).leakage_lexemes == 0


def test_leaked_lexemes_must_come_from_the_query() -> None:
    with pytest.raises(MetricsError, match="subset of the query"):
        QuestionOutcome(
            question_id="q",
            required=("a",),
            retrieved=("a",),
            misses=(),
            query_lexemes=("biojät",),
            leaked_lexemes=("kompostor",),
        )

import pytest

from fi_rag_eval.metrics import (
    Discordance,
    MetricsError,
    Miss,
    MissKind,
    QuestionOutcome,
    compute,
    discordance,
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


# --------------------------------------------------------------------------- power
#
# Two cells are scored on the same questions, so comparing them is a PAIRED test.
# The absolute-difference interval slice 3's override reasoned with is the wrong
# instrument, and correcting it makes the argument for slice 4 stronger: at N=21
# fixing every remaining miss in the best cell yields d=3 and p=0.25, so there was
# no result the vector layer could have produced that would register at all.


def cell(*passes: bool) -> list[QuestionOutcome]:
    """One outcome per question, passing or failing exactly as given."""
    return [
        outcome(
            f"q{index}",
            required=("chunk",),
            retrieved=("chunk",) if ok else (),
            misses=() if ok else (Miss(address="chunk", kind=MissKind.RANKED_OUT),),
        )
        for index, ok in enumerate(passes)
    ]


@pytest.mark.parametrize(
    ("d", "expected"),
    [(0, 1.0), (1, 1.0), (2, 0.5), (3, 0.25), (4, 0.125), (5, 0.0625), (6, 0.03125)],
)
def test_all_discordant_one_way_is_two_times_a_half_to_the_d(d: int, expected: float) -> None:
    """The spec's table, reproduced: six must flip for p<0.05, at any N."""
    assert Discordance(a_only=d, b_only=0).p_value == pytest.approx(expected)
    assert Discordance(a_only=0, b_only=d).p_value == pytest.approx(expected)


def test_an_even_split_is_the_least_significant_result_possible() -> None:
    assert Discordance(a_only=3, b_only=3).p_value == 1.0
    assert Discordance(a_only=50, b_only=50).p_value == 1.0


def test_p_is_never_above_one_even_though_the_formula_doubles_a_tail() -> None:
    for a in range(6):
        for b in range(6):
            assert 0.0 <= Discordance(a_only=a, b_only=b).p_value <= 1.0


def test_questions_both_cells_agree_about_carry_no_information() -> None:
    """Adding questions both cells pass cannot change the verdict."""
    lean = discordance(cell(True, False, False), cell(False, True, True))
    padded = discordance(cell(True, False, False, True, True), cell(False, True, True, True, True))
    assert (lean.a_only, lean.b_only) == (1, 2)
    assert (padded.a_only, padded.b_only) == (1, 2)
    assert lean.p_value == padded.p_value


def test_discordance_counts_each_direction_separately() -> None:
    result = discordance(cell(True, True, False), cell(False, True, True))
    assert (result.a_only, result.b_only, result.discordant) == (1, 1, 2)


def test_pairing_two_different_populations_is_refused() -> None:
    with pytest.raises(MetricsError, match="same questions on both sides"):
        discordance(cell(True, True), cell(True))


def test_pairing_the_same_questions_in_a_different_order_is_refused() -> None:
    """Zipping on position is only valid if the positions agree."""
    a = cell(True, False)
    b = list(reversed(cell(True, False)))
    with pytest.raises(MetricsError, match="not in the same question order"):
        discordance(a, b)


def test_two_identical_cells_are_perfectly_indistinguishable() -> None:
    result = discordance(cell(True, False, True), cell(True, False, True))
    assert result.discordant == 0
    assert result.p_value == 1.0

"""The judge's contract, its arithmetic, and its control -- with no network.

Deliberately **no live model call anywhere in this file**, on the same terms as
`test_answer.py`: `make gate` runs before every commit, and a test that spends
money on every commit is a test that gets deleted the first time it is
inconvenient. The live exercise is `fi-rag-eval judge`, run by a human, and that
gap is confessed in REVIEW-DEBT.md rather than papered over here.

What is covered is everything that must never be wrong without a model:

* the envelope contract -- a broken one stops the run, a bad *verdict* does not;
* the quote check, which is the judge's only self-validation before agreement;
* the judged arithmetic, exhaustively, because it is pure;
* citation address validity (AC9), which needs no judge at all;
* D11's withholding rule, which is the reason the answer layer publishes nothing
  in this tracer;
* the control loader's guards, which stop a mis-authored case reading as a
  broken judge.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from fi_rag_eval import judging
from fi_rag_eval.addressing import ChunkAddress
from fi_rag_eval.answer import Usage
from fi_rag_eval.citations import address_validity, check
from fi_rag_eval.db import Hit
from fi_rag_eval.evaluate import PUBLISHED, QuestionRun
from fi_rag_eval.golden import Branch, GoldenSet, Phrasing, Question
from fi_rag_eval.judge import (
    SYSTEM_PROMPT,
    WEAK_SYSTEM_PROMPT,
    Judgement,
    JudgementError,
    MalformedJudgementError,
    format_task,
    judge_ceiling_for,
    parse_verdicts,
    quote_words_present,
)
from fi_rag_eval.judging import JudgingError, load_control, load_run
from fi_rag_eval.metrics import (
    BranchVerdict,
    ForbiddenVerdict,
    JudgedAnswer,
    MetricsError,
    Miss,
    MissKind,
    QuestionOutcome,
    UnitLabel,
    cluster_robust_interval,
    judged_metrics,
    unit_agreement,
    wilson,
)
from fi_rag_eval.report import AGREEMENT_FLOOR, format_judged

ANSWER = (
    "Biojätteelle on järjestettävä erillinen jäteastia yli 10 000 asukkaan taajamassa\n"
    "[lounais-suomi@2024-08-01#15]. Velvoite ei koske kompostoivaa kiinteistöä."
)


def _payload(
    *,
    branches: list[dict[str, object]] | None = None,
    forbidden: list[dict[str, object]] | None = None,
) -> str:
    return json.dumps(
        {
            "branches": branches
            if branches is not None
            else [{"index": 1, "stated": True, "supported": True, "quote": "erillinen jäteastia"}],
            "forbidden": forbidden if forbidden is not None else [],
        }
    )


def _parse(
    raw: str, *, refused: bool = False, branches: int = 1, forbidden: int = 0
) -> tuple[JudgedAnswer, int]:
    return parse_verdicts(
        raw,
        question_id="q1",
        refused=refused,
        answer_text=ANSWER,
        branch_count=branches,
        forbidden_count=forbidden,
    )


class TestTheEnvelopeIsAHardContract:
    """A broken envelope stops the run. This is `answer.py`'s rule, inherited."""

    @pytest.mark.parametrize(
        ("raw", "because"),
        [
            ("", "empty content"),
            ("not json at all", "not JSON"),
            ("[1, 2, 3]", "a list, not an object"),
            ('{"branches": []}', "omitted forbidden"),
            ('{"forbidden": []}', "omitted branches"),
            ('{"branches": {}, "forbidden": []}', "branches is not a list"),
            ('{"branches": [1], "forbidden": []}', "an entry is not an object"),
        ],
    )
    def test_a_malformed_payload_raises(self, raw: str, because: str) -> None:
        with pytest.raises(MalformedJudgementError):
            _parse(raw)

    def test_a_missing_verdict_is_never_a_skip(self) -> None:
        """Two units asked, one answered. The run stops rather than averaging over one."""
        with pytest.raises(MalformedJudgementError, match="1 verdicts under `branches` for 2"):
            _parse(_payload(), branches=2)

    def test_a_non_boolean_verdict_raises(self) -> None:
        with pytest.raises(MalformedJudgementError, match="must be a boolean"):
            _parse(
                _payload(
                    branches=[
                        {"index": 1, "stated": "yes", "supported": True, "quote": "erillinen"}
                    ]
                )
            )

    def test_a_non_string_quote_raises(self) -> None:
        with pytest.raises(MalformedJudgementError, match="must be a string"):
            _parse(
                _payload(branches=[{"index": 1, "stated": True, "supported": True, "quote": 42}])
            )

    def test_stated_with_no_quote_raises(self) -> None:
        """A judge that asserts a branch it cannot point at is not making a measurement."""
        with pytest.raises(MalformedJudgementError, match="stated with no quote"):
            _parse(
                _payload(branches=[{"index": 1, "stated": True, "supported": True, "quote": ""}])
            )


class TestTheQuoteCheck:
    """The judge's only self-validation before judge-human agreement exists."""

    def test_a_quote_that_is_in_the_answer_is_found(self) -> None:
        judged, _ = _parse(_payload())
        assert judged.branches[0].quote_found is True

    def test_a_quote_reflowed_across_a_line_break_is_still_found(self) -> None:
        """The answers wrap; a judge copying a claim out of one re-flows it.

        Whitespace is the only thing normalised. Case and punctuation are not: a
        "quote" that matches only after those are discarded is a paraphrase, and
        the field exists precisely because a paraphrase is not checkable.
        """
        judged, _ = _parse(
            _payload(
                branches=[
                    {
                        "index": 1,
                        "stated": True,
                        "supported": True,
                        "quote": "taajamassa [lounais-suomi@2024-08-01#15]",
                    }
                ]
            )
        )
        assert judged.branches[0].quote_found is True

    def test_a_fabricated_quote_is_recorded_not_raised(self) -> None:
        """The judge inventing words is a MEASUREMENT of the judge, not a crash."""
        judged, _ = _parse(
            _payload(
                branches=[
                    {
                        "index": 1,
                        "stated": True,
                        "supported": True,
                        "quote": "jokaisella kiinteistöllä on oltava biojäteastia",
                    }
                ]
            )
        )
        assert judged.branches[0].quote_found is False
        assert judged_metrics([judged]).judge_fabrications == ("q1",)

    def test_a_case_difference_is_not_a_quote(self) -> None:
        judged, _ = _parse(
            _payload(
                branches=[
                    {"index": 1, "stated": True, "supported": True, "quote": "ERILLINEN JÄTEASTIA"}
                ]
            )
        )
        assert judged.branches[0].quote_found is False


class TestIncoherentVerdictsAreNormalisedAndCounted:
    """Never swallowed, never fatal. The same discipline as `json_validate_failed`."""

    def test_supported_without_stated_is_normalised(self) -> None:
        judged, incoherent = _parse(
            _payload(branches=[{"index": 1, "stated": False, "supported": True, "quote": ""}])
        )
        assert incoherent == 1
        assert judged.branches[0].supported is False

    def test_a_branch_read_out_of_a_refusal_is_normalised(self) -> None:
        """`refused` is the answerer's own boolean about itself, so it wins."""
        judged, incoherent = _parse(
            _payload(
                branches=[
                    {"index": 1, "stated": True, "supported": True, "quote": "erillinen jäteastia"}
                ]
            ),
            refused=True,
        )
        assert incoherent == 1
        assert judged.branches[0].stated is False
        assert judged.stated == 0

    def test_an_over_claim_read_out_of_a_refusal_is_normalised(self) -> None:
        judged, incoherent = _parse(
            _payload(
                branches=[{"index": 1, "stated": False, "supported": False, "quote": ""}],
                forbidden=[{"index": 1, "asserted": True, "quote": "erillinen jäteastia"}],
            ),
            refused=True,
            forbidden=1,
        )
        assert incoherent == 1
        assert judged.forbidden[0].asserted is False


class TestTheJudgedArithmetic:
    """Pure. No model, no network, so it is tested exhaustively."""

    @staticmethod
    def _answer(
        question_id: str,
        *,
        required: int,
        stated: int,
        supported: int,
        over_claims: int = 0,
        forbidden_items: int = 0,
        refused: bool = False,
    ) -> JudgedAnswer:
        return JudgedAnswer(
            question_id=question_id,
            refused=refused,
            required_branches=required,
            branches=tuple(
                BranchVerdict(
                    index=index,
                    stated=index <= stated,
                    supported=index <= supported,
                    quote="erillinen jäteastia" if index <= stated else "",
                    quote_found=index <= stated,
                )
                for index in range(1, required + 1)
            ),
            forbidden=tuple(
                ForbiddenVerdict(
                    index=index,
                    asserted=index <= over_claims,
                    quote="erillinen jäteastia" if index <= over_claims else "",
                    quote_found=index <= over_claims,
                )
                for index in range(1, forbidden_items + 1)
            ),
        )

    def test_groundedness_is_over_branches_stated(self) -> None:
        """`CONTEXT.md:47`. The denominator that was settled the hard way."""
        metrics = judged_metrics(
            [
                self._answer("a", required=4, stated=2, supported=1),
                self._answer("b", required=4, stated=2, supported=2),
            ]
        )
        assert metrics.branches_stated == 4
        assert metrics.branches_supported == 3
        assert metrics.groundedness == pytest.approx(3 / 4)

    def test_branch_coverage_is_over_branches_required(self) -> None:
        metrics = judged_metrics([self._answer("a", required=5, stated=2, supported=2)])
        assert metrics.branch_coverage == pytest.approx(2 / 5)

    def test_saying_less_scores_a_perfect_groundedness_and_a_poor_coverage(self) -> None:
        """The gameability `CONTEXT.md:47` names, demonstrated rather than asserted.

        One well-supported branch of five is groundedness 1.0. This is exactly why
        D11 makes branch coverage a mandatory companion rather than a diagnostic.
        """
        metrics = judged_metrics([self._answer("a", required=5, stated=1, supported=1)])
        assert metrics.groundedness == pytest.approx(1.0)
        assert metrics.branch_coverage == pytest.approx(0.2)

    def test_a_wrongly_refused_question_scores_zero_on_coverage(self) -> None:
        """D11: cowardice is punished here, not by distorting groundedness."""
        metrics = judged_metrics(
            [self._answer("a", required=3, stated=0, supported=0, refused=True)]
        )
        assert metrics.branch_coverage == pytest.approx(0.0)
        assert metrics.groundedness is None

    def test_over_claim_rate_is_per_answer_not_per_item(self) -> None:
        """`CONTEXT.md:46` says share of ANSWERS. Both figures are reported."""
        metrics = judged_metrics(
            [
                self._answer(
                    "a", required=1, stated=1, supported=1, forbidden_items=3, over_claims=3
                ),
                self._answer("b", required=1, stated=1, supported=1, forbidden_items=3),
                self._answer("c", required=1, stated=1, supported=1, forbidden_items=3),
                self._answer("d", required=1, stated=1, supported=1, forbidden_items=3),
            ]
        )
        assert metrics.over_claim_rate == pytest.approx(0.25)
        assert metrics.forbidden_asserted == 3
        assert metrics.forbidden_items == 12

    def test_the_unit_count_is_branches_plus_forbidden(self) -> None:
        metrics = judged_metrics(
            [self._answer("a", required=3, stated=3, supported=3, forbidden_items=2)]
        )
        assert metrics.units == 5

    def test_judging_the_same_question_twice_raises(self) -> None:
        with pytest.raises(MetricsError, match="judged twice"):
            judged_metrics(
                [
                    self._answer("a", required=1, stated=1, supported=1),
                    self._answer("a", required=1, stated=1, supported=1),
                ]
            )

    def test_zero_answers_raises(self) -> None:
        with pytest.raises(MetricsError, match="zero answers"):
            judged_metrics([])


class TestTheVerdictTypesRefuseIncoherence:
    """Structural guards, so an impossible verdict cannot be counted."""

    def test_supported_without_stated_cannot_be_constructed(self) -> None:
        with pytest.raises(MetricsError, match=r"inflate it above 1\.0"):
            BranchVerdict(index=1, stated=False, supported=True, quote="", quote_found=False)

    def test_a_verdict_count_mismatch_cannot_be_constructed(self) -> None:
        with pytest.raises(MetricsError, match="branch verdicts for"):
            JudgedAnswer(
                question_id="a",
                refused=False,
                required_branches=2,
                branches=(
                    BranchVerdict(
                        index=1, stated=False, supported=False, quote="", quote_found=False
                    ),
                ),
                forbidden=(),
            )

    def test_an_index_gap_cannot_be_constructed(self) -> None:
        """An index is how a verdict attaches to a hand-written claim."""
        with pytest.raises(MetricsError, match=r"expected 1\.\.2"):
            JudgedAnswer(
                question_id="a",
                refused=False,
                required_branches=2,
                branches=(
                    BranchVerdict(
                        index=1, stated=False, supported=False, quote="", quote_found=False
                    ),
                    BranchVerdict(
                        index=3, stated=False, supported=False, quote="", quote_found=False
                    ),
                ),
                forbidden=(),
            )


class TestCitationAddressValidity:
    """AC9: computed with no judge and no network. A pure unit test, as specified."""

    RETRIEVED = ("lounais-suomi@2024-08-01#15", "lounais-suomi@2024-08-01#25")

    def test_a_retrieved_address_resolves(self) -> None:
        result = check(
            question_id="q",
            citations=("lounais-suomi@2024-08-01#15",),
            retrieved=self.RETRIEVED,
            authority="lounais-suomi",
        )
        assert result.inside == ("lounais-suomi@2024-08-01#15",)
        assert result.invalid == ()
        assert result.address_validity == pytest.approx(1.0)

    def test_a_non_address_is_unparseable_not_an_error(self) -> None:
        """What the model puts inside the envelope is the behaviour under measurement."""
        result = check(question_id="q", citations=("[15 §]", "lähde 3"), retrieved=self.RETRIEVED)
        assert result.unparseable == ("[15 §]", "lähde 3")
        assert result.inside == ()

    def test_an_address_the_question_never_retrieved_is_outside(self) -> None:
        result = check(
            question_id="q",
            citations=("lounais-suomi@2024-08-01#99",),
            retrieved=self.RETRIEVED,
            authority="lounais-suomi",
        )
        assert result.outside == ("lounais-suomi@2024-08-01#99",)
        assert result.foreign == ()

    def test_another_authoritys_address_is_foreign(self) -> None:
        """The product's #1 failure mode, one layer above the retrieval filter."""
        result = check(
            question_id="q",
            citations=("pirkanmaa@2021-07-01#25",),
            retrieved=self.RETRIEVED,
            authority="lounais-suomi",
        )
        assert result.foreign == ("pirkanmaa@2021-07-01#25",)
        assert result.outside == ("pirkanmaa@2021-07-01#25",)

    def test_citing_nothing_is_not_a_zero(self) -> None:
        """A refusal legitimately cites nothing; averaging it in as 0 would be a lie."""
        result = check(question_id="q", citations=(), retrieved=self.RETRIEVED)
        assert result.address_validity is None

    def test_the_rollup_separates_bad_citations_from_bad_answers(self) -> None:
        """One bad citation in each of two answers is not two bad ones in one."""
        spread = address_validity(
            [
                check(
                    question_id="a",
                    citations=("x", "lounais-suomi@2024-08-01#15"),
                    retrieved=self.RETRIEVED,
                ),
                check(
                    question_id="b",
                    citations=("y", "lounais-suomi@2024-08-01#15"),
                    retrieved=self.RETRIEVED,
                ),
            ]
        )
        concentrated = address_validity(
            [
                check(question_id="a", citations=("x", "y"), retrieved=self.RETRIEVED),
                check(
                    question_id="b",
                    citations=("lounais-suomi@2024-08-01#15",) * 2,
                    retrieved=self.RETRIEVED,
                ),
            ]
        )
        assert spread.validity == pytest.approx(concentrated.validity)
        assert spread.clean_answers == pytest.approx(0.0)
        assert concentrated.clean_answers == pytest.approx(0.5)


class TestD11IsEnforcedWhereTheTableIsRendered:
    """AC12, as a unit test. The live proof is `judge --stub-agreement`."""

    @staticmethod
    def _run(*, partial: bool = False) -> judging.JudgeRun:
        judged = JudgedAnswer(
            question_id="a",
            refused=False,
            required_branches=2,
            branches=(
                BranchVerdict(index=1, stated=True, supported=True, quote="x", quote_found=True),
                BranchVerdict(index=2, stated=True, supported=False, quote="y", quote_found=True),
            ),
            forbidden=(),
        )
        one = check(question_id="a", citations=(), retrieved=("lounais-suomi@2024-08-01#15",))
        usage = Usage(
            prompt_tokens=1,
            completion_tokens=1,
            reasoning_tokens=0,
            total_tokens=2,
            cost_usd=0.0,
        )
        judgement = Judgement(
            judged=judged,
            usage=usage,
            model="openai/gpt-oss-120b",
            incoherent_verdicts=0,
        )
        return judging.JudgeRun(
            source=Path("eval/runs/example.json"),
            source_commit="abc1234",
            dirty_provenance=False,
            cell=PUBLISHED,
            k=5,
            answerer="qwen/qwen3.6-27b",
            judge_model="openai/gpt-oss-120b",
            weak=False,
            judged=(judgement,),
            metrics=judged_metrics([judged]),
            checks=(one,),
            validity=address_validity([one]),
            tokens=1,
            cost_usd=0.0,
            ceiling=10,
            json_validation_retries=0,
            available=2 if partial else 1,
        )

    def test_unmeasured_agreement_withholds_the_published_value(self) -> None:
        table = format_judged(self._run(), agreement=None)
        assert "PUBLISHED   nothing" in table
        assert "NOT MEASURED" in table
        assert "DIAGNOSTIC" in table

    def test_agreement_below_the_floor_withholds_the_published_value(self) -> None:
        table = format_judged(self._run(), agreement=0.80)
        assert "PUBLISHED   nothing" in table
        assert "below the pre-registered" in table

    def test_agreement_at_the_floor_publishes_with_both_companions(self) -> None:
        table = format_judged(self._run(), agreement=AGREEMENT_FLOOR)
        assert "PUBLISHED   nothing" not in table
        assert "branch coverage" in table
        assert "judge agreement" in table

    def test_BRANCH_COVERAGE_leads_the_published_block_not_groundedness(self) -> None:
        """D11 inverted, 31 Aug 2026, on the Owner's decision.

        Groundedness measured 1.000 with complete retrieval and 1.000 without it --
        no variance on this answerer, which drops a branch rather than stating one
        it cannot cite. A headline identical in both strata tells a reader nothing
        and gets quoted anyway. Pinned as an ORDER because the first number under
        PUBLISHED is the one that gets copied into a README.
        """
        table = format_judged(self._run(), agreement=AGREEMENT_FLOOR)
        published = table.split("  PUBLISHED", 1)[1]
        assert published.index("branch coverage") < published.index("groundedness")
        assert "THE HEADLINE" in published.split("DIAGNOSTIC", 1)[0]

    def test_neither_judged_figure_is_ever_printed_without_the_other(self) -> None:
        """The half of D11 the inversion did NOT change, and the load-bearing half.

        Groundedness is gameable by saying less and branch coverage by saying
        everything; only the pair is a metric. True in the published block and in
        the withheld one, so no rendering path can emit a lone figure.
        """
        for agreement in (None, 0.5, AGREEMENT_FLOOR, 0.99):
            table = format_judged(self._run(), agreement=agreement)
            assert table.count("branch coverage") == table.count("groundedness")
            assert "branch coverage" in table

    def test_the_withheld_block_withholds_BOTH_figures_by_name(self) -> None:
        """Both are judge-dependent, so an unvalidated judge withholds both."""
        table = format_judged(self._run(), agreement=None)
        assert "Branch coverage AND groundedness are WITHHELD" in table

    def test_a_partial_run_cannot_publish_however_good_agreement_is(self) -> None:
        """The two gates are independent, and a reduced N overrides a healthy judge."""
        table = format_judged(self._run(partial=True), agreement=0.99)
        assert "PARTIAL RUN" in table
        assert "PUBLISHED   nothing" in table


class TestTheControlLoaderGuardsAgainstItself:
    """A mis-authored case would fail forever and read as a broken judge."""

    @staticmethod
    def _golden() -> GoldenSet:
        return GoldenSet(
            questions=(
                Question(
                    id="q-ls",
                    question="Miten?",
                    phrasing=Phrasing.AUTHORED,
                    phrasing_source=None,
                    municipality="Turku",
                    required_chunks=(_address("lounais-suomi", 15),),
                    required_branches=(Branch(claim="c", chunk=_address("lounais-suomi", 15)),),
                    forbidden=("f",),
                    label_source="s",
                ),
                Question(
                    id="q-pir",
                    question="Mitä?",
                    phrasing=Phrasing.AUTHORED,
                    phrasing_source=None,
                    municipality="Tampere",
                    required_chunks=(_address("pirkanmaa", 4),),
                    required_branches=(Branch(claim="c", chunk=_address("pirkanmaa", 4)),),
                    forbidden=("f",),
                    label_source="s",
                ),
            )
        )

    def _write(self, tmp_path: Path, cases: list[dict[str, object]]) -> Path:
        import yaml

        path = tmp_path / "control.yaml"
        path.write_text(yaml.safe_dump({"version": 1, "cases": cases}), encoding="utf-8")
        return path

    def _case(self, **overrides: object) -> dict[str, object]:
        case: dict[str, object] = {
            "id": "c1",
            "question_id": "q-ls",
            "shape": "wrong-citation",
            "answer": "väärä",
            "must_catch": [{"unit": "branch", "index": 1, "field": "supported", "expect": False}],
        }
        case.update(overrides)
        return case

    def test_an_index_past_the_golden_entry_raises(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            [
                self._case(
                    must_catch=[
                        {"unit": "branch", "index": 9, "field": "supported", "expect": False}
                    ]
                )
            ],
        )
        with pytest.raises(JudgingError, match="would fail forever"):
            load_control(path, self._golden())

    def test_a_case_with_nothing_to_check_raises(self, tmp_path: Path) -> None:
        """It would pass any judge, including one that returns nothing."""
        path = self._write(tmp_path, [self._case(must_catch=[])])
        with pytest.raises(JudgingError, match="must_catch is required"):
            load_control(path, self._golden())

    def test_an_unknown_question_raises(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, [self._case(question_id="nope")])
        with pytest.raises(JudgingError, match="not in the golden set"):
            load_control(path, self._golden())

    def test_an_unknown_shape_raises(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, [self._case(shape="vibes")])
        with pytest.raises(JudgingError, match="shape must be one of"):
            load_control(path, self._golden())

    def test_an_asserted_field_on_a_branch_raises(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            [
                self._case(
                    must_catch=[{"unit": "branch", "index": 1, "field": "asserted", "expect": True}]
                )
            ],
        )
        with pytest.raises(JudgingError, match="a branch verdict has fields"):
            load_control(path, self._golden())

    def test_one_authority_alone_raises(self, tmp_path: Path) -> None:
        """A judge good at one authority's prose and bad at another's averages healthy."""
        path = self._write(
            tmp_path,
            [self._case(id=f"c{n}", shape=shape) for n, shape in enumerate(judging.SHAPES)],
        )
        with pytest.raises(JudgingError, match="at least two authorities"):
            load_control(path, self._golden())

    def test_a_missing_shape_raises(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            [
                self._case(id=f"ls{n}", question_id="q-ls", shape=shape)
                for n, shape in enumerate(judging.SHAPES)
            ]
            + [self._case(id="pir0", question_id="q-pir", shape="wrong-citation")],
        )
        with pytest.raises(JudgingError, match="Missing:"):
            load_control(path, self._golden())

    def test_the_real_control_loads_and_covers_every_shape(self, golden: GoldenSet) -> None:
        """The shipped control, checked against the real golden set."""
        cases = load_control(judging.DEFAULT_CONTROL, golden)
        assert len(cases) == 8
        assert {case.shape for case in cases} == set(judging.SHAPES)
        assert all(case.why for case in cases), "every case states why it exists"


class TestReadingARecordedRun:
    """The guards that stop a stale or malformed run being judged."""

    @staticmethod
    def _run_payload(**overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "cell": PUBLISHED.name,
            "k": 5,
            "model": "qwen/qwen3.6-27b",
            "reasoning": True,
            "commit": "abc1234",
            "tokens": 1,
            "cost_usd": 0.1,
            "answers": [
                {
                    "question_id": "q1",
                    "population": "answerable",
                    "question": "Miten?",
                    "municipality": "Turku",
                    "authority_key": "lounais-suomi",
                    "retrieved": ["lounais-suomi@2024-08-01#15"],
                    "refused": False,
                    "text": "Vastaus.",
                    "citations": ["lounais-suomi@2024-08-01#15"],
                }
            ],
        }
        payload.update(overrides)
        return payload

    def _write(self, tmp_path: Path, payload: dict[str, object]) -> Path:
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_a_missing_file_says_how_to_make_one(self, tmp_path: Path) -> None:
        with pytest.raises(JudgingError, match="answer --all --out"):
            load_run(tmp_path / "absent.json")

    def test_an_empty_answer_text_raises(self, tmp_path: Path) -> None:
        """It judges as stating nothing, which is not distinguishable from a refusal."""
        payload = self._run_payload()
        answers = payload["answers"]
        assert isinstance(answers, list)
        answers[0]["text"] = "   "
        with pytest.raises(JudgingError, match="empty answer text"):
            load_run(self._write(tmp_path, payload))

    def test_an_unknown_population_raises(self, tmp_path: Path) -> None:
        payload = self._run_payload()
        answers = payload["answers"]
        assert isinstance(answers, list)
        answers[0]["population"] = "other"
        with pytest.raises(JudgingError, match="never pooled"):
            load_run(self._write(tmp_path, payload))

    def test_duplicate_ids_raise(self, tmp_path: Path) -> None:
        payload = self._run_payload()
        answers = payload["answers"]
        assert isinstance(answers, list)
        answers.append(dict(answers[0]))
        with pytest.raises(JudgingError, match="duplicate question ids"):
            load_run(self._write(tmp_path, payload))

    def test_a_run_from_a_dirty_tree_is_flagged_not_refused(self, tmp_path: Path) -> None:
        """The run this project has is `4b75dfd-dirty`. Say so; do not refuse it."""
        loaded = load_run(self._write(tmp_path, self._run_payload(commit="4b75dfd-dirty")))
        assert loaded.dirty_provenance is True

    def test_a_run_answered_in_another_cell_is_refused(self, tmp_path: Path) -> None:
        loaded = load_run(self._write(tmp_path, self._run_payload(cell="snowball/0")))
        with pytest.raises(JudgingError, match="would be judged against"):
            judging.assert_run_matches_corpus(loaded, retrieval=(), cell=PUBLISHED)

    def test_a_moved_corpus_is_refused_with_the_question_named(self, tmp_path: Path) -> None:
        """The drift detector. Judging a stale run would read as an answerer failure."""
        loaded = load_run(self._write(tmp_path, self._run_payload()))
        with pytest.raises(JudgingError, match="the corpus has moved under"):
            judging.assert_run_matches_corpus(
                loaded, retrieval=(_question_run("q1", "#28"),), cell=PUBLISHED
            )

    def test_a_tie_reordering_the_context_is_not_drift(self, tmp_path: Path) -> None:
        """Compared as sets: from the judge's position the context is a set."""
        payload = self._run_payload()
        answers = payload["answers"]
        assert isinstance(answers, list)
        answers[0]["retrieved"] = [
            "lounais-suomi@2024-08-01#25",
            "lounais-suomi@2024-08-01#15",
        ]
        loaded = load_run(self._write(tmp_path, payload))
        judging.assert_run_matches_corpus(
            loaded, retrieval=(_question_run("q1", "#15", "#25"),), cell=PUBLISHED
        )

    def test_a_question_the_run_never_answered_is_refused(self, tmp_path: Path) -> None:
        loaded = load_run(self._write(tmp_path, self._run_payload()))
        with pytest.raises(JudgingError, match="has no answer for"):
            judging.assert_run_matches_corpus(
                loaded,
                retrieval=(_question_run("q1", "#15"), _question_run("q2", "#15")),
                cell=PUBLISHED,
            )


class TestThePromptsAndTheCeiling:
    def test_the_weak_prompt_is_genuinely_weaker(self) -> None:
        """It has to be a real failure mode, not a strawman, or the red proof is theatre."""
        assert "Judge ONLY against EXCERPTS" in SYSTEM_PROMPT
        assert "benefit of the doubt" in WEAK_SYSTEM_PROMPT
        assert "Judge ONLY against EXCERPTS" not in WEAK_SYSTEM_PROMPT
        assert len(WEAK_SYSTEM_PROMPT) < len(SYSTEM_PROMPT)

    def test_both_prompts_demand_the_same_envelope(self) -> None:
        """Otherwise the red proof would fail on parsing, not on judgement."""
        for prompt in (SYSTEM_PROMPT, WEAK_SYSTEM_PROMPT):
            assert '"branches"' in prompt
            assert '"forbidden"' in prompt
            assert '"quote": string' in prompt

    def test_the_ceiling_scales_with_the_run(self) -> None:
        """D8's constant made a legitimate run trip its own enforcer. This does not."""
        assert judge_ceiling_for(1) == 600_000
        assert judge_ceiling_for(50) > 600_000
        assert judge_ceiling_for(50) == 2 * 50 * 11_000

    def test_a_zero_call_run_raises(self) -> None:
        with pytest.raises(JudgementError, match="at least one call"):
            judge_ceiling_for(0)

    def test_a_question_with_no_branches_cannot_be_judged(self) -> None:
        """Groundedness would have no denominator and coverage no numerator."""
        with pytest.raises(JudgementError, match="nothing to judge"):
            format_task(
                question="Miten?",
                answer_text="Vastaus.",
                refused=False,
                cited=(),
                branches=(),
                forbidden=(),
            )

    def test_an_empty_forbidden_list_is_stated_out_loud(self) -> None:
        """An absent heading reads as a truncated prompt and invites invention."""
        task = format_task(
            question="Miten?",
            answer_text="Vastaus.",
            refused=False,
            cited=(),
            branches=("c",),
            forbidden=(),
        )
        assert "none for this question" in task


def _address(authority: str, clause: int) -> ChunkAddress:

    effective = date(2024, 8, 1) if authority == "lounais-suomi" else date(2021, 7, 1)
    return ChunkAddress(authority=authority, effective_date=effective, clause=clause)


def _question_run(question_id: str, *clauses: str) -> QuestionRun:
    """A retrieval result, built by hand, for the drift check's tests."""
    addresses = [f"lounais-suomi@2024-08-01{clause}" for clause in clauses]
    question = Question(
        id=question_id,
        question="Miten?",
        phrasing=Phrasing.AUTHORED,
        phrasing_source=None,
        municipality="Turku",
        required_chunks=(_address("lounais-suomi", 15),),
        required_branches=(Branch(claim="c", chunk=_address("lounais-suomi", 15)),),
        forbidden=(),
        label_source="s",
    )
    return QuestionRun(
        question=question,
        authority_key="lounais-suomi",
        effective_date=date(2024, 8, 1),
        lexemes=("x",),
        hits=tuple(
            Hit(
                position=index,
                address=address,
                citation="15 §",
                rank=1.0,
                authority_key="lounais-suomi",
            )
            for index, address in enumerate(addresses, start=1)
        ),
        outcome=QuestionOutcome(
            question_id=question_id,
            required=("lounais-suomi@2024-08-01#15",),
            retrieved=tuple(addresses),
            # Classified rather than left empty: `QuestionOutcome` requires every
            # required chunk to be retrieved or accounted for as a miss, and that
            # guard is the reason this helper cannot cut the corner.
            misses=(
                ()
                if "lounais-suomi@2024-08-01#15" in addresses
                else (Miss(address="lounais-suomi@2024-08-01#15", kind=MissKind.RANKED_OUT),)
            ),
        ),
    )


class TestASpliceIsNotAFabrication:
    """The distinction was measured, not reasoned about, so it is pinned here.

    The first full judge run flagged 9 of 50 answers on the contiguity check, and
    the first one inspected had joined `- Biojäte:` from a bullet's head to a
    sentence three clauses later. Every word was present and the claim really was
    stated. One count for both would have published a judge-fabrication rate of
    18% that was mostly untidy quoting.
    """

    ANSWER = "Alku: eka väite [a@2024-08-01#1]. Toka väite. Kolmas väite [a@2024-08-01#2]."

    def test_a_contiguous_quote_scores_one_and_is_found(self) -> None:
        assert quote_words_present("Toka väite", self.ANSWER) == pytest.approx(1.0)

    def test_a_spliced_quote_has_every_word_but_is_not_contiguous(self) -> None:
        assert quote_words_present("Alku: Kolmas väite", self.ANSWER) == pytest.approx(1.0)

    def test_an_invented_word_lowers_the_share(self) -> None:
        assert quote_words_present("Neljäs väite", self.ANSWER) == pytest.approx(0.5)

    def test_repeating_a_word_the_answer_uses_once_goes_beyond_the_text(self) -> None:
        """Multiset containment, not set containment."""
        assert quote_words_present("Alku Alku", self.ANSWER) == pytest.approx(0.5)

    def test_an_empty_quote_is_not_a_fabrication(self) -> None:
        """It is only ever paired with a negative verdict."""
        assert quote_words_present("", self.ANSWER) == pytest.approx(1.0)

    def test_the_two_are_counted_apart(self) -> None:
        spliced = JudgedAnswer(
            question_id="splice",
            refused=False,
            required_branches=1,
            branches=(
                BranchVerdict(
                    index=1,
                    stated=True,
                    supported=True,
                    quote="Alku: Kolmas väite",
                    quote_found=False,
                    quote_words_present=1.0,
                ),
            ),
            forbidden=(),
        )
        invented = JudgedAnswer(
            question_id="fabrication",
            refused=False,
            required_branches=1,
            branches=(
                BranchVerdict(
                    index=1,
                    stated=True,
                    supported=True,
                    quote="Neljäs väite",
                    quote_found=False,
                    quote_words_present=0.5,
                ),
            ),
            forbidden=(),
        )
        metrics = judged_metrics([spliced, invented])
        assert metrics.judge_splices == ("splice",)
        assert metrics.judge_fabrications == ("fabrication",)

    def test_a_share_outside_zero_to_one_cannot_be_constructed(self) -> None:
        with pytest.raises(MetricsError, match="is a share"):
            BranchVerdict(
                index=1,
                stated=False,
                supported=False,
                quote="",
                quote_found=False,
                quote_words_present=1.5,
            )


class TestUnitAgreementAndItsInterval:
    """Built for tracer slice 5's judge-human agreement; used first on the judge itself."""

    @staticmethod
    def _labels(pattern: dict[str, list[bool]], field: str = "stated") -> list[UnitLabel]:
        return [
            UnitLabel(question_id=question, unit="branch", index=index, field=field, value=value)
            for question, values in pattern.items()
            for index, value in enumerate(values, start=1)
        ]

    def test_perfect_agreement_does_not_report_certainty(self) -> None:
        """The cluster-robust variance is zero here, so it must not publish [1, 1]."""
        pattern = {"q1": [True, True], "q2": [False, True], "q3": [True, False]}
        result = unit_agreement(self._labels(pattern), self._labels(pattern))
        assert result.rate == pytest.approx(1.0)
        assert result.interval_kind == "wilson-over-clusters"
        assert result.low < 0.6, "three questions cannot buy certainty"

    def test_disagreement_is_named_not_only_counted(self) -> None:
        first = self._labels({"q1": [True, True], "q2": [True, True], "q3": [True, True]})
        second = self._labels({"q1": [True, False], "q2": [True, True], "q3": [True, True]})
        result = unit_agreement(first, second)
        assert result.agreed == 5
        assert result.units == 6
        assert [one.question_id for one in result.disagreements] == ["q1"]
        assert result.disagreements[0].index == 2

    def test_clustering_widens_the_interval_over_a_naive_one(self) -> None:
        """The whole reason D3 demands this. Disagreement concentrated in one question.

        A naive binomial over 20 units would call 0.80 precise. Clustered by
        question -- where one answer failing takes all its units with it -- it is
        not, and the interval has to say so.
        """
        first = self._labels({f"q{n}": [True] * 5 for n in range(4)})
        second = self._labels(
            {"q0": [False] * 5, "q1": [True] * 5, "q2": [True] * 5, "q3": [True] * 5}
        )
        clustered = unit_agreement(first, second)
        naive = wilson(clustered.agreed, clustered.units)
        assert clustered.rate == pytest.approx(0.75)
        assert (clustered.high - clustered.low) > (naive.high - naive.low)

    def test_the_field_split_is_computed_because_prediction_2_needs_it(self) -> None:
        """D5's prediction 2 compares agreement on forbidden items against branches."""
        first = self._labels({"q1": [True], "q2": [True]}, field="stated") + self._labels(
            {"q1": [True], "q2": [True]}, field="asserted"
        )
        second = self._labels({"q1": [True], "q2": [True]}, field="stated") + self._labels(
            {"q1": [False], "q2": [False]}, field="asserted"
        )
        result = unit_agreement(first, second)
        split = {field: (agreed, units) for field, agreed, units in result.by_field}
        assert split["stated"] == (2, 2)
        assert split["asserted"] == (0, 2)

    def test_label_sets_covering_different_units_raise(self) -> None:
        """Comparing the overlap would be a reduced N arrived at by accident."""
        first = self._labels({"q1": [True], "q2": [True]})
        second = self._labels({"q1": [True]})
        with pytest.raises(MetricsError, match="do not cover the same units"):
            unit_agreement(first, second)

    def test_a_duplicated_unit_raises(self) -> None:
        first = self._labels({"q1": [True]})
        with pytest.raises(MetricsError, match="same unit twice"):
            unit_agreement(first + first, first + first)

    def test_one_cluster_cannot_support_an_interval(self) -> None:
        with pytest.raises(MetricsError, match="at least two clusters"):
            cluster_robust_interval([(3, 4)])

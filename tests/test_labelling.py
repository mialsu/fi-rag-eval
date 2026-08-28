"""The labelling protocol: blind, resumable, and forced units excluded.

ADR-0011's decisions, as tests. Nothing here touches a network or a model — the
labelling core is pure by design, and the interactive shell in `cli.py` holds no
logic precisely so that this file can cover the protocol.

The test that matters most is the one asserting `format_context` **cannot** be
handed a judge verdict. A protocol whose blindness depended on nobody passing the
wrong argument would not be a protocol.
"""

from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path

import pytest
import yaml

from fi_rag_eval import labelling
from fi_rag_eval.addressing import ChunkAddress
from fi_rag_eval.golden import Branch, GoldenSet, Phrasing, Question
from fi_rag_eval.judging import RecordedAnswer, RecordedRun
from fi_rag_eval.labelling import (
    BRANCH,
    FORBIDDEN,
    HumanLabel,
    LabellingError,
    QuestionToLabel,
    format_context,
    human_unit_labels,
    informative,
    judge_unit_labels,
    load_labels,
    pending,
    questions_to_label,
    run_session,
    write_labels,
)

ADDRESS = "lounais-suomi@2024-08-01#15"
BODIES = {ADDRESS: "15 § Velvoite koskee taajamaa."}
CITATIONS = {ADDRESS: "15 § Lajitteluvelvoitteet"}


def _address(clause: int = 15) -> ChunkAddress:
    return ChunkAddress(authority="lounais-suomi", effective_date=date(2024, 8, 1), clause=clause)


def _question(question_id: str, *, branches: int = 2, forbidden: int = 1) -> Question:
    return Question(
        id=question_id,
        question=f"Kysymys {question_id}?",
        phrasing=Phrasing.AUTHORED,
        phrasing_source=None,
        municipality="Turku",
        required_chunks=(_address(),),
        required_branches=tuple(
            Branch(claim=f"{question_id} väite {n}", chunk=_address())
            for n in range(1, branches + 1)
        ),
        forbidden=tuple(f"{question_id} kielletty {n}" for n in range(1, forbidden + 1)),
        label_source="s",
    )


def _answer(question_id: str, *, refused: bool = False) -> RecordedAnswer:
    return RecordedAnswer(
        question_id=question_id,
        population="answerable",
        question=f"Kysymys {question_id}?",
        municipality="Turku",
        authority_key="lounais-suomi",
        retrieved=(ADDRESS,),
        refused=refused,
        text=f"Vastaus {question_id} [{ADDRESS}]." if not refused else "En voi vastata.",
        citations=(ADDRESS,) if not refused else (),
    )


def _fixture(*, refused_ids: frozenset[str] = frozenset()) -> tuple[GoldenSet, RecordedRun]:
    ids = ("q-answered", "q-refused")
    golden = GoldenSet(questions=tuple(_question(one) for one in ids))
    run = RecordedRun(
        source=Path("eval/frozen/sample-tracer5.json"),
        cell="lemma-reasm/0",
        k=5,
        model="qwen/qwen3.6-27b",
        reasoning=True,
        commit="4b75dfd-dirty",
        tokens=1,
        cost_usd=0.1,
        answers=tuple(_answer(one, refused=one in refused_ids) for one in ids),
    )
    return golden, run


class TestBlindness:
    """ADR-0011 decision 1, enforced by a signature rather than by discipline."""

    def test_format_context_takes_nothing_the_judge_produced(self) -> None:
        """The strongest form this can be tested in: there is no parameter for it.

        A judge verdict, a suggestion, a confidence or a stability flag cannot
        reach the labeller because no argument accepts one. If someone later adds
        such a parameter, this test fails and they have to read ADR-0011.
        """
        parameters = set(inspect.signature(format_context).parameters)
        assert parameters == {"one", "bodies", "citations"}

    def test_what_the_labeller_sees_is_only_the_answer_and_the_corpus(self) -> None:
        one = QuestionToLabel(
            question_id="q",
            question="Kysymys?",
            municipality="Turku",
            authority_key="lounais-suomi",
            answer_text=f"Vastaus [{ADDRESS}].",
            refused=False,
            citations=(ADDRESS,),
            retrieved=(ADDRESS,),
            branches=("väite",),
            forbidden=(),
        )
        shown = format_context(one, BODIES, CITATIONS)
        assert "Kysymys?" in shown
        assert BODIES[ADDRESS] in shown
        assert "Vastaus" in shown
        for leak in ("stated", "supported", "asserted", "judge", "verdict", "stability"):
            assert leak not in shown.lower(), f"{leak!r} leaked into the labelling view"

    def test_a_missing_chunk_body_is_an_error_not_a_hole(self) -> None:
        one = QuestionToLabel(
            question_id="q",
            question="Kysymys?",
            municipality="Turku",
            authority_key="lounais-suomi",
            answer_text="Vastaus.",
            refused=False,
            citations=(),
            retrieved=("lounais-suomi@2024-08-01#99",),
            branches=("väite",),
            forbidden=(),
        )
        with pytest.raises(LabellingError, match="judging support against a hole"):
            format_context(one, BODIES, CITATIONS)


class TestForcedUnitsAreExcluded:
    """ADR-0011 decision 6, and the arithmetic that decided it."""

    def test_a_refused_answer_is_not_offered_for_labelling(self) -> None:
        golden, run = _fixture(refused_ids=frozenset({"q-refused"}))
        questions = questions_to_label(golden=golden, run=run)
        assert [one.question_id for one in informative(questions)] == ["q-answered"]
        assert labelling.forced_units(questions) == 3

    def test_pending_never_offers_a_forced_unit(self) -> None:
        golden, run = _fixture(refused_ids=frozenset({"q-refused"}))
        questions = questions_to_label(golden=golden, run=run)
        assert {one.question_id for one, _, _ in pending(questions, ())} == {"q-answered"}

    def test_free_agreement_would_move_a_below_floor_judge_over_the_floor(self) -> None:
        """The arithmetic from ADR-0011 decision 6, pinned so it cannot be waved away.

        31 forced units in 199. A judge agreeing on 0.827 of the 168 informative
        units reaches 0.85 pooled -- clearing D11's floor on the strength of units
        nobody judged.
        """
        informative_units, forced = 168, 31
        real = 0.827
        pooled = (real * informative_units + forced) / (informative_units + forced)
        assert real < 0.85 <= pooled

    def test_nothing_is_forced_when_nothing_was_refused(self) -> None:
        golden, run = _fixture()
        questions = questions_to_label(golden=golden, run=run)
        assert labelling.forced_units(questions) == 0
        assert len(informative(questions)) == 2


class TestTheLabelTypeRefusesIncoherence:
    def test_a_branch_needs_stated(self) -> None:
        with pytest.raises(LabellingError, match="needs `stated`"):
            HumanLabel(question_id="q", unit=BRANCH, index=1)

    def test_a_stated_branch_needs_supported(self) -> None:
        with pytest.raises(LabellingError, match="needs `supported`"):
            HumanLabel(question_id="q", unit=BRANCH, index=1, stated=True)

    def test_an_unstated_branch_does_not_need_supported(self) -> None:
        label = HumanLabel(question_id="q", unit=BRANCH, index=1, stated=False)
        assert label.supported is None

    def test_supported_without_stated_is_refused(self) -> None:
        with pytest.raises(LabellingError, match=r"inflate groundedness above 1\.0"):
            HumanLabel(question_id="q", unit=BRANCH, index=1, stated=False, supported=True)

    def test_a_forbidden_item_needs_asserted(self) -> None:
        with pytest.raises(LabellingError, match="needs `asserted`"):
            HumanLabel(question_id="q", unit=FORBIDDEN, index=1)

    def test_a_forbidden_item_has_no_stated(self) -> None:
        with pytest.raises(LabellingError, match="has no `stated`"):
            HumanLabel(question_id="q", unit=FORBIDDEN, index=1, asserted=False, stated=True)


class TestPersistence:
    def test_a_round_trip_preserves_every_field(self, tmp_path: Path) -> None:
        labels = (
            HumanLabel(
                question_id="q",
                unit=BRANCH,
                index=1,
                stated=True,
                supported=False,
                note="contestable",
            ),
            HumanLabel(question_id="q", unit=BRANCH, index=2, stated=False),
            HumanLabel(question_id="q", unit=FORBIDDEN, index=1, asserted=True),
        )
        path = tmp_path / "labels.yaml"
        write_labels(path, labels, sample=Path("s.json"), commit="abc")
        assert load_labels(path) == labels

    def test_an_absent_file_is_empty_not_an_error(self, tmp_path: Path) -> None:
        """Resumability starts from nothing on the first run."""
        assert load_labels(tmp_path / "absent.yaml") == ()

    def test_the_file_records_the_protocol_it_was_made_under(self, tmp_path: Path) -> None:
        """A label set whose protocol is unstated is a label set nobody can defend."""
        path = tmp_path / "labels.yaml"
        write_labels(
            path,
            (HumanLabel(question_id="q", unit=FORBIDDEN, index=1, asserted=False),),
            sample=Path("eval/frozen/sample-tracer5.json"),
            commit="4b75dfd-dirty",
        )
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "BLIND" in document["protocol"]
        assert document["sample_answered_at_commit"] == "4b75dfd-dirty"

    def test_a_duplicated_unit_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "labels": [
                        # Both entries must be individually VALID, or the type's own
                        # guard fires before the whole-set duplicate check is reached.
                        {"question_id": "q", "unit": "branch", "index": 1, "stated": False},
                        {"question_id": "q", "unit": "branch", "index": 1, "stated": False},
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(LabellingError, match="labelled twice"):
            load_labels(path)

    def test_a_wrong_version_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.yaml"
        path.write_text(yaml.safe_dump({"version": 99, "labels": []}), encoding="utf-8")
        with pytest.raises(LabellingError, match="label version"):
            load_labels(path)


class TestTheSession:
    """One pass per unit, resumable, and every label on disk immediately."""

    @staticmethod
    def _drive(
        script: list[str], path: Path, *, refused: bool = False
    ) -> tuple[labelling.SessionResult, tuple[QuestionToLabel, ...]]:
        golden, run = _fixture(refused_ids=frozenset({"q-refused"}) if refused else frozenset())
        questions = questions_to_label(golden=golden, run=run)
        feed = iter(script)
        return run_session(
            questions=questions,
            labels_path=path,
            sample_path=Path("s.json"),
            sample_commit="abc",
            bodies=BODIES,
            citations=CITATIONS,
            prompt=lambda _: next(feed),
            emit=lambda _: None,
        ), questions

    def test_a_branch_takes_two_answers_and_a_forbidden_item_one(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.yaml"
        # q-answered: branch1 stated+supported, branch2 not stated, forbidden1 no
        result, _ = self._drive(["y", "y", "n", "n", "q"], path, refused=True)
        assert result.labelled == 3
        labels = load_labels(path)
        assert (labels[0].stated, labels[0].supported) == (True, True)
        assert (labels[1].stated, labels[1].supported) == (False, None)
        assert labels[2].asserted is False

    def test_a_note_survives_onto_the_verdict(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.yaml"
        self._drive(["y this one is arguable", "y", "q"], path, refused=True)
        assert load_labels(path)[0].note == "this one is arguable"

    def test_quitting_keeps_every_label_already_given(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.yaml"
        result, _ = self._drive(["y", "y", "q"], path, refused=True)
        assert result.quit_early is True
        assert len(load_labels(path)) == 1

    def test_a_resumed_session_continues_where_it_stopped(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.yaml"
        self._drive(["y", "y", "q"], path, refused=True)
        second, questions = self._drive(["n", "n", "q"], path, refused=True)
        assert second.labelled == 2
        labels = load_labels(path)
        assert len(labels) == 3
        assert pending(questions, labels) == ()

    def test_a_skip_defers_the_unit_rather_than_dropping_it(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.yaml"
        result, questions = self._drive(["s", "y", "y", "q"], path, refused=True)
        assert result.skipped == 1
        assert result.labelled == 1
        # The skipped unit is still pending, so `agreement` will still refuse.
        assert any(
            unit == BRANCH and index == 1
            for _, unit, index in pending(questions, load_labels(path))
        )

    def test_skipping_the_second_half_of_a_branch_defers_the_whole_unit(
        self, tmp_path: Path
    ) -> None:
        """A branch with `stated` and no `supported` cannot enter groundedness."""
        path = tmp_path / "labels.yaml"
        result, _ = self._drive(["y", "s", "q"], path, refused=True)
        assert result.labelled == 0
        assert result.skipped == 1
        assert load_labels(path) == ()

    def test_unrecognised_input_is_rejected_not_guessed(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.yaml"
        result, _ = self._drive(["maybe", "?", "y", "y", "q"], path, refused=True)
        assert result.labelled == 1


class TestFeedingTheAgreementArithmetic:
    def test_an_unstated_branch_contributes_one_field_and_a_stated_one_two(self) -> None:
        flattened = human_unit_labels(
            [
                HumanLabel(question_id="q", unit=BRANCH, index=1, stated=True, supported=False),
                HumanLabel(question_id="q", unit=BRANCH, index=2, stated=False),
                HumanLabel(question_id="q", unit=FORBIDDEN, index=1, asserted=True),
            ]
        )
        assert [(one.unit, one.index, one.field) for one in flattened] == [
            (BRANCH, 1, "stated"),
            (BRANCH, 1, "supported"),
            (BRANCH, 2, "stated"),
            (FORBIDDEN, 1, "asserted"),
        ]

    def test_the_humans_stated_decides_scope_not_the_judges(self) -> None:
        """Otherwise the compared unit set would depend on the thing being measured.

        The human says branch 1 is stated and the judge says it is not. `supported`
        is in scope because the HUMAN put it there, and the judge's `supported` is
        read for comparison -- rather than the unit silently vanishing because the
        judge declined to state it.
        """
        labels = [HumanLabel(question_id="q", unit=BRANCH, index=1, stated=True, supported=True)]
        payload = {
            "answers": [
                {
                    "question_id": "q",
                    "branches": [{"index": 1, "stated": False, "supported": False}],
                    "forbidden": [],
                }
            ]
        }
        judged = judge_unit_labels(payload, restrict_to=labels)
        assert [(one.field, one.value) for one in judged] == [
            ("stated", False),
            ("supported", False),
        ]

    def test_a_missing_judge_verdict_raises_naming_the_unit(self) -> None:
        labels = [HumanLabel(question_id="q", unit=FORBIDDEN, index=1, asserted=False)]
        with pytest.raises(LabellingError, match="no verdict for"):
            judge_unit_labels({"answers": []}, restrict_to=labels)

    def test_self_consistency_shapes_cover_every_informative_unit(self) -> None:
        golden, run = _fixture(refused_ids=frozenset({"q-refused"}))
        questions = questions_to_label(golden=golden, run=run)
        shape = labelling.every_informative_label(questions)
        assert {one.question_id for one in shape} == {"q-answered"}
        # stated=True throughout, so every branch's `supported` is in scope: the
        # widest unit set available, which is the right choice for a ceiling.
        assert all(one.stated for one in shape if one.unit == BRANCH)
        assert len(human_unit_labels(shape)) == 2 * 2 + 1


class TestTheSampleAndTheGoldenSetMustAgree:
    def test_a_sample_missing_a_golden_question_raises(self) -> None:
        golden = GoldenSet(questions=(_question("q-a"), _question("q-b")))
        run = RecordedRun(
            source=Path("s.json"),
            cell="lemma-reasm/0",
            k=5,
            model="m",
            reasoning=True,
            commit="abc",
            tokens=1,
            cost_usd=0.0,
            answers=(_answer("q-a"),),
        )
        with pytest.raises(LabellingError, match="no answer for"):
            questions_to_label(golden=golden, run=run)


class TestTheShippedSampleIsUsable:
    """The committed artifact, checked against the real golden set."""

    def test_the_frozen_sample_covers_the_whole_answerable_population(self) -> None:
        from fi_rag_eval.judging import load_run

        run = load_run(labelling.DEFAULT_SAMPLE)
        assert len(run.answerable) == 50
        assert len(run.refusals) == 14

    def test_the_frozen_sample_states_its_own_provenance(self) -> None:
        import json

        payload = json.loads(labelling.DEFAULT_SAMPLE.read_text(encoding="utf-8"))
        assert payload["provenance_is_a_tree_not_a_commit"] is True
        assert payload["answered_at_commit"].endswith("-dirty")
        assert "do not re-generate" in payload["_what_this_is"].lower()

    def test_the_labelling_burden_is_168_units(self, golden: GoldenSet) -> None:
        """The number quoted in ADR-0011, the README and the module docstring."""
        from fi_rag_eval.judging import load_run

        questions = questions_to_label(golden=golden, run=load_run(labelling.DEFAULT_SAMPLE))
        assert sum(one.units for one in informative(questions)) == 168
        assert labelling.forced_units(questions) == 31

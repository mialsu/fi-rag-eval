"""The refusal population: its entry type, its arithmetic, and its enforcers.

Nothing here makes a model call. The refusal *metrics* are arithmetic by
decision (D-derived, slice 5) -- no judge, no network -- which is what lets them
be tested exactly rather than sampled, and it is the same property that makes
retrieval metrics the ones that win arguments.

The database-backed tests carry the checks that matter most: that every refusal
question's central claim still holds against the real corpus, and that the check
goes red when it stops holding.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
import yaml

from fi_rag_eval import db
from fi_rag_eval.addressing import ChunkAddress
from fi_rag_eval.analyse import Analyser, Morphology
from fi_rag_eval.answer import TOKEN_CEILING, Answer, AnswerError, TokenBudget, Usage, ceiling_for
from fi_rag_eval.answering import AnswerRun, ScoredAnswer
from fi_rag_eval.cli import main
from fi_rag_eval.evaluate import (
    ABSENCE_ANALYSER,
    PUBLISHED,
    EvaluationError,
    assert_refusal_absences,
    question_stopwords,
    retrieve_refusals,
)
from fi_rag_eval.golden import (
    GoldenSet,
    GoldenSetError,
    Phrasing,
    RefusalKind,
    RefusalQuestion,
    load_golden_set,
)
from fi_rag_eval.manifest import Manifest, ManifestError
from fi_rag_eval.metrics import (
    AnswerOutcome,
    MetricsError,
    QuestionOutcome,
    RefusalOutcome,
    compute,
    refusal_metrics,
    wilson,
)
from fi_rag_eval.metrics import RefusalKind as MetricsRefusalKind
from fi_rag_eval.report import format_refusal_detail, format_refusals

REFUSALS = Path(__file__).resolve().parent.parent / "corpus" / "golden" / "refusals.yaml"


def out_of_jurisdiction(golden: GoldenSet) -> tuple[RefusalQuestion, ...]:
    """The hard half of the population. A test helper, deliberately not on GoldenSet.

    A convenience method used only by tests is production API nobody calls, and
    this project deleted one for that reason a commit ago.
    """
    return tuple(r for r in golden.refusals if r.kind is RefusalKind.OUT_OF_JURISDICTION)


def write(tmp_path: Path, document: dict[str, object]) -> Path:
    path = tmp_path / "refusals.yaml"
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    return path


def entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "ooj-example",
        "question": "Saanko asentaa jätemyllyn?",
        "kind": "out-of-jurisdiction",
        "phrasing": "authored",
        "municipality": "Tampere",
        "absent_lexeme": "jätemylly",
        "absence_source": "read Pirkanmaa's clause list",
        "answerable_from": "lounais-suomi@2024-08-01#19",
        "label_source": "Lounais-Suomi 19 §",
    }
    base.update(overrides)
    return base


class TestTheCommittedSet:
    """The 13 real entries, as shipped.

    Fourteen until 31 Aug 2026, when `ooc-autonrenkaiden-vastaanotto` was removed:
    both authorities' 2 § enumerate `renkaat` as producer-responsibility waste and
    12 § says where such waste goes, so the corpus answered the question outright
    and the refusal label was wrong. See the tombstone in `refusals.yaml`.
    """

    def test_the_population_is_thirteen_split_seven_and_six(self, golden: GoldenSet) -> None:
        assert len(golden.refusals) == 13
        kinds = [r.kind for r in golden.refusals]
        assert kinds.count(RefusalKind.OUT_OF_CORPUS) == 7
        assert kinds.count(RefusalKind.OUT_OF_JURISDICTION) == 6

    def test_the_removed_tyre_question_has_not_come_back(self, golden: GoldenSet) -> None:
        """It is removable only once; re-adding it would silently restore the defect.

        Its answer was correct and was scored as a missed refusal, which is the
        failure direction that makes a good answerer look worse. If this question
        ever returns it returns to the ANSWERABLE set, with branches and a
        re-recorded baseline -- never here.
        """
        assert not any(r.id == "ooc-autonrenkaiden-vastaanotto" for r in golden.refusals)
        assert not any(r.absent_lexeme == "rengas" for r in golden.refusals)

    def test_the_answerable_population_is_untouched_at_fifty(self, golden: GoldenSet) -> None:
        """`len(golden)` is the retrieval headline's N and must not have moved."""
        assert len(golden) == 50
        assert len(golden.questions) == 50

    def test_every_out_of_jurisdiction_entry_points_at_the_other_authority(
        self, golden: GoldenSet, manifest: Manifest
    ) -> None:
        for refusal in out_of_jurisdiction(golden):
            asked = manifest.resolve_municipality(refusal.municipality).key
            assert refusal.foreign_authority is not None
            assert refusal.foreign_authority != asked

    def test_out_of_jurisdiction_is_asked_in_both_directions(self, golden: GoldenSet) -> None:
        """Three each way, so a one-directional failure cannot hide behind the other."""
        asked = [r.municipality for r in out_of_jurisdiction(golden)]
        pirkanmaa = {"Tampere", "Nokia", "Ylöjärvi"}
        assert sum(1 for m in asked if m in pirkanmaa) == 3
        assert sum(1 for m in asked if m not in pirkanmaa) == 3

    def test_no_refusal_question_targets_the_absorbed_pirkanmaa_clause(
        self, golden: GoldenSet
    ) -> None:
        targets = {str(r.answerable_from) for r in golden.refusals if r.answerable_from}
        assert "pirkanmaa@2021-07-01#18" not in targets

    def test_every_entry_records_how_the_absence_was_established(self, golden: GoldenSet) -> None:
        """The lexeme is the drift detector; this is the claim it protects."""
        for refusal in golden.refusals:
            assert len(refusal.absence_source) > 40, refusal.id
            assert refusal.absent_lexeme.strip()


class TestTheEntryType:
    def test_an_out_of_jurisdiction_entry_must_say_where_it_IS_answerable(
        self, manifest: Manifest, tmp_path: Path
    ) -> None:
        path = write(tmp_path, {"version": 1, "refusals": [entry(answerable_from=None)]})
        with pytest.raises(GoldenSetError, match="must name answerable_from"):
            load_golden_set(path, manifest)

    def test_an_out_of_corpus_entry_must_NOT_say_where_it_is_answerable(
        self, manifest: Manifest, tmp_path: Path
    ) -> None:
        path = write(tmp_path, {"version": 1, "refusals": [entry(kind="out-of-corpus")]})
        with pytest.raises(GoldenSetError, match="must not name answerable_from"):
            load_golden_set(path, manifest)

    def test_an_answer_in_the_SAME_authority_is_not_out_of_jurisdiction(
        self, manifest: Manifest, tmp_path: Path
    ) -> None:
        """The whole category is 'asked with the wrong authority's filter'."""
        path = write(
            tmp_path,
            {"version": 1, "refusals": [entry(answerable_from="pirkanmaa@2021-07-01#19")]},
        )
        with pytest.raises(GoldenSetError, match="the very authority"):
            load_golden_set(path, manifest)

    def test_the_absorbed_pirkanmaa_clause_is_refused_as_a_target(
        self, manifest: Manifest, tmp_path: Path
    ) -> None:
        path = write(
            tmp_path,
            {
                "version": 1,
                "refusals": [
                    entry(municipality="Turku", answerable_from="pirkanmaa@2021-07-01#18")
                ],
            },
        )
        with pytest.raises(GoldenSetError, match="18"):
            load_golden_set(path, manifest)

    def test_an_empty_absent_lexeme_is_refused(self, manifest: Manifest, tmp_path: Path) -> None:
        path = write(tmp_path, {"version": 1, "refusals": [entry(absent_lexeme="   ")]})
        with pytest.raises(GoldenSetError, match="no drift detector"):
            load_golden_set(path, manifest)

    def test_an_unknown_kind_is_refused(self, manifest: Manifest, tmp_path: Path) -> None:
        path = write(tmp_path, {"version": 1, "refusals": [entry(kind="out-of-scope")]})
        with pytest.raises(GoldenSetError, match="kind must be one of"):
            load_golden_set(path, manifest)

    def test_a_partially_covered_municipality_still_refuses_here(
        self, manifest: Manifest, tmp_path: Path
    ) -> None:
        """Sastamala raises for a refusal question exactly as for an answerable one."""
        path = write(tmp_path, {"version": 1, "refusals": [entry(municipality="Sastamala")]})
        with pytest.raises(ManifestError, match="covered only in part"):
            load_golden_set(path, manifest)

    def test_a_file_with_neither_key_is_refused_rather_than_read_as_empty(
        self, manifest: Manifest, tmp_path: Path
    ) -> None:
        path = write(tmp_path, {"version": 1, "refusalz": [entry()]})
        with pytest.raises(GoldenSetError, match="non-empty 'questions' or"):
            load_golden_set(path, manifest)

    def test_an_id_shared_with_the_answerable_population_is_refused(
        self, manifest: Manifest, tmp_path: Path
    ) -> None:
        (tmp_path / "refusals.yaml").write_text(
            yaml.safe_dump({"version": 1, "refusals": [entry(id="clash")]}, allow_unicode=True),
            encoding="utf-8",
        )
        (tmp_path / "answerable.yaml").write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "questions": [
                        {
                            "id": "clash",
                            "question": "Milloin biojäte kerätään?",
                            "phrasing": "authored",
                            "municipality": "Turku",
                            "required_chunks": ["lounais-suomi@2024-08-01#15"],
                            "label_source": "15 §",
                        }
                    ],
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        with pytest.raises(GoldenSetError, match="duplicate question ids"):
            load_golden_set(tmp_path, manifest)

    def test_one_text_cannot_be_both_answerable_and_a_refusal(
        self, manifest: Manifest, tmp_path: Path
    ) -> None:
        shared = "Milloin biojäte kerätään?"
        (tmp_path / "a-refusals.yaml").write_text(
            yaml.safe_dump(
                {"version": 1, "refusals": [entry(question=shared)]}, allow_unicode=True
            ),
            encoding="utf-8",
        )
        (tmp_path / "b-answerable.yaml").write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "questions": [
                        {
                            "id": "answerable-one",
                            "question": shared,
                            "phrasing": "authored",
                            "municipality": "Turku",
                            "required_chunks": ["lounais-suomi@2024-08-01#15"],
                            "label_source": "15 §",
                        }
                    ],
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        with pytest.raises(GoldenSetError, match="BOTH populations"):
            load_golden_set(tmp_path, manifest)

    def test_the_provenance_rules_apply_to_refusals_too(
        self, manifest: Manifest, tmp_path: Path
    ) -> None:
        path = write(
            tmp_path,
            {"version": 1, "refusals": [entry(phrasing="harvested")]},
        )
        with pytest.raises(GoldenSetError, match="phrasing_source must name that page"):
            load_golden_set(path, manifest)


class TestPopulationsCannotBePooled:
    """AC8. The separation is a type, and it is also checked at runtime."""

    def outcome(self) -> QuestionOutcome:
        return QuestionOutcome(
            question_id="answerable",
            required=("lounais-suomi@2024-08-01#15",),
            retrieved=("lounais-suomi@2024-08-01#15",),
            misses=(),
        )

    def test_retrieval_metrics_reject_a_refusal_outcome(self) -> None:
        refusal = RefusalOutcome(
            question_id="ooc-one", kind=MetricsRefusalKind.OUT_OF_CORPUS, refused=True
        )
        with pytest.raises(MetricsError, match="refusing to compute retrieval metrics"):
            compute([self.outcome(), refusal], k=5)  # type: ignore[list-item]

    def test_refusal_metrics_reject_a_retrieval_outcome(self) -> None:
        with pytest.raises(MetricsError, match="refusing to pool populations"):
            refusal_metrics(
                refusals=[self.outcome()],  # type: ignore[list-item]
                answerable=[AnswerOutcome(question_id="a", refused=False)],
            )

    def test_a_question_with_no_required_chunks_still_cannot_be_constructed(self) -> None:
        """The original guard, unchanged: this is why refusals needed a new type."""
        with pytest.raises(MetricsError, match="no required chunks"):
            QuestionOutcome(question_id="x", required=(), retrieved=(), misses=())

    def test_refusal_precision_refuses_to_be_computed_without_the_other_population(
        self,
    ) -> None:
        with pytest.raises(MetricsError, match="needs the answerable population"):
            refusal_metrics(
                refusals=[
                    RefusalOutcome(
                        question_id="ooc-one",
                        kind=MetricsRefusalKind.OUT_OF_CORPUS,
                        refused=True,
                    )
                ],
                answerable=[],
            )

    def test_an_id_in_both_populations_is_refused(self) -> None:
        with pytest.raises(MetricsError, match="both populations"):
            refusal_metrics(
                refusals=[
                    RefusalOutcome(
                        question_id="same", kind=MetricsRefusalKind.OUT_OF_CORPUS, refused=True
                    )
                ],
                answerable=[AnswerOutcome(question_id="same", refused=False)],
            )

    def test_the_two_refusal_kind_vocabularies_are_identical(self) -> None:
        """`metrics` deliberately does not import `golden`; this pins them equal."""
        assert {k.value for k in RefusalKind} == {k.value for k in MetricsRefusalKind}


class TestRefusalArithmetic:
    def population(
        self, refused: dict[str, bool], kinds: dict[str, MetricsRefusalKind] | None = None
    ) -> list[RefusalOutcome]:
        kinds = kinds or {}
        return [
            RefusalOutcome(
                question_id=qid,
                kind=kinds.get(qid, MetricsRefusalKind.OUT_OF_CORPUS),
                refused=value,
            )
            for qid, value in refused.items()
        ]

    def test_recall_is_correct_refusals_over_the_refusal_population(self) -> None:
        metrics = refusal_metrics(
            refusals=self.population({"r1": True, "r2": True, "r3": False, "r4": False}),
            answerable=[AnswerOutcome(question_id="a1", refused=False)],
        )
        assert metrics.recall.point == 0.5
        assert metrics.recall.n == 4
        assert metrics.missed == ("r3", "r4")

    def test_precision_counts_the_refusals_emitted_over_ANSWERABLE_questions(self) -> None:
        """The metric that punishes refusing everything."""
        metrics = refusal_metrics(
            refusals=self.population({"r1": True, "r2": True}),
            answerable=[
                AnswerOutcome(question_id="a1", refused=True),
                AnswerOutcome(question_id="a2", refused=True),
                AnswerOutcome(question_id="a3", refused=False),
            ],
        )
        assert metrics.recall.point == 1.0
        assert metrics.precision.point == 0.5  # 2 correct of 4 emitted
        assert metrics.wrongly_refused == ("a1", "a2")

    def test_an_answerer_that_never_refuses_has_no_precision_rather_than_zero(self) -> None:
        """0/0 reported as 0.0 would read as 'every refusal it emitted was wrong'."""
        metrics = refusal_metrics(
            refusals=self.population({"r1": False}),
            answerable=[AnswerOutcome(question_id="a1", refused=False)],
        )
        assert metrics.recall.point == 0.0
        assert metrics.precision.n == 0

    def test_the_two_kinds_are_scored_apart(self) -> None:
        """Prediction 3 is a comparison between these two rows."""
        metrics = refusal_metrics(
            refusals=self.population(
                {"c1": True, "c2": True, "j1": False, "j2": False},
                {
                    "j1": MetricsRefusalKind.OUT_OF_JURISDICTION,
                    "j2": MetricsRefusalKind.OUT_OF_JURISDICTION,
                },
            ),
            answerable=[AnswerOutcome(question_id="a1", refused=False)],
        )
        by_kind = dict(metrics.by_kind)
        assert by_kind[MetricsRefusalKind.OUT_OF_CORPUS].point == 1.0
        assert by_kind[MetricsRefusalKind.OUT_OF_JURISDICTION].point == 0.0

    def test_citing_the_retrieved_context_is_a_diagnostic_and_not_a_defect(self) -> None:
        """ADR-0010 narrowed the rule. This pins the half that was measured wrong.

        Tracer slice 3 found two refusals citing a chunk they were given, both to
        say what the excerpts DO cover. Under `CONTEXT.md:40` those are correct
        citations, so counting them as defects punished the more auditable answer.
        """
        metrics = refusal_metrics(
            refusals=[
                RefusalOutcome(
                    question_id="r1",
                    kind=MetricsRefusalKind.OUT_OF_CORPUS,
                    refused=True,
                    citations=("lounais-suomi@2024-08-01#15",),
                    retrieved=("lounais-suomi@2024-08-01#15", "lounais-suomi@2024-08-01#16"),
                ),
                RefusalOutcome(
                    question_id="r2", kind=MetricsRefusalKind.OUT_OF_CORPUS, refused=True
                ),
            ],
            answerable=[AnswerOutcome(question_id="a1", refused=False)],
        )
        assert metrics.refusals_citing_context == ("r1",)
        assert metrics.refusals_citing_outside == ()

    def test_citing_outside_the_retrieved_set_is_still_a_defect(self) -> None:
        """The half of the old rule that was always unambiguous.

        A refusal says the retrieved context does not answer the question. An
        address from outside that context contradicts the refusal itself, whether
        it was hallucinated or belongs to the authority the question was not asked
        about.
        """
        metrics = refusal_metrics(
            refusals=[
                RefusalOutcome(
                    question_id="r1",
                    kind=MetricsRefusalKind.OUT_OF_JURISDICTION,
                    refused=True,
                    citations=("pirkanmaa@2021-07-01#7",),
                    retrieved=("lounais-suomi@2024-08-01#15",),
                ),
            ],
            answerable=[AnswerOutcome(question_id="a1", refused=False)],
        )
        assert metrics.refusals_citing_outside == ("r1",)
        assert metrics.refusals_citing_context == ()

    def test_a_refusal_can_be_both_at_once_and_is_named_in_both(self) -> None:
        """One citation inside the context and one outside it is two findings."""
        metrics = refusal_metrics(
            refusals=[
                RefusalOutcome(
                    question_id="r1",
                    kind=MetricsRefusalKind.OUT_OF_CORPUS,
                    refused=True,
                    citations=("lounais-suomi@2024-08-01#15", "pirkanmaa@2021-07-01#7"),
                    retrieved=("lounais-suomi@2024-08-01#15",),
                ),
            ],
            answerable=[AnswerOutcome(question_id="a1", refused=False)],
        )
        assert metrics.refusals_citing_context == ("r1",)
        assert metrics.refusals_citing_outside == ("r1",)


class TestWilson:
    def test_a_perfect_score_does_not_report_certainty(self) -> None:
        """Wald would give [1.0, 1.0] here, which 14 questions cannot buy."""
        interval = wilson(14, 14)
        assert interval.point == 1.0
        assert interval.low < 0.8
        assert interval.high == 1.0

    def test_the_interval_at_R_equals_14_is_far_wider_than_the_spec_quoted(self) -> None:
        """D5 says +/-0.13. That is one standard error, not a 95% interval."""
        interval = wilson(7, 14)
        assert interval.high - interval.low > 0.4
        assert 0.2 < interval.low < 0.3
        assert 0.7 < interval.high < 0.8

    def test_it_never_runs_past_zero_or_one(self) -> None:
        for successes in range(15):
            interval = wilson(successes, 14)
            assert 0.0 <= interval.low <= interval.high <= 1.0

    def test_a_proportion_that_is_not_one_is_refused(self) -> None:
        with pytest.raises(MetricsError, match="is not a proportion"):
            wilson(15, 14)
        with pytest.raises(MetricsError, match="zero observations"):
            wilson(0, 0)


class TestNoMunicipalityIsEverDefaulted:
    """AC14's unit half. The live half is `answer <id> --municipality ''`."""

    def test_an_empty_municipality_refuses_rather_than_picking_one(
        self, manifest: Manifest
    ) -> None:
        with pytest.raises(ManifestError, match="no municipality was given"):
            manifest.resolve_municipality("")

    def test_whitespace_is_not_a_municipality_either(self, manifest: Manifest) -> None:
        with pytest.raises(ManifestError, match="no municipality was given"):
            manifest.resolve_municipality("   ")

    def test_an_unknown_municipality_is_still_a_different_error(self, manifest: Manifest) -> None:
        """So 'you gave nothing' and 'we do not cover that' stay distinguishable."""
        with pytest.raises(ManifestError, match="no authority in the manifest covers"):
            manifest.resolve_municipality("Kuopio")


class TestTheTokenCeilingIsDerived:
    def test_a_single_call_keeps_D8s_floor(self) -> None:
        assert ceiling_for(1) == TOKEN_CEILING

    def test_a_full_run_gets_a_ceiling_a_full_run_cannot_trip(self) -> None:
        """D8's constant could not survive this: 64 x ~10,900 is already ~700K."""
        ceiling = ceiling_for(64)
        assert ceiling > 64 * 10_900
        assert ceiling > TOKEN_CEILING

    def test_the_ceiling_scales_with_the_run_rather_than_being_revised(self) -> None:
        assert ceiling_for(200) > ceiling_for(100) > ceiling_for(64)

    def test_a_run_of_no_calls_is_refused(self) -> None:
        with pytest.raises(AnswerError):
            ceiling_for(0)

    def test_for_run_builds_a_budget_at_that_ceiling(self) -> None:
        assert TokenBudget.for_run(64).ceiling == ceiling_for(64)


class TestAgainstTheCorpus:
    """The checks that need the real documents. These are the load-bearing ones."""

    def test_every_committed_refusal_claim_still_holds(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        golden: GoldenSet,
    ) -> None:
        assert_refusal_absences(corpus, manifest=manifest, refusals=golden.refusals)

    def test_the_absence_check_goes_RED_when_the_topic_is_covered(
        self, corpus: psycopg.Connection[tuple[object, ...]], manifest: Manifest
    ) -> None:
        """Seen red on purpose: `kompostointi` is regulated at length in Pirkanmaa."""
        covered = RefusalQuestion(
            id="pretend-absent",
            question="Miten kompostoidaan?",
            kind=RefusalKind.OUT_OF_CORPUS,
            phrasing=Phrasing.AUTHORED,
            phrasing_source=None,
            municipality="Tampere",
            absent_lexeme="kompostointi",
            absence_source="a claim this test exists to falsify",
            answerable_from=None,
            label_source="none",
        )
        with pytest.raises(EvaluationError, match="is NOT absent from"):
            assert_refusal_absences(corpus, manifest=manifest, refusals=[covered])

    def test_the_lemma_check_catches_what_the_SUBSTRING_check_provably_cannot(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        morphology: Morphology,
    ) -> None:
        """The tyre case, kept as a permanent red.

        `ooc-autonrenkaiden-vastaanotto` shipped for two slices claiming the word
        `rengas` appears in neither authority "missään muodossa". Both 2 §
        definitions enumerate `renkaat`. The substring detector could not see it --
        Finnish consonant gradation means `rengas` is not a substring of `renkaat`
        -- and the answerer was scored as having missed a refusal for giving the
        right answer.

        The first two assertions are the *diagnosis*, not decoration: if the
        substring check ever starts finding it, this test is passing for a
        different reason than the one it was written for.
        """
        assert db.chunks_containing(corpus, authority_key="lounais-suomi", needle="rengas") == []
        assert db.chunks_containing(corpus, authority_key="pirkanmaa", needle="rengas") == []

        tyre = RefusalQuestion(
            id="pretend-tyres-are-absent",
            question="Mihin vanhat autonrenkaat pitää toimittaa?",
            kind=RefusalKind.OUT_OF_CORPUS,
            phrasing=Phrasing.AUTHORED,
            phrasing_source=None,
            municipality="Salo",
            absent_lexeme="rengas",
            absence_source="the claim this test exists to falsify",
            answerable_from=None,
            label_source="none",
        )
        with pytest.raises(EvaluationError, match="is NOT absent from"):
            assert_refusal_absences(
                corpus, manifest=manifest, refusals=[tyre], morphology=morphology
            )

    def test_a_multi_word_needle_needs_ADJACENCY_and_not_merely_both_words(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        golden: GoldenSet,
        morphology: Morphology,
    ) -> None:
        """`toissijainen jatehuoltopalvelu` is a phrase needle for exactly this reason.

        Lounais-Suomi 1 SS carries `toissijaiselle jatehuoltovastuulle kuuluviin
        jatehuoltopalveluihin`: both lemmas, in one chunk, three tokens apart. A
        bag-of-lemmas absence check would fire on it and go red for an entry whose
        label is sound and whose author had already anticipated this.
        """
        entry = next(
            r for r in golden.refusals if r.absent_lexeme == "toissijainen jätehuoltopalvelu"
        )
        both_words_present = db.chunks_matching_lemmas(
            corpus,
            authority_key="lounais-suomi",
            tsquery="'toissijainen' & 'jätehuoltopalvelu'",
            analyser=ABSENCE_ANALYSER,
        )
        assert both_words_present, "the premise of this test has changed"
        assert_refusal_absences(corpus, manifest=manifest, refusals=[entry], morphology=morphology)

    def test_the_absence_analyser_does_not_decompose_compounds(
        self, morphology: Morphology
    ) -> None:
        """Why the detector is not on the published cell's analyser.

        `lemma-reasm` reads `lisajate` as `lisa` + `jate` as well as whole, and
        `jate` is in almost every chunk of a waste corpus -- so a reassembling
        absence check would go red on every compound needle in the population.
        """
        assert morphology.lexemes("lisäjäte", ABSENCE_ANALYSER) == ("lisäjäte",)
        assert "jäte" in morphology.lexemes("lisäjäte", Analyser.LEMMA_REASM)
        assert morphology.lexemes("renkaat", ABSENCE_ANALYSER) == ("rengas",)

    def test_an_out_of_jurisdiction_claim_goes_RED_when_the_answer_is_not_there_either(
        self, corpus: psycopg.Connection[tuple[object, ...]], manifest: Manifest
    ) -> None:
        """The other side of the two-sided check: the entry has gone vacuous.

        A one-sided check passes just as happily when the foreign clause is the
        thing that disappeared, and that failure would leave six questions in the
        population measuring nothing while the run stayed green.
        """
        vacuous = RefusalQuestion(
            id="pretend-elsewhere",
            question="Mitä sanoo lentojätepykälä?",
            kind=RefusalKind.OUT_OF_JURISDICTION,
            phrasing=Phrasing.AUTHORED,
            phrasing_source=None,
            municipality="Tampere",
            # Absent from Pirkanmaa, as an out-of-jurisdiction entry requires --
            # and absent from Lounais-Suomi too, which is the defect.
            absent_lexeme="lentojäte",
            absence_source="a claim this test exists to falsify",
            answerable_from=ChunkAddress.parse("lounais-suomi@2024-08-01#19"),
            label_source="none",
        )
        with pytest.raises(EvaluationError, match="ALSO absent from"):
            assert_refusal_absences(corpus, manifest=manifest, refusals=[vacuous])

    def test_an_unresolvable_answerable_from_fails_the_run(
        self, corpus: psycopg.Connection[tuple[object, ...]], manifest: Manifest
    ) -> None:
        ghost = RefusalQuestion(
            id="ghost",
            question="Saanko asentaa jätemyllyn?",
            kind=RefusalKind.OUT_OF_JURISDICTION,
            phrasing=Phrasing.AUTHORED,
            phrasing_source=None,
            municipality="Tampere",
            absent_lexeme="jätemylly",
            absence_source="none",
            answerable_from=ChunkAddress.parse("lounais-suomi@2024-08-01#999"),
            label_source="none",
        )
        with pytest.raises(EvaluationError, match="not in the corpus"):
            assert_refusal_absences(corpus, manifest=manifest, refusals=[ghost])

    def test_refusal_retrieval_obeys_the_authority_filter_like_everything_else(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        golden: GoldenSet,
        morphology: Morphology,
    ) -> None:
        stopwords = question_stopwords(corpus, golden, morphology)
        retrieved = retrieve_refusals(
            corpus,
            manifest=manifest,
            refusals=golden.refusals,
            k=5,
            cell=PUBLISHED,
            morphology=morphology,
            stopwords=stopwords,
        )
        assert len(retrieved) == 13
        for one in retrieved:
            assert one.hits, one.refusal.id
            assert {hit.authority_key for hit in one.hits} == {one.authority_key}

    def test_an_out_of_jurisdiction_question_retrieves_plausible_chunks_anyway(
        self,
        corpus: psycopg.Connection[tuple[object, ...]],
        manifest: Manifest,
        golden: GoldenSet,
        morphology: Morphology,
    ) -> None:
        """This is what makes the hard kind hard, and it is worth asserting.

        If these questions retrieved nothing, refusing them would measure the
        tokeniser rather than the answerer, and prediction 3 would be untestable.
        """
        stopwords = question_stopwords(corpus, golden, morphology)
        retrieved = retrieve_refusals(
            corpus,
            manifest=manifest,
            refusals=out_of_jurisdiction(golden),
            k=5,
            cell=PUBLISHED,
            morphology=morphology,
            stopwords=stopwords,
        )
        for one in retrieved:
            assert len(one.hits) == 5, f"{one.refusal.id} retrieved {len(one.hits)}"


def test_the_committed_file_declares_every_entry_authored() -> None:
    """Read from the YAML, not the parsed object: this is a claim about the file."""
    document = yaml.safe_load(REFUSALS.read_text(encoding="utf-8"))
    assert {r["phrasing"] for r in document["refusals"]} == {"authored"}
    assert all("phrasing_source" not in r for r in document["refusals"])


class TestTheCommandRefusesSilentlyIgnoredFlags:
    """A flag dropped on the floor reads as a run the operator configured and did not get."""

    def test_all_and_a_question_id_together_are_refused(self) -> None:
        assert main(["answer", "--all", "pir-mika-on-kimppa"]) == 1

    def test_municipality_cannot_be_combined_with_all(self) -> None:
        assert main(["answer", "--all", "--municipality", "Turku"]) == 1

    def test_out_without_all_is_refused(self, tmp_path: Path) -> None:
        assert main(["answer", "x", "--out", str(tmp_path / "run.json")]) == 1
        assert not (tmp_path / "run.json").exists()

    def test_neither_a_question_nor_all_is_refused(self) -> None:
        assert main(["answer"]) == 1


def synthetic_run(**overrides: object) -> AnswerRun:
    """An AnswerRun assembled without a model call, for the formatters."""

    def scored(qid: str, refused: bool, text: str, citations: tuple[str, ...] = ()) -> ScoredAnswer:
        return ScoredAnswer(
            question_id=qid,
            question="Saanko asentaa jätemyllyn?",
            municipality="Tampere",
            authority_key="pirkanmaa",
            retrieved=("pirkanmaa@2021-07-01#19",),
            answer=Answer(
                question_id=qid,
                model="qwen/qwen3.6-27b",
                refused=refused,
                text=text,
                citations=citations,
                usage=Usage(
                    prompt_tokens=1,
                    completion_tokens=1,
                    reasoning_tokens=0,
                    total_tokens=2,
                    cost_usd=0.01,
                ),
                finish_reason="stop",
            ),
        )

    refusals = (
        scored("ooj-one", True, "Näissä määräyksissä ei ole tästä säännöstä."),
        scored("ooc-one", False, "Vastaus on kerran vuodessa.", ("pirkanmaa@2021-07-01#19",)),
    )
    kinds = {
        "ooj-one": RefusalKind.OUT_OF_JURISDICTION,
        "ooc-one": RefusalKind.OUT_OF_CORPUS,
    }
    answerable = (scored("a-one", False, "Kyllä."), scored("a-two", True, "En osaa sanoa."))
    base: dict[str, object] = {
        "cell": PUBLISHED,
        "k": 5,
        "model": "qwen/qwen3.6-27b",
        "reasoning": True,
        "answerable": answerable,
        "refusals": refusals,
        "refusal_kinds": kinds,
        "metrics": refusal_metrics(
            refusals=[
                RefusalOutcome(
                    question_id=one.question_id,
                    kind=MetricsRefusalKind(kinds[one.question_id].value),
                    refused=one.answer.refused,
                    citations=one.answer.citations,
                )
                for one in refusals
            ],
            answerable=[
                AnswerOutcome(question_id=one.question_id, refused=one.answer.refused)
                for one in answerable
            ],
        ),
        "tokens": 100,
        "cost_usd": 1.23,
        "ceiling": 1_000_000,
        "json_validation_retries": 0,
    }
    base.update(overrides)
    return AnswerRun(**base)  # type: ignore[arg-type]


class TestTheRefusalReport:
    """The formatters run after an hour of paid work, so they are tested before it."""

    def test_it_prints_recall_precision_and_both_kinds_with_intervals(self) -> None:
        out = format_refusals(synthetic_run())
        assert "recall" in out and "precision" in out
        assert "out-of-corpus" in out and "out-of-jurisdiction" in out
        assert "n=2" in out  # every proportion carries the n it was computed over

    def test_it_names_the_questions_that_went_wrong_rather_than_only_counting_them(
        self,
    ) -> None:
        out = format_refusals(synthetic_run())
        assert "ooc-one" in out  # answered when it should have refused
        assert "a-two" in out  # refused when it should have answered

    def test_it_says_the_quoted_interval_is_not_the_spec_figure(self) -> None:
        """The project has been burned once by publishing the wrong statistic."""
        assert "standard error" in format_refusals(synthetic_run())

    def test_a_refusal_carrying_a_citation_is_called_a_defect_in_the_output(self) -> None:
        cited = RefusalOutcome(
            question_id="ooj-one",
            kind=MetricsRefusalKind.OUT_OF_JURISDICTION,
            refused=True,
            citations=("pirkanmaa@2021-07-01#19",),
        )
        metrics = refusal_metrics(
            refusals=[cited],
            answerable=[AnswerOutcome(question_id="a-one", refused=False)],
        )
        assert "DEFECT" in format_refusals(synthetic_run(metrics=metrics))

    def test_the_retry_count_is_surfaced_when_there_was_one(self) -> None:
        assert "invalid JSON" in format_refusals(synthetic_run(json_validation_retries=2))
        assert "invalid JSON" not in format_refusals(synthetic_run())

    def test_the_detail_view_prints_every_refusal_question_and_its_answer(self) -> None:
        out = format_refusal_detail(synthetic_run())
        assert "REFUSED" in out and "ANSWERED (miss)" in out
        assert "Näissä määräyksissä" in out
        assert "[out-of-jurisdiction]" in out

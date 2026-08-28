"""The command-line surface: ``ingest``, ``eval``, ``answer``, ``judge``, ``label``
and ``agreement``.

Exit codes are a feature, not an afterthought -- CI reads them. Zero means the
run completed and every metric held. Anything else means the table on stdout,
if there is one, must not be trusted.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from fi_rag_eval import answering, db, judging, labelling
from fi_rag_eval.analyse import AnalyserError, Morphology
from fi_rag_eval.answer import (
    ANSWERER,
    JUDGE,
    AnswerError,
    TokenBudget,
    answer_question,
)
from fi_rag_eval.chunking import ChunkingError
from fi_rag_eval.evaluate import (
    DEFAULT_K,
    PUBLISHED,
    EvaluationError,
    evaluate,
    evaluate_grid,
)
from fi_rag_eval.extract import ExtractionError
from fi_rag_eval.golden import GoldenSetError, load_golden_set
from fi_rag_eval.ingest import IngestError, ingest
from fi_rag_eval.judge import judge_ceiling_for
from fi_rag_eval.judging import DEFAULT_CONTROL, JudgingError, load_control, load_run
from fi_rag_eval.labelling import (
    DEFAULT_LABELS,
    DEFAULT_SAMPLE,
    LabellingError,
    human_unit_labels,
    judge_unit_labels,
    load_labels,
    questions_to_label,
)
from fi_rag_eval.manifest import ManifestError, load_manifest
from fi_rag_eval.metrics import MetricsError, unit_agreement
from fi_rag_eval.report import (
    Baseline,
    BaselineError,
    compare,
    format_address_validity,
    format_agreement,
    format_control,
    format_grid,
    format_ingest,
    format_judged,
    format_judged_detail,
    format_probe_table,
    format_refusal_detail,
    format_refusals,
    git_commit,
)

DEFAULT_MANIFEST = Path("corpus/manifest.yaml")
DEFAULT_GOLDEN = Path("corpus/golden")
"""A directory: one file per authority, pooled into one set (slice 4, D11)."""
DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_BASELINE = Path("eval/baseline.json")

HANDLED = (
    AnswerError,
    JudgingError,
    LabellingError,
    ManifestError,
    GoldenSetError,
    ExtractionError,
    ChunkingError,
    IngestError,
    EvaluationError,
    MetricsError,
    BaselineError,
    AnalyserError,
    db.DatabaseError,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fi-rag-eval",
        description="Evaluation harness for Finnish waste-regulation retrieval.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser(
        "ingest", help="fetch, chunk and load the corpus described by the manifest"
    )
    ingest_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ingest_parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)

    eval_parser = subparsers.add_parser(
        "eval", help="score the golden set and print the metric table"
    )
    eval_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    eval_parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    eval_parser.add_argument("--k", type=int, default=DEFAULT_K)
    eval_parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help="recorded run to gate against; a missing file is reported, not tolerated",
    )
    eval_parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="record this run as the baseline instead of gating against it",
    )
    eval_parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="print the table without gating (for exploring, never for CI)",
    )
    answer_parser = subparsers.add_parser(
        "answer",
        help="answer ONE golden question from the published cell's retrieval -- or, "
        "with --all, both populations with refusal precision/recall. Prints what it cost",
    )
    answer_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    answer_parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    answer_parser.add_argument("--k", type=int, default=DEFAULT_K)
    answer_parser.add_argument(
        "question_id",
        nargs="?",
        help="which golden question to answer; an unknown id lists the ones that exist",
    )
    answer_parser.add_argument(
        "--all",
        action="store_true",
        help="answer BOTH populations -- 50 answerable and 14 refusal questions -- and "
        "print refusal precision/recall. This spends real money: budget the measured "
        "per-answer cost times 64",
    )
    answer_parser.add_argument(
        "--municipality",
        default=None,
        help="ask the question as a resident of this kunta instead of the one the "
        "golden entry names. Pass an empty string to exercise the no-municipality "
        "refusal, which must never silently pick an authority",
    )
    answer_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the whole run -- every answer text, verbatim -- to this JSON file. "
        "The hand-labelled agreement sample is frozen from a file like this one, and a "
        "sample regenerated from a later model is not the sample that was labelled. "
        "Run artifacts belong under eval/runs/, which is gitignored; the frozen sample "
        "is a deliberate copy, not whatever the last run happened to write",
    )
    answer_parser.add_argument(
        "--model",
        default=ANSWERER,
        help=f"the model under test (default: {ANSWERER})",
    )
    answer_parser.add_argument(
        "--no-reasoning",
        action="store_true",
        help="turn the model's reasoning off. Tracer slice 1 found refusal behaviour "
        "depends on it, which is pre-registered as prediction 7 -- so this is a knob "
        "the measurement needs, not a performance option",
    )
    answer_parser.add_argument(
        "--token-ceiling",
        type=int,
        default=None,
        help="override the run's token ceiling. Exists so the ceiling can be watched "
        "failing, which is the only thing that makes it a gate",
    )

    judge_parser = subparsers.add_parser(
        "judge",
        help="score a frozen answer run's every claim with the judge -- or, with "
        "--control, run the 8/8 known-bad control. Prints what it cost",
    )
    judge_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    judge_parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    judge_parser.add_argument(
        "run",
        nargs="?",
        type=Path,
        help="the answer run to judge, as written by `answer --all --out`. The judge "
        "never generates the answers it scores (ADR-0010): a judge prompt is developed "
        "by iteration, and iteration needs an input that cannot move underneath it",
    )
    judge_parser.add_argument(
        "--control",
        action="store_true",
        help="run the known-bad control instead: 8 hand-authored bad answers the judge "
        "must all catch. Needs no run file and is reproducible from a clean clone. "
        "Exits non-zero below 8/8",
    )
    judge_parser.add_argument(
        "--control-file",
        type=Path,
        default=DEFAULT_CONTROL,
        help=f"where the control cases live (default: {DEFAULT_CONTROL})",
    )
    judge_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="judge only the first N answers. Exists so ONE judge call can be bought "
        "and measured before the batch -- prediction 6 came in at 11x, so the judge's "
        "cost is measured rather than predicted. A limited run is NEVER a result: the "
        "table says so and no metric from it may be quoted",
    )
    judge_parser.add_argument(
        "--weak-prompt",
        action="store_true",
        help="use the deliberately credulous judge prompt. This is how the control is "
        "watched failing (AC10), which is the only thing that makes it a gate",
    )
    judge_parser.add_argument(
        "--stub-agreement",
        type=float,
        default=None,
        help="pretend judge-human agreement is this value. Exists so D11's withholding "
        "rule can be watched changing the table (AC12); real agreement is tracer slice "
        "5's and does not exist yet",
    )
    judge_parser.add_argument(
        "--model",
        default=JUDGE,
        help=f"the judge (default: {JUDGE}). A different model FAMILY than the answerer, "
        "by CONTEXT.md:66",
    )
    judge_parser.add_argument(
        "--token-ceiling",
        type=int,
        default=None,
        help="override the run's token ceiling, so the ceiling can be watched failing",
    )
    judge_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write every unit verdict to this JSON file. Tracer slice 5 compares hand "
        "labels against a file like this one, and two of these files compare the judge "
        "against ITSELF -- which is what puts a ceiling on the agreement it can reach",
    )
    judge_parser.add_argument(
        "--detail",
        action="store_true",
        help="also print every judged answer unit by unit, with the judge's own quote. "
        "This is the view tracer slice 5's hand labelling is done against",
    )

    label_parser = subparsers.add_parser(
        "label",
        help="hand-label the frozen sample's claims, one unit at a time. BLIND: it shows "
        "you nothing the judge produced (ADR-0011). Resumable -- run it again to continue",
    )
    label_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    label_parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    label_parser.add_argument(
        "--sample",
        type=Path,
        default=DEFAULT_SAMPLE,
        help=f"the frozen answer texts to label against (default: {DEFAULT_SAMPLE}). "
        "Committed on purpose: a sample regenerated from a later model is not the sample "
        "that was labelled",
    )
    label_parser.add_argument(
        "--labels",
        type=Path,
        default=DEFAULT_LABELS,
        help=f"where your labels are written, after every single unit (default: {DEFAULT_LABELS})",
    )

    agreement_parser = subparsers.add_parser(
        "agreement",
        help="compute judge-human agreement over the hand-labelled units, with a "
        "cluster-aware interval, and apply D11's publishability floor",
    )
    agreement_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    agreement_parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    agreement_parser.add_argument(
        "verdicts",
        type=Path,
        help="a judge verdict file, as written by `judge --out`",
    )
    agreement_parser.add_argument(
        "--against",
        type=Path,
        default=None,
        help="a SECOND judge verdict file. Given one, this reports judge SELF-consistency "
        "instead -- the ceiling on any agreement figure, since two judge runs that differ "
        "cannot both match a human",
    )
    agreement_parser.add_argument(
        "--sample", type=Path, default=DEFAULT_SAMPLE, help=f"default: {DEFAULT_SAMPLE}"
    )
    agreement_parser.add_argument(
        "--labels", type=Path, default=DEFAULT_LABELS, help=f"default: {DEFAULT_LABELS}"
    )
    agreement_parser.add_argument(
        "--partial",
        action="store_true",
        help="compute over the units labelled SO FAR instead of refusing. A progress "
        "check, never a result: the output says so and no number from it may be quoted",
    )

    eval_parser.add_argument(
        "--probe",
        action="store_true",
        help="also print what the analyser does to every probe word, so a changed "
        "fingerprint can be diagnosed rather than merely detected",
    )
    return parser


def _ingest(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    with db.connect() as conn:
        report = ingest(conn, manifest, args.raw_dir)
    print(format_ingest(report))
    print(f"ingest: {report.chunks} chunks loaded")
    return 0


def _eval(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    golden = load_golden_set(args.golden, manifest)
    morphology = Morphology.open()
    with db.connect() as conn:
        summary = db.corpus_summary(conn)
        if not summary:
            raise EvaluationError(
                "the corpus is empty. Run `make ingest` first -- an eval over an "
                "empty corpus would score zero and blame retrieval for it."
            )
        # The lemma columns are written by the ingest, not generated by Postgres,
        # so an eval against a corpus loaded by an older ingest would score the
        # lemma cells against an empty index and call it a retrieval failure.
        db.assert_lemma_vectors_populated(conn)
        lexemes = db.lexeme_counts(conn)
        grid = evaluate_grid(
            conn, manifest=manifest, golden=golden, k=args.k, morphology=morphology
        )

    commit = git_commit()
    print(format_grid(grid, commit=commit, lexemes=lexemes))
    if args.probe:
        print()
        print(format_probe_table(grid, morphology.probe_table()))

    if args.write_baseline:
        baseline = Baseline.from_grid(grid, commit)
        baseline.write(args.baseline)
        print(f"\nbaseline recorded at {args.baseline} (commit {commit})")
        return 0

    if args.no_baseline:
        print("\nno regression gate applied (--no-baseline)")
        return 0

    if not args.baseline.is_file():
        print(
            f"\nno baseline at {args.baseline}: nothing to gate against. Record one "
            "with `--write-baseline` once you believe the number.",
            file=sys.stderr,
        )
        return 1

    problems = compare(Baseline.load(args.baseline), grid)
    if problems:
        print("\nREGRESSION — this run does not meet the recorded baseline:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"\ngate: green against {args.baseline}")
    return 0


def _answer(args: argparse.Namespace) -> int:
    # Flags are rejected in the mode that would ignore them rather than accepted and
    # dropped. A silently ignored flag on a command that spends money reads to the
    # operator as a run they configured and did not get.
    if args.all:
        if args.question_id:
            raise AnswerError(
                f"--all answers every question, so it cannot also be given "
                f"{args.question_id!r}. Drop one."
            )
        if args.municipality is not None:
            raise AnswerError(
                "--municipality cannot be combined with --all: every question carries the "
                "kunta it is labelled against, and overriding all 64 at once would ask "
                "each of them in a jurisdiction nobody labelled them for."
            )
        return _answer_all(args)
    if not args.question_id:
        raise AnswerError("say which question to answer, or pass --all for every question")
    if args.out is not None:
        raise AnswerError(
            "--out writes a whole run, so it needs --all. One answer is already printed "
            "in full; a one-question file would not be the frozen sample it looks like."
        )
    return _answer_one(args)


def _answer_all(args: argparse.Namespace) -> int:
    """Both populations, one pass, refusal precision/recall printed.

    Deliberately **not** wired into `make eval` yet. `make eval` is offline,
    deterministic and gated at zero tolerance; this run is networked, costs money
    and has no floor gate to make it honest until tracer 6 derives one. Attaching
    it early would make the retrieval gate depend on a provider, which is the one
    property that half of the harness has that the other does not.
    """
    manifest = load_manifest(args.manifest)
    golden = load_golden_set(args.golden, manifest)
    morphology = Morphology.open() if PUBLISHED.analyser.lemmatising else None
    planned = len(golden.questions) + len(golden.refusals)
    budget = (
        TokenBudget(ceiling=args.token_ceiling)
        if args.token_ceiling is not None
        else TokenBudget.for_run(planned)
    )
    print(
        f"answering {planned} questions "
        f"({len(golden.questions)} answerable + {len(golden.refusals)} refusal) "
        f"through {args.model}, token ceiling {budget.ceiling}"
    )
    with db.connect() as conn:
        run = answering.run(
            conn,
            manifest=manifest,
            golden=golden,
            budget=budget,
            k=args.k,
            cell=PUBLISHED,
            morphology=morphology,
            model=args.model,
            reasoning=not args.no_reasoning,
            # Flushed per line: this run takes the better part of an hour, and a
            # progress line held in a buffer is not progress.
            progress=lambda line: print(line, flush=True),
        )

    print()
    print(format_refusals(run))
    print()
    print(format_refusal_detail(run))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(_run_as_json(run), encoding="utf-8")
        print(f"\nrun written to {args.out}")
    return 0


def _run_as_json(run: answering.AnswerRun) -> str:
    """The whole run, verbatim, as the frozen sample will need it."""
    payload = {
        "cell": run.cell.name,
        "k": run.k,
        "model": run.model,
        "reasoning": run.reasoning,
        "commit": git_commit(),
        "tokens": run.tokens,
        "cost_usd": run.cost_usd,
        "ceiling": run.ceiling,
        "answers": [
            {
                "question_id": one.question_id,
                "population": population,
                "kind": (
                    run.refusal_kinds[one.question_id].value if population == "refusal" else None
                ),
                "question": one.question,
                "municipality": one.municipality,
                "authority_key": one.authority_key,
                "retrieved": list(one.retrieved),
                "refused": one.answer.refused,
                "text": one.answer.text,
                "citations": list(one.answer.citations),
                "finish_reason": one.answer.finish_reason,
                "usage": {
                    "prompt_tokens": one.answer.usage.prompt_tokens,
                    "completion_tokens": one.answer.usage.completion_tokens,
                    "reasoning_tokens": one.answer.usage.reasoning_tokens,
                    "total_tokens": one.answer.usage.total_tokens,
                    "cost_usd": one.answer.usage.cost_usd,
                },
            }
            for population, answers in (("answerable", run.answerable), ("refusal", run.refusals))
            for one in answers
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _answer_one(args: argparse.Namespace) -> int:
    """One question, end to end, with the price on it.

    Deliberately reuses `evaluate` rather than re-running the search itself: the
    demo must be answering from *the retrieval the harness measures*, not from a
    second implementation of it that could quietly diverge.
    """
    manifest = load_manifest(args.manifest)
    golden = load_golden_set(args.golden, manifest)
    if args.municipality is not None:
        # Resolved before anything else so the refusal costs nothing: an absent
        # municipality has no authority to answer from, and the harness must not
        # pick one (CLAUDE.md's third verification layer, AC14).
        manifest.resolve_municipality(args.municipality)
    morphology = Morphology.open() if PUBLISHED.analyser.lemmatising else None
    with db.connect() as conn:
        run = evaluate(
            conn, manifest=manifest, golden=golden, k=args.k, cell=PUBLISHED, morphology=morphology
        )
        bodies = dict(db.chunk_bodies(conn))

    found = next((r for r in run.runs if r.question.id == args.question_id), None)
    if found is None:
        known = ", ".join(sorted(r.question.id for r in run.runs)[:8])
        raise AnswerError(
            f"no golden question with id {args.question_id!r}. "
            f"{len(run.runs)} exist, for example: {known}"
        )

    budget = TokenBudget(**({} if args.token_ceiling is None else {"ceiling": args.token_ceiling}))
    required = set(found.outcome.required)
    print(f"question  {found.question.id}  ({found.question.municipality} -> {run.cell.name})")
    print(f"          {found.question.question}")
    print(f"\nretrieved top-{run.k}:")
    for hit in found.hits:
        mark = "*" if hit.address in required else " "
        print(f"  {mark} {hit.position}. {hit.address}  {hit.citation}")
    missing = sorted(required - {hit.address for hit in found.hits})
    print(f"          (* = required; {len(required) - len(missing)}/{len(required)} retrieved)")
    if missing:
        print(f"          NOT retrieved: {', '.join(missing)}")

    result = answer_question(
        question_id=found.question.id,
        question=found.question.question,
        hits=found.hits,
        bodies=bodies,
        budget=budget,
        model=args.model,
        reasoning=not args.no_reasoning,
    )
    print(f"\nanswer    {result.model}  refused={result.refused}  {result.finish_reason}")
    print(f"\n{result.text}\n")
    print(f"citations {list(result.citations)}")
    usage = result.usage
    print(
        f"cost      ${usage.cost_usd:.6f} measured at the gateway  "
        f"({usage.prompt_tokens} prompt + {usage.completion_tokens} completion, "
        f"of which {usage.reasoning_tokens} reasoning)"
    )
    return 0


def _judge(args: argparse.Namespace) -> int:
    """Dispatch, and refuse the flag combinations that would silently do nothing."""
    if args.control:
        if args.run is not None:
            raise JudgingError(
                f"--control judges its own authored answers, so it cannot also be given "
                f"{args.run}. Drop one."
            )
        if args.stub_agreement is not None:
            raise JudgingError(
                "--stub-agreement changes what the judged table publishes; the control "
                "publishes no metric, so the flag would be silently ignored."
            )
        if args.limit is not None:
            raise JudgingError(
                "--limit cannot be combined with --control. The control is a FLOOR at "
                "8/8, so a partial control is not a weaker pass -- it is no measurement "
                "at all."
            )
        if args.out is not None:
            raise JudgingError(
                "--out freezes the unit verdicts over the golden set for tracer slice 5. "
                "The control judges authored answers that are not in it, so the file "
                "would look like a frozen sample and not be one."
            )
        return _judge_control(args)
    if args.run is None:
        raise JudgingError(
            "say which answer run to judge, or pass --control for the known-bad control"
        )
    return _judge_run(args)


def _judge_run(args: argparse.Namespace) -> int:
    """Judge a frozen answer run. Networked, costs money, publishes nothing yet."""
    manifest = load_manifest(args.manifest)
    golden = load_golden_set(args.golden, manifest)
    run = load_run(args.run)
    morphology = Morphology.open() if PUBLISHED.analyser.lemmatising else None

    if args.limit is not None and args.limit < 1:
        raise JudgingError(f"--limit judges at least one answer, not {args.limit}")
    planned = len(run.answerable) if args.limit is None else min(args.limit, len(run.answerable))
    budget = (
        TokenBudget(ceiling=args.token_ceiling)
        if args.token_ceiling is not None
        else TokenBudget(ceiling=judge_ceiling_for(planned))
    )
    print(
        f"judging {planned} of {len(run.answerable)} answerable answers from {args.run} "
        f"through {args.model}, token ceiling {budget.ceiling}"
    )
    if args.weak_prompt:
        print(
            "!! WEAKENED JUDGE PROMPT: this run measures a judge built to fail the "
            "control. Nothing from it is a result."
        )
    with db.connect() as conn:
        judged = judging.judge_run(
            conn,
            manifest=manifest,
            golden=golden,
            run=run,
            budget=budget,
            cell=PUBLISHED,
            morphology=morphology,
            model=args.model,
            weak=args.weak_prompt,
            limit=args.limit,
            progress=lambda line: print(line, flush=True),
        )

    print()
    print(format_address_validity(judged))
    print()
    print(format_judged(judged, agreement=args.stub_agreement))
    if args.detail:
        print()
        print(format_judged_detail(judged))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(_judgement_as_json(judged), encoding="utf-8")
        print(f"\nverdicts written to {args.out}")
    if args.stub_agreement is not None:
        print()
        print(
            "NOTE  --stub-agreement was set, so the agreement figure above is INVENTED. "
            "It exists to watch D11's withholding rule change the table, and no number "
            "from this run may be quoted."
        )
    return 0


def _judgement_as_json(run: judging.JudgeRun) -> str:
    """Every unit verdict, verbatim, as tracer slice 5 will need it.

    Written per unit rather than per answer because the hand labels are per unit:
    a file that recorded only the rolled-up counts could not be compared against
    a human at the level D3 publishes agreement at.
    """
    payload = {
        "source": str(run.source),
        "source_commit": run.source_commit,
        "cell": run.cell.name,
        "k": run.k,
        "answerer": run.answerer,
        "judge": run.judge_model,
        "weak_prompt": run.weak,
        "judged_at_commit": git_commit(),
        "partial": run.partial,
        "tokens": run.tokens,
        "cost_usd": run.cost_usd,
        "incoherent_verdicts": run.incoherent_verdicts,
        "answers": [
            {
                "question_id": one.judged.question_id,
                "refused": one.judged.refused,
                "required_branches": one.judged.required_branches,
                "branches": [
                    {
                        "index": verdict.index,
                        "stated": verdict.stated,
                        "supported": verdict.supported,
                        "quote": verdict.quote,
                        "quote_found": verdict.quote_found,
                        "quote_words_present": verdict.quote_words_present,
                    }
                    for verdict in one.judged.branches
                ],
                "forbidden": [
                    {
                        "index": verdict.index,
                        "asserted": verdict.asserted,
                        "quote": verdict.quote,
                        "quote_found": verdict.quote_found,
                        "quote_words_present": verdict.quote_words_present,
                    }
                    for verdict in one.judged.forbidden
                ],
            }
            for one in run.judged
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _judge_control(args: argparse.Namespace) -> int:
    """The known-bad control. Exit code is the gate: non-zero below the floor."""
    manifest = load_manifest(args.manifest)
    golden = load_golden_set(args.golden, manifest)
    cases = load_control(args.control_file, golden)
    morphology = Morphology.open() if PUBLISHED.analyser.lemmatising else None
    budget = (
        TokenBudget(ceiling=args.token_ceiling)
        if args.token_ceiling is not None
        else TokenBudget(ceiling=judge_ceiling_for(len(cases)))
    )
    print(
        f"running {len(cases)} known-bad control cases through {args.model}, "
        f"token ceiling {budget.ceiling}"
    )
    if args.weak_prompt:
        print("!! WEAKENED JUDGE PROMPT: this run is the red proof, not a pass attempt.")
    with db.connect() as conn:
        control = judging.run_control(
            conn,
            manifest=manifest,
            golden=golden,
            cases=cases,
            budget=budget,
            cell=PUBLISHED,
            morphology=morphology,
            model=args.model,
            weak=args.weak_prompt,
            progress=lambda line: print(line, flush=True),
        )

    print()
    print(format_control(control))
    if not control.passed:
        print(
            f"\nfi-rag-eval judge --control: the judge caught {control.caught} of "
            f"{control.total}. The bar is every case: a judge that misses a failure shape "
            "cannot be trusted on that shape, and no judged metric may be published while "
            "this is red.",
            file=sys.stderr,
        )
        return 1
    return 0


def _label(args: argparse.Namespace) -> int:
    """The interactive labelling shell. Holds no logic -- `labelling` holds it all.

    The seam is deliberate: everything that decides what to show, in what order,
    and what to write is a pure function exercised by tests, and this function
    only connects it to a terminal. A protocol whose correctness depended on an
    interactive loop nobody can test would be the weakest link in the slice.
    """
    manifest = load_manifest(args.manifest)
    golden = load_golden_set(args.golden, manifest)
    run = load_run(args.sample)
    morphology = Morphology.open() if PUBLISHED.analyser.lemmatising else None
    questions = questions_to_label(golden=golden, run=run)

    with db.connect() as conn:
        # The same drift check the judge runs. Labels written against a context the
        # corpus no longer produces would be labels of nothing, and the failure
        # would surface as disagreement.
        retrieval = evaluate(
            conn,
            manifest=manifest,
            golden=golden,
            k=run.k or DEFAULT_K,
            cell=PUBLISHED,
            morphology=morphology,
        )
        judging.assert_run_matches_corpus(run, retrieval=retrieval.runs, cell=PUBLISHED)
        bodies = dict(db.chunk_bodies(conn))
        citations = {
            hit.address: hit.citation
            for question_run in retrieval.runs
            for hit in question_run.hits
        }

    # Exit 0 whether the session finished or was stopped part-way: stopping is the
    # protocol working, not a failure. `agreement` is the command that refuses an
    # incomplete label set, and it is the right place for that check because it is
    # the one producing a number.
    labelling.run_session(
        questions=questions,
        labels_path=args.labels,
        sample_path=args.sample,
        sample_commit=run.commit,
        bodies=bodies,
        citations=citations,
        prompt=input,
        emit=lambda line: print(line, flush=True),
    )
    return 0


def _agreement(args: argparse.Namespace) -> int:
    """Judge-human agreement, or judge self-consistency with `--against`."""
    manifest = load_manifest(args.manifest)
    golden = load_golden_set(args.golden, manifest)
    run = load_run(args.sample)
    questions = questions_to_label(golden=golden, run=run)
    verdicts = json.loads(args.verdicts.read_text(encoding="utf-8"))

    if args.against is not None:
        other = json.loads(args.against.read_text(encoding="utf-8"))
        # Self-consistency needs no human labels, so it is computed over every
        # informative unit rather than over what happens to be labelled.
        reference = labelling.every_informative_label(questions)
        first = judge_unit_labels(verdicts, restrict_to=reference)
        second = judge_unit_labels(other, restrict_to=reference)
        print(
            format_agreement(
                unit_agreement(first, second),
                kind="judge self-consistency",
                first=str(args.verdicts),
                second=str(args.against),
                forced=labelling.forced_units(questions),
                partial=False,
            )
        )
        return 0

    labels = load_labels(args.labels)
    if not labels:
        raise LabellingError(
            f"no hand labels at {args.labels}. Judge-human agreement is a comparison "
            "against a human, and there is no human in it yet -- run `fi-rag-eval label`."
        )
    outstanding = labelling.pending(questions, labels)
    if outstanding and not args.partial:
        raise LabellingError(
            f"{len(outstanding)} of {len(labels) + len(outstanding)} units are still "
            f"unlabelled, e.g. {outstanding[0][0].question_id} {outstanding[0][1]} "
            f"{outstanding[0][2]}. Agreement over the labelled subset would be a reduced N "
            "arrived at by accident -- and it would be the labelled subset, which is not a "
            "random one. Finish the labelling, or pass --partial for a progress check that "
            "prints nothing quotable."
        )
    human = human_unit_labels(labels)
    judged = judge_unit_labels(verdicts, restrict_to=labels)
    print(
        format_agreement(
            unit_agreement(human, judged),
            kind="judge-human agreement",
            first=str(args.labels),
            second=str(args.verdicts),
            forced=labelling.forced_units(questions),
            partial=bool(outstanding),
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    # The gateway's credentials live in `.env`, which docker compose already reads
    # for the services. Reading it here too means "clone it and run it" holds for
    # the CLI as well -- without this the first answering run fails on a missing
    # variable that is sitting in a file three lines away. A real environment
    # variable still wins: `load_dotenv` does not override what is already set.
    #
    # Searched from the working directory rather than from this file: the default
    # walks up from `cli.py`, which finds the repository only because this is an
    # editable install. A wheel installed into site-packages would silently find
    # nothing, and "it worked in the dev checkout" is the exact shape of failure
    # the clean-clone build gate exists to catch.
    load_dotenv(find_dotenv(usecwd=True))
    args = _parser().parse_args(argv)
    handlers = {
        "ingest": _ingest,
        "eval": _eval,
        "answer": _answer,
        "judge": _judge,
        "label": _label,
        "agreement": _agreement,
    }
    try:
        return handlers[args.command](args)
    except HANDLED as exc:
        print(f"fi-rag-eval {args.command}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

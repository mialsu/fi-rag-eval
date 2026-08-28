"""The command-line surface: ``fi-rag-eval ingest``, ``eval`` and ``answer``.

Exit codes are a feature, not an afterthought -- CI reads them. Zero means the
run completed and every metric held. Anything else means the table on stdout,
if there is one, must not be trusted.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from fi_rag_eval import db
from fi_rag_eval.analyse import AnalyserError, Morphology
from fi_rag_eval.answer import ANSWERER, AnswerError, TokenBudget, answer_question
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
from fi_rag_eval.manifest import ManifestError, load_manifest
from fi_rag_eval.metrics import MetricsError
from fi_rag_eval.report import (
    Baseline,
    BaselineError,
    compare,
    format_grid,
    format_ingest,
    format_probe_table,
    git_commit,
)

DEFAULT_MANIFEST = Path("corpus/manifest.yaml")
DEFAULT_GOLDEN = Path("corpus/golden")
"""A directory: one file per authority, pooled into one set (slice 4, D11)."""
DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_BASELINE = Path("eval/baseline.json")

HANDLED = (
    AnswerError,
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
        help="answer ONE golden question from the published cell's retrieval, and "
        "print what it cost",
    )
    answer_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    answer_parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    answer_parser.add_argument("--k", type=int, default=DEFAULT_K)
    answer_parser.add_argument(
        "question_id",
        help="which golden question to answer; an unknown id lists the ones that exist",
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
    """One question, end to end, with the price on it.

    Deliberately reuses `evaluate` rather than re-running the search itself: the
    demo must be answering from *the retrieval the harness measures*, not from a
    second implementation of it that could quietly diverge.
    """
    manifest = load_manifest(args.manifest)
    golden = load_golden_set(args.golden, manifest)
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
    handlers = {"ingest": _ingest, "eval": _eval, "answer": _answer}
    try:
        return handlers[args.command](args)
    except HANDLED as exc:
        print(f"fi-rag-eval {args.command}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""The metric table, and the regression gate that reads it.

Two rules govern everything in this module:

* **Never print a number the run did not compute.** There are no defaults, no
  placeholders and no cached values -- if a metric is missing the run failed.
* **Always print the N.** A metric without the question count it was computed
  over is the easiest lie this harness could tell.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fi_rag_eval.db import TEXT_SEARCH_CONFIG
from fi_rag_eval.evaluate import EvaluationRun
from fi_rag_eval.ingest import IngestReport
from fi_rag_eval.metrics import Metrics

RANKER_NOTE = (
    f"Postgres ts_rank over to_tsvector({TEXT_SEARCH_CONFIG!r}, ...), default "
    "normalisation (0). NOT BM25: no inverse document frequency, no document-length "
    "normalisation. Query lexemes are OR-ed; no field weighting."
)


class BaselineError(RuntimeError):
    """The recorded baseline cannot be compared against this run."""


@dataclass(frozen=True, slots=True)
class Baseline:
    """A previous run's numbers, with everything needed to know it is comparable."""

    commit: str
    k: int
    questions: int
    required_chunks: int
    complete_set_recall: float
    per_chunk_recall: float
    mean_reciprocal_rank: float

    @classmethod
    def from_metrics(cls, metrics: Metrics, commit: str) -> Baseline:
        return cls(
            commit=commit,
            k=metrics.k,
            questions=metrics.questions,
            required_chunks=metrics.required_chunks,
            complete_set_recall=metrics.complete_set_recall,
            per_chunk_recall=metrics.per_chunk_recall,
            mean_reciprocal_rank=metrics.mean_reciprocal_rank,
        )

    @classmethod
    def load(cls, path: Path) -> Baseline:
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BaselineError(f"cannot read the baseline at {path}: {exc}") from exc
        try:
            return cls(
                commit=str(payload["commit"]),
                k=int(payload["k"]),
                questions=int(payload["questions"]),
                required_chunks=int(payload["required_chunks"]),
                complete_set_recall=float(payload["complete_set_recall"]),
                per_chunk_recall=float(payload["per_chunk_recall"]),
                mean_reciprocal_rank=float(payload["mean_reciprocal_rank"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BaselineError(f"{path} is not a usable baseline: {exc}") from exc

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_commit() -> str:
    """Identify the run. Every published number is traceable to a commit."""
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{revision}-dirty" if status else revision


def compare(baseline: Baseline, metrics: Metrics) -> list[str]:
    """Return the reasons this run must fail the gate. Empty means green.

    A changed question set is reported rather than tolerated. It is not a
    regression, but comparing across it would be comparing two different
    measurements, and that is how a real drop gets waved through.
    """
    problems: list[str] = []
    if baseline.k != metrics.k:
        problems.append(f"baseline is at k={baseline.k}, this run is at k={metrics.k}")
    if baseline.questions != metrics.questions:
        problems.append(
            f"the golden set has {metrics.questions} questions, the baseline was "
            f"recorded over {baseline.questions}; re-record it deliberately"
        )
    if baseline.required_chunks != metrics.required_chunks:
        problems.append(
            f"the golden set labels {metrics.required_chunks} required chunks, the "
            f"baseline was recorded over {baseline.required_chunks}; re-record it "
            "deliberately"
        )
    if problems:
        return problems

    for label, was, now in (
        ("complete-set recall", baseline.complete_set_recall, metrics.complete_set_recall),
        ("per-chunk recall", baseline.per_chunk_recall, metrics.per_chunk_recall),
        ("MRR", baseline.mean_reciprocal_rank, metrics.mean_reciprocal_rank),
    ):
        if now < was:
            problems.append(f"{label} fell from {was:.3f} to {now:.3f}")
    return problems


def format_ingest(report: IngestReport) -> str:
    lines = ["corpus"]
    for source in report.sources:
        lines.append(
            f"  {source.authority_key}@{source.effective_date}: {source.chunks} chunks "
            f"({source.clauses} clauses, {source.definitions} definition chunks)"
        )
        lines.append(
            f"    extraction: {source.page_breaks} page breaks, "
            f"{source.hyphen_joins} line-break hyphens repaired, "
            f"{source.conjunction_guards} left alone"
            + ("  [downloaded]" if source.downloaded else "  [cached]")
        )
    return "\n".join(lines)


def format_run(run: EvaluationRun, *, commit: str) -> str:
    metrics = run.metrics
    lines = [
        "fi-rag-eval — lexical retrieval baseline",
        f"commit {commit}   k={metrics.k}",
        f"ranker: {RANKER_NOTE}",
        "",
        f"golden set: {metrics.questions} questions, {metrics.required_chunks} required "
        f"chunks, {sum(1 for r in run.runs if len(r.question.required_chunks) > 1)} "
        "spanning more than one chunk",
        "",
        f"{'metric':<34}{'value':>8}   N",
        "-" * 62,
        f"{'complete-set recall@' + str(metrics.k) + ' (headline)':<34}"
        f"{metrics.complete_set_recall:>8.3f}   {metrics.questions} questions",
        f"{'per-chunk recall@' + str(metrics.k) + ' (diagnostic)':<34}"
        f"{metrics.per_chunk_recall:>8.3f}   {metrics.required_chunks} chunks",
        f"{'MRR (diagnostic)':<34}{metrics.mean_reciprocal_rank:>8.3f}   "
        f"{metrics.questions} questions",
        "",
        f"miss breakdown ({metrics.misses} of {metrics.required_chunks} required chunks "
        "not retrieved)",
        f"  zero-overlap  {metrics.misses_zero_overlap:>3}   "
        "unreachable: shares no stem with the question — a morphology failure",
        f"  ranked-out    {metrics.misses_ranked_out:>3}   "
        f"matched but ranked below {metrics.k} — a ranking failure, where IDF would help",
        "",
        "per question",
    ]
    for question_run in run.runs:
        outcome = question_run.outcome
        mark = "PASS" if outcome.complete else "FAIL"
        first = next(
            (
                str(position)
                for position, address in enumerate(outcome.retrieved, start=1)
                if address in set(outcome.required)
            ),
            "-",
        )
        lines.append(
            f"  {mark}  {outcome.question_id:<48} "
            f"{len(outcome.found)}/{len(outcome.required)} required, first at {first}"
        )
        for miss in outcome.misses:
            lines.append(f"          missed {miss.address}  [{miss.kind}]")
    return "\n".join(lines)

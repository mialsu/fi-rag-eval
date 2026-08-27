"""The metric table, and the regression gate that reads it.

Three rules govern everything in this module:

* **Never print a number the run did not compute.** There are no defaults, no
  placeholders and no cached values -- if a metric is missing the run failed.
* **Always print the N.** A metric without the question count it was computed
  over is the easiest lie this harness could tell.
* **One published cell, chosen deliberately.** The grid has eight cells and the
  gate defends all eight, but the README quotes one, and which one it is is a
  recorded decision rather than whichever configuration scored best today.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fi_rag_eval.analyse import PROBE_WORDS, Analyser
from fi_rag_eval.db import TEXT_SEARCH_CONFIG
from fi_rag_eval.evaluate import PUBLISHED, EvaluationRun, GridRun
from fi_rag_eval.golden import Phrasing
from fi_rag_eval.ingest import IngestReport
from fi_rag_eval.metrics import Metrics, discordance

RANKER_NOTE = (
    "Postgres ts_rank over a tsvector, normalisation as shown per cell. NOT BM25: "
    "no inverse document frequency, and at normalisation 0 no document-length "
    "normalisation either. Query lexemes are OR-ed; no field weighting."
)

ANALYSER_NOTE = (
    f"snowball is to_tsvector({TEXT_SEARCH_CONFIG!r}, ...) -- the control. The three "
    "lemma analysers are voikko, in Python (ADR-0005), and they nest: baseform, then "
    "+ a conservative compound split, then + one that reassembles derivational "
    "affixes. All four stop on the same words, so a cell-to-cell delta is the "
    "normalisation of a kept word and nothing else."
)


WIDTH = 92
"""Report width. The table is read in a terminal, so the prose is wrapped to fit."""


def _wrapped(prefix: str, body: str) -> list[str]:
    return textwrap.wrap(
        body, width=WIDTH, initial_indent=prefix, subsequent_indent=" " * len(prefix)
    )


class BaselineError(RuntimeError):
    """The recorded baseline cannot be compared against this run."""


@dataclass(frozen=True, slots=True)
class CellBaseline:
    """One cell's recorded numbers. Compared only against the same cell."""

    complete_set_recall: float
    per_chunk_recall: float
    mean_reciprocal_rank: float
    lexical_leakage: float

    @classmethod
    def from_metrics(cls, metrics: Metrics) -> CellBaseline:
        return cls(
            complete_set_recall=metrics.complete_set_recall,
            per_chunk_recall=metrics.per_chunk_recall,
            mean_reciprocal_rank=metrics.mean_reciprocal_rank,
            lexical_leakage=metrics.lexical_leakage,
        )


@dataclass(frozen=True, slots=True)
class Baseline:
    """A previous run's numbers, with everything needed to know it is comparable.

    Every cell is recorded, and **any** cell regressing fails the gate. Gating one
    cell would let the other seven rot silently, and would make this slice's gate
    trivially green -- a gate that cannot fail is decoration.

    Recording per cell is also what makes the leakage gate survive lemmatisation.
    Leakage is a property of the questions *under an analyser*: words snowball
    stems apart, lemmatisation joins, so the same golden set leaks more in a lemma
    cell without a single question having been edited. Comparing each cell against
    its own recorded leakage compares like with like, instead of waiving the rule.
    """

    commit: str
    k: int
    questions: int
    required_chunks: int
    analyser_fingerprint: str
    published_cell: str
    cells: dict[str, CellBaseline]

    @classmethod
    def from_grid(cls, grid: GridRun, commit: str) -> Baseline:
        first = grid.cells[0].metrics
        return cls(
            commit=commit,
            k=grid.k,
            questions=first.questions,
            required_chunks=first.required_chunks,
            analyser_fingerprint=grid.fingerprint,
            published_cell=PUBLISHED.name,
            cells={run.cell.name: CellBaseline.from_metrics(run.metrics) for run in grid.cells},
        )

    @classmethod
    def load(cls, path: Path) -> Baseline:
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BaselineError(f"cannot read the baseline at {path}: {exc}") from exc
        if not isinstance(payload, dict) or "cells" not in payload:
            raise BaselineError(
                f"{path} is a pre-slice-3 baseline: it records one set of metrics, not "
                "one per grid cell, and has no analyser fingerprint. Re-record it "
                "deliberately with `make eval-baseline` after reading the new table."
            )
        try:
            cells = {
                str(name): CellBaseline(
                    complete_set_recall=float(values["complete_set_recall"]),
                    per_chunk_recall=float(values["per_chunk_recall"]),
                    mean_reciprocal_rank=float(values["mean_reciprocal_rank"]),
                    lexical_leakage=float(values["lexical_leakage"]),
                )
                for name, values in payload["cells"].items()
            }
            return cls(
                commit=str(payload["commit"]),
                k=int(payload["k"]),
                questions=int(payload["questions"]),
                required_chunks=int(payload["required_chunks"]),
                analyser_fingerprint=str(payload["analyser_fingerprint"]),
                published_cell=str(payload["published_cell"]),
                cells=cells,
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise BaselineError(f"{path} is not a usable baseline: {exc}") from exc

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_commit() -> str:
    """Identify the run. Every published number is traceable to a commit.

    Called *before* a baseline is written, deliberately: recording a baseline
    dirties the tree by creating the very file being recorded, so capturing the
    revision afterwards would stamp every baseline ``-dirty`` and make the flag
    meaningless. Record baselines from a clean tree; the resulting file names the
    commit whose code produced the numbers, and lands in the commit after it.
    """
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


def compare(baseline: Baseline, grid: GridRun) -> list[str]:
    """Return the reasons this run must fail the gate. Empty means green.

    A changed question set, a changed grid or a changed analyser is *reported*
    rather than tolerated. None of them is a regression, but comparing across one
    would be comparing two different measurements, and that is how a real drop
    gets waved through.
    """
    problems: list[str] = []
    if baseline.analyser_fingerprint != grid.fingerprint:
        problems.append(
            f"the analyser changed: baseline fingerprint {baseline.analyser_fingerprint}, "
            f"this run {grid.fingerprint} (voikko library {grid.library_version}). "
            "libvoikko does not expose the dictionary version, so this is the only "
            "signal that voikko-fi moved. Diff the probe table printed above against "
            "the baseline commit, then re-record deliberately -- every published "
            "number depends on this."
        )
    first = grid.cells[0].metrics
    if baseline.k != grid.k:
        problems.append(f"baseline is at k={baseline.k}, this run is at k={grid.k}")
    if baseline.questions != first.questions:
        problems.append(
            f"the golden set has {first.questions} questions, the baseline was "
            f"recorded over {baseline.questions}; re-record it deliberately"
        )
    if baseline.required_chunks != first.required_chunks:
        problems.append(
            f"the golden set labels {first.required_chunks} required chunks, the "
            f"baseline was recorded over {baseline.required_chunks}; re-record it "
            "deliberately"
        )
    if baseline.published_cell != PUBLISHED.name:
        problems.append(
            f"the published cell moved from {baseline.published_cell} to "
            f"{PUBLISHED.name}. That is the Owner's decision and comes with a "
            "deliberate re-baseline, not a code change"
        )
    measured = {run.cell.name for run in grid.cells}
    if measured != set(baseline.cells):
        missing = sorted(set(baseline.cells) - measured)
        extra = sorted(measured - set(baseline.cells))
        problems.append(
            f"the grid changed: {len(measured)} cells measured, "
            f"{len(baseline.cells)} recorded"
            + (f"; not measured: {missing}" if missing else "")
            + (f"; not recorded: {extra}" if extra else "")
        )
    if problems:
        return problems

    for run in grid.cells:
        recorded = baseline.cells[run.cell.name]
        metrics = run.metrics
        for label, was, now in (
            ("complete-set recall", recorded.complete_set_recall, metrics.complete_set_recall),
            ("per-chunk recall", recorded.per_chunk_recall, metrics.per_chunk_recall),
            ("MRR", recorded.mean_reciprocal_rank, metrics.mean_reciprocal_rank),
        ):
            if now < was:
                problems.append(f"{run.cell.name}: {label} fell from {was:.3f} to {now:.3f}")

        # Guarded in the opposite direction, deliberately. Every metric above is a
        # score to defend from falling; leakage is a *handicap* to defend from
        # rising. A question edited to look more like its target chunk raises the
        # headline while making the harness weaker, and that is the one
        # "improvement" this project must never accept silently. Falling leakage is
        # progress and passes.
        if metrics.lexical_leakage > recorded.lexical_leakage:
            problems.append(
                f"{run.cell.name}: lexical leakage rose from "
                f"{recorded.lexical_leakage:.3f} to {metrics.lexical_leakage:.3f} — "
                "the golden set got easier, which inflates every score above it"
            )
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
    lemmas = report.lemmas
    lines.extend(
        [
            "",
            f"analyser: voikko library {lemmas.library_version}, "
            f"fingerprint {lemmas.fingerprint} over {len(PROBE_WORDS)} probe words",
            f"    {lemmas.word_tokens} word tokens ({lemmas.stopped_tokens} stopped by the "
            f"{TEXT_SEARCH_CONFIG!r} stopword list), {lemmas.unique_words} distinct forms",
            f"    {lemmas.unanalysable_words} forms "
            f"({lemmas.unanalysable_share:.1%}) have no analysis and are indexed as raw "
            "tokens",
            "    lexemes indexed: "
            + " · ".join(f"{analyser} {count}" for analyser, count in lemmas.lexemes),
        ]
    )
    return "\n".join(lines)


def format_lexeme_counts(counts: dict[Analyser, int]) -> str:
    """Index size per analyser -- the evidence for the grid's second axis.

    Compound splitting inflates the lexeme count, and `ts_rank` at normalisation 0
    rewards accumulated term weight. These two numbers are why the analyser and
    the normalisation had to be measured together rather than in sequence.
    """
    baseline = counts[Analyser.SNOWBALL]
    return " · ".join(
        f"{analyser} {count}"
        + ("" if analyser is Analyser.SNOWBALL else f" ({count / baseline:.2f}x snowball)")
        for analyser, count in counts.items()
    )


def format_grid(grid: GridRun, *, commit: str, lexemes: dict[Analyser, int]) -> str:
    """The whole table: header, one row per cell, the pass matrix, then detail."""
    published = grid.published
    first = published.metrics
    harvested = sum(1 for r in published.runs if r.question.phrasing is Phrasing.HARVESTED)
    paired = len({r.question.pair for r in published.runs if r.question.pair is not None})
    lines = [
        "fi-rag-eval — lexical retrieval grid",
        f"commit {commit}   k={grid.k}   {len(grid.cells)} cells",
        f"analyser: voikko library {grid.library_version}, fingerprint {grid.fingerprint} "
        f"over {len(PROBE_WORDS)} probe words",
        *_wrapped("ranker: ", RANKER_NOTE),
        *_wrapped("cells:  ", ANALYSER_NOTE),
        "",
        f"golden set: {first.questions} questions, {first.required_chunks} required "
        f"chunks, {sum(1 for r in published.runs if len(r.question.required_chunks) > 1)} "
        "spanning more than one chunk",
        f"            phrasing: {harvested} harvested verbatim from resident-facing pages, "
        f"{first.questions - harvested} authored",
        *_wrapped(
            "            ",
            "authorities: "
            + " · ".join(f"{key} {metrics.questions}" for key, metrics in published.by_authority())
            + f";  {paired} paired question(s) — one text labelled once per authority",
        ),
        *_wrapped("index size: ", format_lexeme_counts(lexemes)),
        "",
        f"{'cell':<20}{'recall@' + str(grid.k):>9}{'per-chunk':>11}{'MRR':>8}"
        f"{'leakage':>10}{'zero-ovl':>10}{'ranked-out':>12}",
        "-" * 80,
    ]
    for run in grid.cells:
        metrics = run.metrics
        mark = "  <- published" if run.cell == PUBLISHED else ""
        lines.append(
            f"{run.cell.name:<20}{metrics.complete_set_recall:>9.3f}"
            f"{metrics.per_chunk_recall:>11.3f}{metrics.mean_reciprocal_rank:>8.3f}"
            f"{metrics.lexical_leakage:>10.3f}{metrics.misses_zero_overlap:>10}"
            f"{metrics.misses_ranked_out:>12}{mark}"
        )
    lines.extend(
        [
            "",
            f"  recall@{grid.k} is complete-set recall (ADR-0003): per question, did the top "
            f"{grid.k}",
            "  contain EVERY chunk the answer depends on. It is the headline, and it cannot be",
            "  read without leakage beside it — leakage is how much of each question's own",
            "  vocabulary its target chunk already contains, a property of the QUESTIONS and",
            "  not of the retriever. Each cell is gated against its own recorded leakage.",
            "",
            "  zero-ovl is a required chunk sharing no lexeme with the question at all: a",
            "  morphology failure. ranked-out matched but lost the ranking: an IDF failure.",
            "  A miss moving from the first column to the second was reached by morphology",
            "  and lost by ranking — a different fix from the one that was applied.",
            "",
            f"published headline: {PUBLISHED.name} — the cell the README quotes. Moving it is",
            "  the Owner's decision, with a deliberate re-baseline. The headline is POOLED",
            "  over every authority in the set; the rows below say where it comes from and",
            "  are diagnostics, not headlines of their own.",
            "",
            format_by_authority(published),
            "",
            format_power(grid),
            "",
            f"per question x cell   (P = every required chunk inside the top {grid.k}, . = not)",
            f"  {'':<40}" + "".join(f"{run.cell.short:>5}" for run in grid.cells),
        ]
    )
    for index, question_run in enumerate(published.runs):
        marks = "".join(
            f"{'P' if run.runs[index].outcome.complete else '.':>5}" for run in grid.cells
        )
        lines.append(f"  {question_run.outcome.question_id:<40}{marks}")
    lines.extend(["", format_cell_detail(published)])
    best = grid.best
    if best.cell != PUBLISHED:
        lines.extend(["", format_cell_detail(best)])
    return "\n".join(lines)


def format_by_authority(run: EvaluationRun) -> str:
    """One cell's metrics broken down per authority (slice 4, D11).

    Printed because the pooled headline hides real heterogeneity: one authority's
    questions have had three slices of implicit fitting and the other's none. It
    is *not* gated per authority -- the gate defends the pooled number of every
    cell -- so a row moving here is a thing to look at, not a thing to trust.
    """
    rows = run.by_authority()
    lines = [
        f"per authority — {run.cell.name}   (diagnostic; the gate defends the pooled row)",
        f"  {'authority':<20}{'N':>4}{'recall@' + str(run.k):>10}{'per-chunk':>11}"
        f"{'MRR':>8}{'leakage':>10}{'zero-ovl':>10}{'ranked-out':>12}",
    ]
    for key, metrics in rows:
        lines.append(
            f"  {key:<20}{metrics.questions:>4}{metrics.complete_set_recall:>10.3f}"
            f"{metrics.per_chunk_recall:>11.3f}{metrics.mean_reciprocal_rank:>8.3f}"
            f"{metrics.lexical_leakage:>10.3f}{metrics.misses_zero_overlap:>10}"
            f"{metrics.misses_ranked_out:>12}"
        )
    if len(rows) > 1:
        lines.append(
            "  A row here cannot register an improvement on its own: six discordant questions"
        )
        lines.append(
            "  are needed for p<0.05, which no single authority's slice of this set can reach."
        )
    return "\n".join(lines)


def format_power(grid: GridRun) -> str:
    """What this run can and cannot resolve: discordant counts and exact McNemar p.

    Every pair of cells is scored on the same questions, so the comparison is
    **paired** and an absolute-difference interval is the wrong test. Only the
    questions two cells disagree about carry information, and with all of them
    flipping one way the exact test gives ``2 x 0.5^d`` -- so six must flip for
    p<0.05 at any N.

    Printed as two triangles rather than 66 lines, and printed at all so that a
    reader never has to assume a 0.048 delta between two cells means something
    (slice 4, D10). The regression gate needs none of this: it is deterministic at
    any N. Power is only about claiming an improvement is *real*.
    """
    cells = grid.cells
    heads = "".join(f"{run.cell.short:>6}" for run in cells)
    lines = [
        "paired power — every cell against every other, over the same questions",
        f"  d = questions the two disagree about; p = exact two-sided McNemar. "
        f"N={cells[0].metrics.questions}",
        "  d >= 6 is the threshold for p<0.05, whatever N is. Below it, a delta between",
        "  two cells is not something this instrument can resolve.",
        "",
        f"  discordant d{'':<8}{heads}",
    ]
    pairs = {}
    for i, left in enumerate(cells):
        for j, right in enumerate(cells):
            if i < j:
                pairs[(i, j)] = discordance(
                    [r.outcome for r in left.runs], [r.outcome for r in right.runs]
                )
    for i, left in enumerate(cells):
        row = "".join(
            "     ." if i == j else f"{pairs[(min(i, j), max(i, j))].discordant:>6}"
            for j in range(len(cells))
        )
        lines.append(f"  {left.cell.name:<20}{row}")
    lines.extend(["", f"  exact p{'':<13}{heads}"])
    for i, left in enumerate(cells):
        row = "".join(
            "     ." if i == j else f"{pairs[(min(i, j), max(i, j))].p_value:>6.3f}"
            for j in range(len(cells))
        )
        lines.append(f"  {left.cell.name:<20}{row}")
    return "\n".join(lines)


def format_cell_detail(run: EvaluationRun) -> str:
    """Per-question detail for one cell, with every miss named and classified."""
    metrics = run.metrics
    lines = [
        f"per question — {run.cell.name}"
        + ("  (published)" if run.cell == PUBLISHED else "  (best cell this run)"),
        f"  {metrics.misses} of {metrics.required_chunks} required chunks not retrieved: "
        f"{metrics.misses_zero_overlap} zero-overlap, {metrics.misses_ranked_out} ranked-out",
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
        leakage = outcome.lexical_leakage
        lines.append(
            f"  {mark}  {outcome.question_id:<48} "
            f"{len(outcome.found)}/{len(outcome.required)} required, first at {first}, "
            f"leakage {'n/a' if leakage is None else format(leakage, '.0%')}"
        )
        for miss in outcome.misses:
            lines.append(f"          missed {miss.address}  [{miss.kind}]")
    return "\n".join(lines)


def format_probe_table(
    grid: GridRun, probe: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]
) -> str:
    """What the analyser does to `PROBE_WORDS`, in full.

    Printed beside the fingerprint so that a mismatch is *diagnosable* and not
    merely detectable: the fingerprint says the analyser changed, this says how.
    """
    lines = [
        f"analyser probe — fingerprint {grid.fingerprint}, voikko library {grid.library_version}",
        "  a change to any line below changes the fingerprint and fails the gate",
    ]
    for word, baseform, reassembled in probe:
        lines.append(f"  {word:<24} baseform: {' '.join(baseform)}")
        if reassembled != baseform:
            lines.append(f"  {'':<24} reasm:    {' '.join(reassembled)}")
    return "\n".join(lines)

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
from fi_rag_eval.answering import AnswerRun
from fi_rag_eval.db import TEXT_SEARCH_CONFIG
from fi_rag_eval.evaluate import PUBLISHED, EvaluationRun, GridRun
from fi_rag_eval.golden import Phrasing
from fi_rag_eval.ingest import IngestReport
from fi_rag_eval.judging import ControlRun, JudgeRun, OfflineRefusalRun
from fi_rag_eval.metrics import Agreement, Metrics, RefusalMetrics, discordance

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
            format_citations(published),
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


def format_citations(run: EvaluationRun) -> str:
    """One real retrieved citation per authority, exactly as a human would read it.

    Printed because a citation is the product's whole claim to trustworthiness and
    it is otherwise invisible: the metric table shows addresses, and an address
    names the date the text came into force rather than the edition. Pirkanmaa's
    address says 2021 while its text is published as the 1.5.2026 edition after
    five amendments (ADR-0006), so this line is where a reader learns which of the
    six they are being shown -- and where a stale edition label would be noticed.
    """
    seen: dict[str, str] = {}
    for question_run in run.runs:
        if question_run.authority_key not in seen and question_run.hits:
            seen[question_run.authority_key] = question_run.hits[0].citation
    lines = ["citations — one retrieved chunk per authority, as a reader sees it"]
    for authority, citation in sorted(seen.items()):
        lines.append(f"  {authority:<16} {citation}")
    lines.append(
        "  The address keys on Voimaantulo; the edition in brackets is what a human reads."
    )
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


def _restricted_precision_lines(metrics: RefusalMetrics) -> list[str]:
    """The second reading of precision, printed only beside the first (Owner, 31 Aug 2026).

    Never on its own and never instead: the system-level figure is what a resident
    experiences and stays the published one. This answers a different question --
    *when the retriever gave the answerer what it needed, how good was its
    judgement?* -- and the gap between the two is a fact about RETRIEVAL, not about
    the answerer, which is exactly why both belong on the page.
    """
    if metrics.restricted_precision is None:
        return [
            "  restricted precision NOT COMPUTED — retrieval completeness is unknown for at",
            "  least one answerable question, and a partly-unknown denominator is not a",
            "  smaller one.",
        ]
    lines = [
        f"  precision* {metrics.restricted_precision.render():<28} "
        "same numerator, minus refusals of questions",
        "             whose retrieval was INCOMPLETE   (diagnostic, never the published one)",
    ]
    if metrics.excused:
        lines.append(
            f"  excused ({len(metrics.excused)}): {', '.join(metrics.excused)} — refused, and the"
        )
        lines.append(
            "  context genuinely lacked the answer. Precision as defined charges the answerer"
        )
        lines.append("  for a RETRIEVAL failure; precision* does not. Read them together.")
    else:
        lines.append(
            "  Nothing excused: every wrongly-refused question had complete retrieval, so the"
        )
        lines.append("  two readings coincide and the answerer owns all of them.")
    return lines


def format_refusals(run: AnswerRun) -> str:
    """The refusal population's arithmetic, with its interval on every figure.

    Nothing here involves a judge, which is what makes it the answer phase's most
    trustworthy output -- the same reason retrieval metrics win arguments against
    one. Every proportion carries a Wilson interval and its n, because at R=14 the
    point estimate alone is not a number anyone should act on.
    """
    metrics = run.metrics
    lines = [
        f"refusal behaviour — {run.cell.name}, {run.model}, "
        f"reasoning {'on' if run.reasoning else 'off'}   (DIAGNOSTIC, never a headline)",
        f"  recall     {metrics.recall.render():<28} correct refusals / refusal population",
        f"  precision  {metrics.precision.render():<28} correct refusals / all refusals emitted",
    ]
    lines.extend(_restricted_precision_lines(metrics))
    for kind, interval in metrics.by_kind:
        lines.append(f"  {kind.value:<10} {interval.render()}")
    lines.append(
        "  Intervals are Wilson 95%, not the +/-0.13 the spec quotes -- that figure is one"
    )
    lines.append(
        "  standard error. At n=13 a 95% interval is roughly +/-0.26, which is why refusal"
    )
    lines.append("  recall is reported as a floor and a direction, never as a published number.")
    if metrics.missed:
        lines.append(f"  ANSWERED anyway ({len(metrics.missed)}): {', '.join(metrics.missed)}")
    if metrics.wrongly_refused:
        lines.append(
            f"  WRONGLY refused ({len(metrics.wrongly_refused)}): "
            f"{', '.join(metrics.wrongly_refused)}"
        )
    if metrics.refusals_citing_outside:
        lines.append(
            f"  DEFECT — refusals citing what they were not given "
            f"({len(metrics.refusals_citing_outside)}): "
            f"{', '.join(metrics.refusals_citing_outside)}"
        )
        lines.append(
            "  A refusal asserts the retrieved context does not answer the question, so an"
        )
        lines.append("  address from outside that context is wrong however it got there.")
    if metrics.refusals_citing_context:
        lines.append(
            f"  diagnostic — refusals citing the context they explain "
            f"({len(metrics.refusals_citing_context)}): "
            f"{', '.join(metrics.refusals_citing_context)}"
        )
        lines.append(
            "  NOT a defect (ADR-0010). These cite a retrieved chunk to say what the excerpts"
        )
        lines.append(
            "  DO cover -- a more auditable refusal than a bare one. The count is watched;"
        )
        lines.append("  neither direction is wrong.")
    lines.append(
        f"  cost       ${run.cost_usd:.4f} measured at the gateway over {run.calls} calls, "
        f"{run.tokens} tokens (ceiling {run.ceiling})"
    )
    if run.json_validation_retries:
        lines.append(
            f"  NOTE       the provider rejected {run.json_validation_retries} generation(s) as "
            "invalid JSON and they were retried."
        )
        lines.append(
            "  Retrying is not skipping -- every question is still answered and scored -- but"
        )
        lines.append(
            "  how often the answerer cannot emit its envelope is a fact about the answerer."
        )
    return "\n".join(lines)


def format_refusal_detail(run: AnswerRun) -> str:
    """Every refusal question, what it retrieved, and what the answerer did.

    Printed in full rather than summarised because AC13 asks for the printed
    answer of at least one out-of-jurisdiction case, and because a refusal metric
    that cannot be read back question by question is a number with no defence.
    """
    lines = ["refusal population — question by question"]
    for scored in run.refusals:
        kind = run.refusal_kinds[scored.question_id]
        verdict = "REFUSED" if scored.answer.refused else "ANSWERED (miss)"
        lines.append("")
        lines.append(f"  {scored.question_id}  [{kind.value}]  {scored.municipality}  -> {verdict}")
        lines.append(f"    {scored.question}")
        lines.append(f"    retrieved: {', '.join(scored.retrieved) or '(nothing)'}")
        if scored.answer.citations:
            lines.append(f"    citations: {', '.join(scored.answer.citations)}")
        body = textwrap.fill(
            scored.answer.text, width=WIDTH - 6, initial_indent="    ", subsequent_indent="    "
        )
        lines.append(body)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The judged answer layer (slice 5, tracer 4)
# ---------------------------------------------------------------------------

AGREEMENT_FLOOR = 0.85
"""D11's pre-registered publishability floor for judge-human agreement.

Fixed in the spec before any agreement figure existed, *because* a floor set
afterwards is whatever the number happened to be. Below it the judge carries ~15%
label noise and a 0.05 difference in groundedness stops being distinguishable from
the judge disagreeing with itself.
"""


def _ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def format_address_validity(run: JudgeRun) -> str:
    """Citation address validity: the answer layer's number that needs no judge.

    Printed first and without a caveat, deliberately. It is arithmetic over the
    retrieved sets, so it is the one figure here that is publishable the moment it
    exists -- the same standing `metrics.py` has at the retrieval layer, and for
    the same reason.
    """
    validity = run.validity
    lines = [
        "citation address validity — arithmetic only, no judge, no network, no floor",
        f"  answers            {validity.answers} judged, {validity.answers_citing} cited anything",
        f"  citations          {validity.citations} emitted",
        f"  resolve            {_ratio(validity.validity)}   {validity.inside} name a chunk "
        "this question actually retrieved",
        f"  clean answers      {_ratio(validity.clean_answers)}   every citation resolves",
        f"  unparseable        {validity.unparseable}   not a chunk address at all",
        f"  outside context    {validity.outside}   a real-looking address the answerer was "
        "not given",
        f"  FOREIGN authority  {validity.foreign}   cited another authority's document",
    ]
    if validity.foreign_offenders:
        lines.append(
            f"  DEFECT — cross-authority citations in: {', '.join(validity.foreign_offenders)}"
        )
        lines.append(
            "  The retrieval filter is proven to keep foreign chunks out of the top-k; that"
        )
        lines.append(
            "  is a different claim from the answer never citing one, and this is the check"
        )
        lines.append("  for the second claim.")
    elif validity.offenders:
        lines.append(f"  answers with an unresolvable citation: {', '.join(validity.offenders)}")
    return "\n".join(lines)


def format_judged(run: JudgeRun, *, agreement: float | None = None) -> str:
    """The judged metrics, and D11's publication rule enforced rather than described.

    **This function is where "never publish a judged metric whose judge is
    unvalidated" actually happens.** `JudgeRun` carries no agreement field, so the
    caller has to supply one or state that there is none; and with none, or one
    below the floor, the judged figures are withheld from the published block and
    appear only under a DIAGNOSTIC heading that says why they may not be quoted.

    **The headline is branch coverage, not groundedness, since 31 Aug 2026** --
    D11 inverted on the Owner's decision, on the measured finding that
    groundedness has no variance on this answerer. The pairing rule is unchanged
    and is the part that was always load-bearing: neither figure is ever printed
    without the other.

    The alternative -- a metrics object that hides its own value -- was rejected
    because it is harder to test than an object that carries the number and a
    report that refuses it a headline.
    """
    metrics = run.metrics
    publishable = agreement is not None and agreement >= AGREEMENT_FLOOR
    lines = [
        f"answer layer — {run.cell.name}, answerer {run.answerer}, judge {run.judge_model}",
        f"  source        {run.source}  (answered at commit {run.source_commit or 'unknown'})",
        f"  judged        {metrics.answers} answers, {metrics.units} units "
        f"({metrics.branches_required} branches + {metrics.forbidden_items} forbidden)",
    ]
    if run.weak:
        lines.append("  !! WEAKENED JUDGE PROMPT — these numbers measure a judge built to fail the")
        lines.append("     control. Never quote them as a result.")
    if run.dirty_provenance:
        lines.append(
            "  !! the answers were produced from an UNCOMMITTED tree, so this table cannot"
        )
        lines.append("     be reproduced from a commit. Said out loud rather than rounded off.")
    if run.partial:
        lines.append(
            f"  !! PARTIAL RUN — {metrics.answers} of {run.available} answers judged. This is"
        )
        lines.append(
            "     NOT a result and no number below may be quoted: a metric over a reduced N"
        )
        lines.append("     is the output this project says destroys it.")

    lines.append("")
    # A partial run cannot publish, whatever the agreement figure says. The two
    # gates are independent and both have to hold.
    publishable = publishable and not run.partial
    if publishable:
        assert agreement is not None  # narrowed by `publishable`
        lines.append("  PUBLISHED")
        lines.append(
            f"    branch coverage   {metrics.branch_coverage:.3f}   stated "
            f"{metrics.branches_stated} / required {metrics.branches_required} branches"
            "   <- THE HEADLINE"
        )
        lines.append(
            f"    groundedness      {_ratio(metrics.groundedness)}   supported "
            f"{metrics.branches_supported} / stated {metrics.branches_stated} branches"
        )
        lines.append(
            f"    judge agreement   {agreement:.3f}   at or above the {AGREEMENT_FLOOR:.2f} floor"
        )
        lines.append("    D11 INVERTED, 31 Aug 2026: branch coverage leads and groundedness is the")
        lines.append("    companion. Groundedness measured 1.000 with complete retrieval AND 1.000")
        lines.append(
            "    without it -- no variance on this answerer, which drops a branch rather than"
        )
        lines.append(
            "    stating one it cannot cite. A headline that reads the same whether retrieval"
        )
        lines.append("    worked or not tells a reader nothing, and gets quoted anyway.")
        lines.append(
            "    Neither ever appears alone: groundedness is gameable by saying less, branch"
        )
        lines.append("    coverage by saying everything. Only the pair is a metric.")
    else:
        lines.append("  PUBLISHED   nothing. Branch coverage AND groundedness are WITHHELD.")
        if agreement is None:
            lines.append(
                "    Judge-human agreement is NOT MEASURED — it is tracer slice 5's work and"
            )
            lines.append("    does not exist yet. D11: no judged figure may appear without it, so")
            lines.append(
                "    there is no publishable answer-layer number in this run. An unvalidated"
            )
            lines.append("    judge is a second opinion with extra steps.")
        else:
            lines.append(f"    Judge-human agreement is {agreement:.3f}, below the pre-registered")
            lines.append(
                f"    {AGREEMENT_FLOOR:.2f} floor. At that level the judge carries ~15% label"
            )
            lines.append(
                "    noise, so a 0.05 difference in either figure is not distinguishable from"
            )
            lines.append("    the judge disagreeing with itself.")

    lines.append("")
    lines.append("  DIAGNOSTIC — computed, not published. Do not quote these on their own.")
    lines.append(
        f"    branch coverage   {metrics.branch_coverage:.3f}   stated "
        f"{metrics.branches_stated} / required {metrics.branches_required} branches"
    )
    lines.append(
        f"    groundedness      {_ratio(metrics.groundedness)}   supported "
        f"{metrics.branches_supported} / stated {metrics.branches_stated} branches"
    )
    lines.append(
        f"    over-claim rate   {metrics.over_claim_rate:.3f}   "
        f"{len(metrics.answers_over_claiming)} of {metrics.answers} answers assert a "
        "forbidden claim"
    )
    lines.append(
        f"    forbidden items   {metrics.forbidden_asserted} of {metrics.forbidden_items} "
        "asserted (per item, not per answer)"
    )
    lines.append(
        f"    refused           {metrics.refused} of {metrics.answers} answerable questions; "
        "each scores 0 on branch coverage"
    )
    lines.append(
        "    No interval is printed for any of these. Units cluster within an answer, so a"
    )
    lines.append(
        "    naive binomial interval would overstate the precision -- the same class of error"
    )
    lines.append("    as the +/-0.18 slice 3 retracted. A cluster-aware one arrives with tracer 5.")

    lines.append("")
    lines.append("  THE JUDGE'S OWN BEHAVIOUR — watched, because it is under validation")
    if metrics.judge_fabrications:
        lines.append(
            f"    DEFECT — quoted words the answer does not contain, on "
            f"{len(metrics.judge_fabrications)}: {', '.join(metrics.judge_fabrications)}"
        )
        lines.append(
            "    This is the judge agreeing a claim is present because it ought to be, and it"
        )
        lines.append(
            "    would corrupt the metric. Caught by string search, with no human in the loop."
        )
    if metrics.judge_splices:
        lines.append(
            f"    splices — quote not contiguous, every word present, on "
            f"{len(metrics.judge_splices)}: {', '.join(metrics.judge_splices)}"
        )
        lines.append(
            "    NOT a defect. The judge joined fragments from different parts of the answer,"
        )
        lines.append(
            "    so the claim really is stated. Reported apart from the line above because"
        )
        lines.append(
            "    pooling them would inflate the count that matters -- measured, not assumed:"
        )
        lines.append(
            "    the first full run flagged 9 answers and the first one inspected was a splice."
        )
    if not metrics.judge_fabrications and not metrics.judge_splices:
        lines.append(
            "    quote check       every `stated` and `asserted` verdict quoted the answer verbatim"
        )
    lines.append(
        f"    incoherent        {run.incoherent_verdicts} verdict(s) normalised "
        "(`supported` without `stated`, or a branch read out of a refusal)"
    )
    if run.json_validation_retries:
        lines.append(
            f"    json retries      {run.json_validation_retries} generation(s) rejected as "
            "invalid JSON and retried"
        )
    lines.append(
        f"  cost          ${run.cost_usd:.4f} measured at the gateway over {run.calls} calls, "
        f"{run.tokens} tokens (ceiling {run.ceiling})"
    )
    return "\n".join(lines)


def format_judged_detail(run: JudgeRun) -> str:
    """Every judged answer, unit by unit, with the judge's own quote.

    A judged metric that cannot be read back claim by claim is a number with no
    defence. This is also the view tracer slice 5's hand labelling is done
    against, so it prints the quote rather than summarising it.
    """
    lines = ["judged answers — unit by unit"]
    checks = {one.question_id: one for one in run.checks}
    for judgement in run.judged:
        one = judgement.judged
        lines.append("")
        state = "REFUSED" if one.refused else f"stated {one.stated}/{one.required_branches}"
        lines.append(
            f"  {one.question_id}  {state}  supported {one.supported}  "
            f"over-claims {one.over_claims}"
        )
        cited = checks.get(one.question_id)
        if cited is not None and cited.invalid:
            lines.append(f"    unresolvable citations: {', '.join(cited.invalid)}")
        for verdict in one.branches:
            mark = "-" if not verdict.stated else ("OK " if verdict.supported else "UNSUPPORTED")
            lines.append(f"    B{verdict.index} {mark:<12} {verdict.quote[:110] or '(not stated)'}")
            if verdict.stated and not verdict.quote_found:
                lines.append("        ^ the judge's quote is NOT in the answer text")
        for over_claim in one.forbidden:
            if over_claim.asserted:
                lines.append(f"    F{over_claim.index} OVER-CLAIM  {over_claim.quote[:110]}")
                if not over_claim.quote_found:
                    lines.append("        ^ the judge's quote is NOT in the answer text")
    return "\n".join(lines)


def format_control(run: ControlRun) -> str:
    """The known-bad control. A floor at 8/8, and it says so when it fails.

    `AC10` requires this seen red, so the failure output has to be worth reading:
    every missed case names the verdict that was expected, the verdict that came
    back, and the authored reason the case exists.
    """
    verdict = "PASS" if run.passed else "FAIL"
    lines = [
        f"known-bad control — judge {run.judge_model}{'  [WEAKENED PROMPT]' if run.weak else ''}",
        f"  {verdict}  {run.caught}/{run.total} authored bad answers caught",
        "  This is a FLOOR, not a proportion. A judge that catches three of the four",
        "  failure shapes cannot be trusted on the fourth, so 7/8 is not 0.875 -- it is a",
        "  judge with a known blind spot and a number that would hide it.",
        "",
    ]
    for outcome in run.outcomes:
        case = outcome.case
        lines.append(
            f"  {'CAUGHT' if outcome.caught else 'MISSED'}  {case.id:<30} {case.shape:<22} "
            f"({case.question_id})"
        )
        for expectation in case.must_catch:
            lines.append(f"    expected {expectation.render()}")
        for failure in outcome.failures:
            lines.append(f"    FAILED   {failure}")
        if not outcome.caught and case.why:
            lines.append(
                textwrap.fill(
                    case.why,
                    width=WIDTH - 6,
                    initial_indent="    why: ",
                    subsequent_indent="         ",
                )
            )
    lines.append("")
    lines.append(
        f"  cost  ${run.cost_usd:.4f} measured at the gateway over {run.total} calls, "
        f"{run.tokens} tokens"
    )
    if run.json_validation_retries:
        lines.append(
            f"  NOTE  {run.json_validation_retries} generation(s) rejected as invalid JSON "
            "and retried"
        )
    return "\n".join(lines)


def format_agreement(
    agreement: Agreement,
    *,
    kind: str,
    first: str,
    second: str,
    forced: int,
    partial: bool,
) -> str:
    """Agreement, its cluster-aware interval, and D11's floor applied.

    Two things this function refuses to let pass silently. It always prints the
    **forced units it excluded** and why, because an exclusion nobody can see is
    indistinguishable from a mistake. And it always prints the interval **kind**,
    because `wilson-over-clusters` means the cluster-robust estimator hit its
    degenerate boundary and the number is the conservative fallback, not the
    estimate.
    """
    lines = [
        f"{kind} — {first} against {second}",
        f"  {agreement.render()}",
        f"  agreed {agreement.agreed} of {agreement.units} field-verdicts "
        f"in {agreement.clusters} questions",
    ]
    if partial:
        lines.append(
            "  !! PARTIAL — computed over the units labelled so far, which are not a random"
        )
        lines.append(
            "     subset. A progress check only: no number here may be quoted as a result."
        )
    lines.append("")
    lines.append("  by field — D5's prediction 2 lives here")
    for field, agreed, units in agreement.by_field:
        lines.append(f"    {field:<10} {agreed}/{units} = {agreed / units:.3f}")
    lines.append(
        "    Prediction 2 expects `asserted` LOWER than `stated`. Higher was pre-registered"
    )
    lines.append(
        "    as a sign the prompt may be collapsing the two questions -- but a verdict class"
    )
    lines.append("    that is almost all negatives is consistent for free, so read the counts.")
    lines.append("")
    lines.append(
        f"  EXCLUDED  {forced} units under refused answers. A refusal states nothing, so both"
    )
    lines.append("            sides are forced to the same verdict and the units measure nothing.")
    lines.append(
        "            Pooling them would hand this figure ~0.16 of agreement for free, and a"
    )
    lines.append(
        "            judge agreeing on only ~0.83 of the real units would clear the 0.85 floor."
    )
    if agreement.disagreements:
        lines.append("")
        lines.append(f"  disagreements ({len(agreement.disagreements)}), named not just counted:")
        for one in agreement.disagreements:
            lines.append(
                f"    {one.question_id:<44} {one.unit} {one.index} {one.field}: "
                f"first said {str(one.value).lower()}"
            )
    lines.append("")
    if kind.startswith("judge-human"):
        if agreement.rate >= AGREEMENT_FLOOR and not partial:
            lines.append(
                f"  VERDICT   {agreement.rate:.3f} is at or above D11's {AGREEMENT_FLOOR:.2f} "
                "floor, so the"
            )
            lines.append(
                "            judged metrics become publishable — with branch coverage beside"
            )
            lines.append("            groundedness, never either alone.")
            lines.append(
                "            Report it against judge SELF-consistency, not against 1.0: the"
            )
            lines.append("            judge's own reproducibility is the ceiling on this number.")
        else:
            lines.append(
                f"  VERDICT   {agreement.rate:.3f} is BELOW D11's {AGREEMENT_FLOOR:.2f} floor. "
                "Groundedness stays"
            )
            lines.append(
                "            WITHHELD, and the slice-6 decision rule says slice 6 is the judge."
            )
    else:
        lines.append("  This is the CEILING on judge-human agreement, not a substitute for it: two")
        lines.append("  judge runs that disagree with each other cannot both match a human.")
    return "\n".join(lines)


def format_offline_refusals(run: OfflineRefusalRun) -> str:
    """The refusal arithmetic recomputed from a frozen file, with its exclusions.

    Prints the same figures `format_refusals` does and three things it cannot: the
    file they came from, the commit that file was answered at, and every answer the
    file holds that the golden set no longer asks. The last is the one that earns
    this function -- a frozen sample and a living golden set diverge the moment a
    label moves, and an exclusion nobody can see is indistinguishable from a
    mistake.
    """
    metrics = run.metrics
    lines = [
        f"refusal behaviour — RECOMPUTED OFFLINE from {run.source}",
        f"  {run.cell}, {run.model}, reasoning {'on' if run.reasoning else 'off'}   "
        "(DIAGNOSTIC, never a headline)",
        "  No model was called and no money was spent: every figure below is arithmetic",
        "  over answers that were already paid for.",
        "",
        f"  recall     {metrics.recall.render():<28} correct refusals / refusal population",
        f"  precision  {metrics.precision.render():<28} correct refusals / all refusals emitted",
    ]
    lines.extend(_restricted_precision_lines(metrics))
    for kind, interval in metrics.by_kind:
        lines.append(f"  {kind.value:<10} {interval.render()}")
    if metrics.missed:
        lines.append(f"  ANSWERED anyway ({len(metrics.missed)}): {', '.join(metrics.missed)}")
    if metrics.wrongly_refused:
        lines.append(
            f"  WRONGLY refused ({len(metrics.wrongly_refused)}): "
            f"{', '.join(metrics.wrongly_refused)}"
        )
    lines.append("")
    lines.append(f"  scored over {len(run.scored)} refusal questions")
    if run.not_in_golden:
        lines.append(
            f"  EXCLUDED ({len(run.not_in_golden)}): {', '.join(run.not_in_golden)} — answered in"
        )
        lines.append(
            "  this file, no longer in the golden set. The answer is real and was paid for;"
        )
        lines.append("  it is left out because the question is not asked any more, NOT because it")
        lines.append("  scored badly. Removing an entry moves this number and that is the point.")
    if run.dirty_provenance:
        lines.append(
            f"  !!         answered at commit {run.source_commit or '(none recorded)'} — a tree,"
        )
        lines.append(
            "  not a commit. These answers are not reproducible from a clean clone; the file"
        )
        lines.append("  that holds them is committed instead (ADR-0011).")
    return "\n".join(lines)

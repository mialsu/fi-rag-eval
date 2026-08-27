# ADR-0007 — the published headline moves to `lemma-reasm/0`

- **Date:** 2026-08-27
- **Status:** accepted

## Context

Since slice 1 the README has published the `snowball/0` control cell: Postgres
`to_tsvector('finnish', ...)` at default `ts_rank` normalisation, deliberately the weakest sensible
baseline. Slice 3 added three lemmatising analysers beside it and measured `lemma-reasm/1` at 0.857
against the control's 0.762, and the headline **did not move** — recorded at the time as
"promoting one cell of twelve after seeing all twelve, on 21 questions, with no held-out slice",
which is golden-set leakage in a new costume.

That refusal was right, and slice 4 showed *why* it was right in a way slice 3 could not:

> Two cells are scored on the **same** questions, so comparing them is a **paired** test. Only the
> questions the two cells disagree about carry information, and the exact McNemar test needs
> **six** of them flipping one way for p<0.05 — at any N.

At N=21 the best cell had three failures. Fixing *every remaining miss* would have given d=3,
p=0.25. So "0.857 beats 0.762" was **never a claim that instrument could support at any effect
size** — the absolute ±0.18 interval slice 3 reasoned with was the wrong statistic, and the right
one is harsher.

Slice 4 grew the set to 50 questions across two authorities specifically to buy that power. It
worked. Measured at N=50, k=5:

| | complete-set recall@5 | leakage | unreachable | out-ranked |
|---|---|---|---|---|
| `snowball/0` (control) | 0.680 | 0.332 | 6 | 11 |
| **`lemma-reasm/0`** | **0.820** | 0.550 | **0** | 10 |

Paired against the control: **9 discordant questions, 8 of them favouring `lemma-reasm/0`, exact
two-sided McNemar p = 0.039.** The bar this project set for calling an improvement real is met,
for the first time in its history.

## Decision

**The published headline moves from `snowball/0` to `lemma-reasm/0`.** `evaluate.PUBLISHED` is the
single place that decides it, `report.compare` fails the gate when it moves without a re-record,
and the re-baseline lands as its own commit.

Chosen over the tied `lemma-reasm/1` (also 0.820) because normalisation 0 is the `ts_rank` default
and slice 4 **retracted** slice 3's finding that length normalisation helps the split analyser — at
N=50 the two are neutral against each other, so the default wins on having one fewer moving part.

## Rejected alternatives

- **Keep `snowball/0`.** Rejected, but it was a real option and it costs something to give up. It
  preserves future power: the control fails 16 of 50, so `f=0.320` leaves room for a *small* later
  improvement to reach d≥6, while the new cell fails 9 and demands a bigger one. It also keeps a
  deliberately dumb baseline stable across every slice. Rejected because the README would go on
  publishing a number 0.140 below what the project measurably achieves, on a harness whose entire
  purpose is that its numbers can be trusted — and the debt entry would enter a fourth slice open.
- **Decide when the reranking slice lands**, moving the headline once with those numbers in hand and
  spending one re-baseline instead of two. Rejected because the next slice would then be gated
  against a baseline nobody should be quoting: a genuine regression in the cell that actually
  matters could pass the gate while the published cell sat still.
- **Publish `lemma-reasm/1` (0.820, MRR 0.595) instead.** Rejected: it ties on the headline and
  wins only on MRR, a diagnostic, and its normalisation is the one whose justification slice 4
  retracted. Choosing it would be picking the higher of two tied numbers on a secondary metric —
  the exact behaviour `PUBLISHED` exists to prevent.
- **Publish the best cell automatically**, whichever it is. Rejected permanently and not just here.
  A headline that migrates to whatever scored best today is how a project ends up publishing its
  own tuning noise, and it would have published 0.857 at N=21 on p=0.25 evidence.
- **Raise `k` from 5 to 10.** Rejected as buying the number rather than earning it. Six of the ten
  remaining misses sit at rank 6–10, so `k=10` would lift the headline substantially and change
  nothing about the system. `k` is a product constraint — how many citations a reader tolerates —
  not a tuning knob. (Reporting recall@10 as a *diagnostic ceiling* remains legitimate and is not
  what this rejects.)

## Consequences

**Easy.** The published number is now the best configuration the project can defend, and the
defence is a p-value rather than a preference. The slice-3 debt entry closes.

**Hard — and both costs were accepted before the change, not discovered after it.**

1. **The published leakage figure rises 0.332 → 0.550, and this is not the golden set getting
   easier.** It is the same 50 unedited questions read by a different analyser: words snowball
   stems apart are one lexeme under lemmatisation, so the metric finally sees overlap a human eye
   always could. The leakage gate is per cell against its own recorded value precisely so this is
   not waved through — `lemma-reasm/0`'s leakage is unchanged at 0.550 and is still defended from
   rising. **Anyone comparing the new published leakage to the old one is comparing two analysers,
   not two golden sets, and the README must say so where the number appears.**
2. **The instrument spends power.** The new cell fails 9 of 50 rather than 16, so the N target for
   detecting a fix that closes half the remaining misses rises from ~51 to ~84. The next
   improvement has to be bigger to register. That is the true price of publishing a better number,
   it was quantified in the slice-4 spec before the decision, and the held-out-slice trigger at
   N≈85 is now doing double duty.

**Living with.** Two numbers are now in the project's history for the same corpus — 0.762 (N=21,
`snowball/0`) and 0.820 (N=50, `lemma-reasm/0`) — and neither the population nor the cell is shared
between them. No document may present them as a trend. What *is* comparable, and is pinned by a
test: over the original 21 questions alone this cell still scores exactly 18/21, unchanged since
slice 3.

# ADR-0011 — the labelling protocol is blind, and the sample is committed rather than regenerated

- **Date:** 2026-08-28
- **Status:** accepted

## Context

Tracer slice 5 asks the Owner for **168 hand labels** — the single most expensive resource this
project has, and the one that cannot be bought back. (168, not the 199 units D3 counts: 31 of
them are forced and are excluded, which is decision 6 below and is itself one of the decisions
that had to be made first.) Three decisions had to be settled before a labelling
surface existed, because both are irreversible in the way that matters: a label written under a
biased procedure is not a weaker label, it is **worthless**, and nobody can tell by looking at it.

What was true in the code when this was decided:

1. **The judge's verdicts already exist** for all 199 units, twice over
   (`eval/runs/judge-verdicts-{A,B}-8c6a0d1.json`), and the judge's self-consistency is measured at
   **0.964 [0.93, 1.00]** once the forced units of decision 6 are taken out (0.975
   with them pooled in, which is the figure tracer slice 4 first published and this ADR supersedes). So the labelling surface *could* show a verdict, or a
   stability flag derived from two.
2. **The answers being labelled live in a gitignored file** whose own `commit` field reads
   **`4b75dfd-dirty`** — produced from an uncommitted tree. ADR-0010's consequences section
   suggested tracer slice 5 should re-freeze from a clean commit.
3. **The answerer is non-deterministic.** `temperature=0` becomes `1e-8` at Groq (ADR-0008),
   measured on the judge in tracer slice 4 and on the answerer in tracer slice 3. Re-running the
   answer phase does not reproduce a run; it makes a new one.
4. **`judging.load_run` reads a run file** and already validates it, so a frozen sample needs no
   new reader.

## Decision

### 1. Labelling is BLIND. The surface never shows the judge's verdict, or anything derived from it

The Owner sees the question, the retrieved excerpts, the answer text, and the enumerated claim.
Nothing else. Not the judge's verdict, not a suggested answer, not a confidence, and **not a
stability flag**.

The stability flag is the part worth spelling out, because it was proposed as a *labelling aid* and
is rejected as one. Telling the Owner *"the judge coin-flips on this unit"* does not reveal which
way the judge went — but it reveals **where the judge was uncertain**, which makes the Owner think
harder on exactly that subset. Agreement would then be measured on a population whose labelling
effort was allocated by the judge's own uncertainty, and the comparison is no longer a comparison.

Stability is a **diagnostic applied afterwards**: *of the units where the judge was unstable, the
human agreed with run A on n of m.* That question is worth answering and costs nothing to defer.

### 2. One pass per unit, both fields together, grouped by question

Each branch is labelled `stated` and — when stated — `supported`, in one visit. Units are ordered by
question in golden-set order, so the answer is read once per question rather than once per field.

*This reverses guidance given earlier in tracer slice 5's shaping*, which proposed labelling every
`stated` first and every `supported` second. That advice confused an **analysis** priority (`stated`
is the field branch coverage rests on, so it is where a judge error costs most) with a **procedure**.
Two passes would make the Owner read all 50 answers twice for no measurement gain.

### 3. Labelling is resumable, and every label is written the moment it is made

168 units is one to two hours; it will not happen in one sitting. The label file is rewritten
atomically after each unit and already-labelled units are skipped on restart. A protocol that loses an hour of
labelling to a closed terminal is a protocol that does not get finished.

### 4. The frozen sample is COMMITTED, not regenerated — and `eval/frozen/` is not gitignored

`eval/frozen/sample-tracer5.json` holds the 64 answer texts verbatim, with their provenance stated
inside the file: `answered_at_commit: 4b75dfd-dirty`, `frozen_at_commit`, and an explicit
`provenance_is_a_tree_not_a_commit: true`.

**Re-answering from a clean commit was considered and rejected**, reversing ADR-0010's suggestion.
Because the answerer is non-deterministic, a re-answered run contains *different answers* — which
means it would move **refusal recall 0.857 and precision 0.632**, both already published from
tracer slice 3. That is re-publishing two measured numbers to improve a provenance string, and it
would break the property ADR-0010 counted as a benefit: that the judged metrics and the published
refusal metrics describe **the same 64 answers**.

Committing the artifact repays the confession more completely and for nothing: the sample becomes
reproducible **by inclusion** rather than by regeneration, which is what *"human labels are written
once against a frozen, committed set of answer texts"* meant in `SPEC-slice-5` all along.

### 5. The filename carries no commit

`sample-tracer5.json`, not `sample-f7dff8d.json`. Its ancestor
`answers-tracer3-4b75dfd.json` named the commit **before** the one that produced it and has already
misled a reading of this project once. Provenance belongs in fields that can be checked, not in a
filename that cannot.

### 6. Units under a refused answer are neither labelled nor counted

A refused answer states nothing. `judge.parse_verdicts` already forces the judge to *not stated* on
every branch and *not asserted* on every forbidden item of one, and any honest human labels them the
same way. Both sides are therefore **structurally forced to agree**, and the units measure nothing.

Measured on the frozen sample: **31 of the 199 units sit under the 7 refused answers.** Pooling them
hands the judge **0.156 of agreement before a word is read** — and the consequence that decides it:
solving `(x·168 + 31) / 199 = 0.85` gives **x = 0.827**, so **a judge agreeing on only 0.827 of the
informative units would clear D11's 0.85 floor** on the strength of units nobody judged.

So the labelling covers **168 units**, agreement is computed over those, and the excluded count is
printed on every agreement table. An exclusion nobody can see is indistinguishable from a mistake.

**This also corrects a figure this project already published.** Tracer slice 4 reported judge
self-consistency of **0.975 over 199 units** — computed with the forced units pooled in, before this
decision existed. Recomputed over the informative units it is **0.964 [0.93, 1.00]** (0.970 counting
a branch as one unit). The corrected figure is the one to quote; the ceiling is clear of the floor
either way, so this changes the number and not the plan.

## Rejected alternatives

- **Show the judge's verdict and let the Owner confirm or correct it.** Far faster — most units
  would be a keystroke — and it is how almost every labelling tool works. Rejected because it makes
  agreement meaningless: a human confirming a model's verdict measures the human's willingness to
  disagree, not the model's accuracy, and it biases in the direction that flatters the number. This
  is the single most dangerous shortcut available in this slice.
- **Show a stability flag as a labelling aid** — see decision 1. Weaker leakage than showing the
  verdict, same class of error, and unnecessary.
- **Label a stratified subsample** — e.g. every unstable unit plus a random remainder. Cheaper in
  Owner hours and it targets the informative units. Rejected: D3 already priced a hand-picked
  subsample at **±0.17** and called it *"the statistic ADR-0007 retracted"*, and stratifying on the
  judge's own uncertainty is decision 1's bias with extra steps.
- **Re-answer from a clean commit before labelling** — ADR-0010's own suggestion, and it buys real
  provenance. Rejected in decision 4: it costs $0.76, ~50 minutes, and two published numbers.
- **Two passes, `stated` then `supported`** — see decision 2. Rejected on Owner minutes.
- **A pre-filled worksheet the Owner edits in an editor** instead of an interactive loop. Simpler to
  build, trivially testable, no TUI. Rejected because 199 rows of YAML invite a misaligned edit that
  attaches a label to the wrong claim, and nothing would catch it — the failure would look like
  disagreement. The interactive loop shows one unit with its own context and cannot misalign. The
  *core* is still pure and tested; only the driver is interactive.
- **Pool the forced units anyway, for a bigger N** — 199 looks better than 168 and D3 quotes
  199. Rejected in decision 6 on arithmetic: they are free agreement, and free agreement moves a
  below-floor judge to publishable.
- **Let the judge label and skip the human entirely.** Rejected before it can be proposed: it is
  what `CLAUDE.md` calls *"a judge that agrees by default, making groundedness look perfect"*, and
  it is the reason agreement is a publishability gate rather than a diagnostic.

## Consequences

**Easy.** The Owner's labels are durable: attached to a committed artifact, valid for as long as the
file exists, and usable by any later slice. Agreement is computed by the already-tested
`metrics.unit_agreement` with its cluster-aware interval. The blind protocol means the resulting
number is defensible against the obvious attack — *"did the human just agree with the model?"*

**Hard.** Blind labelling is slower per unit than confirm-or-correct, and there is no way to buy
that back. The provenance of the *answers* stays a tree rather than a commit, and every judged table
keeps printing a `!!` line saying so — accepted rather than fixed, with the reason recorded above.
`eval/frozen/` now contains committed model output, which is a first for this repository.

**Lived with.** The judge is still validated on the same 50 questions it scores; there is no
held-out slice to draw a validation set from, which was confessed at shaping time and is the second
independent argument for the N≈85 tranche. And the Owner is one labeller: **inter-annotator
agreement is unmeasurable here**, so "judge–human agreement 0.9" means agreement with *this* human,
and no part of this protocol can tell you whether a second person would have labelled the same way.

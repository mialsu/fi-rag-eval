# ADR-0012 — branch coverage is the published answer-layer headline, and groundedness is its companion

- **Date:** 2026-08-31
- **Status:** accepted
- **Amends:** D11 in `specs/SPEC-slice-5-answering-and-judge.md`; supersedes its choice of headline
  and leaves its pairing rule and its 0.85 agreement floor intact.

## Context

D11 named **groundedness** the published answer-layer number, with branch coverage as a mandatory
companion, and pre-registered a judge–human agreement floor of 0.85 below which the value is
withheld. It considered branch coverage as the headline and rejected it for being judge-dependent.

Tracer slice 4 then measured both, twice, over the same 50 frozen answers:

| | run A | run B | complete retrieval | incomplete retrieval |
|---|---|---|---|---|
| groundedness | 1.000 | 0.983 | **1.000** | **1.000** |
| branch coverage | 0.472 | 0.480 | **0.574** | **0.042** |

Groundedness has **no variance on this answerer**. Its denominator is branches *stated*, and
`qwen/qwen3.6-27b` never states a branch it cannot cite — it drops the branch instead. So the
metric is pinned at its ceiling whether retrieval succeeded or failed, and every question it was
supposed to answer is answered by branch coverage instead.

Two further facts were on the table when this was decided:

1. **The argument D11 used to reject branch coverage does not separate the two.** Groundedness is
   judge-dependent in exactly the same way — the same judge, the same call, the same two fields.
2. **Prediction 5 was registered over groundedness** and is therefore void as written. It is *"answer
   failures are dominated by retrieval, not generation"*, and it is the prediction that decides
   whether slice 6 builds the reranker. Branch coverage answers it decisively: **0.574 against
   0.042**, or 0.598 against 0.111 excluding refusals.

## Decision

### 1. Branch coverage is the published answer-layer headline. Groundedness is printed beside it

Inverted, not replaced. The *order* is the decision: the first number under `PUBLISHED` is the one
that gets copied into a README, quoted in a conversation, and remembered. A headline of 1.000 that
reads identically whether retrieval worked or not tells a reader nothing about this system, and it
will be quoted anyway — which is the whole failure mode.

Pinned by a test that asserts the order, not by this paragraph.

### 2. D11's pairing rule survives unchanged, and it is the half that was always load-bearing

Neither figure is ever printed without the other, in the published block or the withheld one.
Groundedness is gameable by saying less; branch coverage is gameable by saying everything. Only the
pair is a metric. A test asserts the two names appear an equal number of times on every rendering
path, so no branch of the report can emit a lone figure.

### 3. The withheld block withholds BOTH, by name

Both are judge-dependent, so an unvalidated judge disqualifies both. The old wording — *"PUBLISHED
nothing. Groundedness is WITHHELD"* — would have read, after this inversion, as though the headline
were exempt from the floor.

### 4. The agreement floor stays at 0.85, and stays pre-registered

Nothing measured here bears on the floor. Moving it in the same breath as moving the headline would
make two changes to the publication rule at once and leave neither attributable.

### 5. Prediction 5 is recorded VOID AS WRITTEN, with its substance held on substituted evidence

The reranker's decision rule **fires**, and the record says on what: branch coverage, not the
statistic that was registered. Slice 6's spec must pre-register its fix size against branch
coverage. The 6-discordant-question bar is unchanged.

This is the **third** pre-registered statistic in this project to turn out to be the wrong one while
its question was answerable — after the ±0.18 absolute interval and the ±0.13 standard error. The
pattern is now specific enough to name: **this project keeps registering a statistic before knowing
whether it has variance on the population it will be measured over.** Slice 6 registers its
statistic *and* the evidence that it varies.

## Rejected alternatives

- **Keep groundedness as the headline (D11 as written).** Costs nothing, changes no code, and keeps
  a pre-registered decision pre-registered — which has real value in a project whose whole claim is
  that it does not move its own goalposts. Rejected because the number carries no information about
  this system: 1.000 in both retrieval strata is not a measurement of the answerer, it is a
  measurement of the answerer's *refusal to over-state*, which refusal precision already covers.
  Publishing it as the headline would be publishing a constant.
- **Publish neither as a headline; leave recall@5 as the project's only one.** Defensible, and
  tempting while judge–human agreement does not exist. Rejected because the answer layer *will*
  publish something once tracer 5's labels land, and deciding which number that is under the
  pressure of having a green run is exactly when the decision gets made badly. Deciding it now, with
  nothing publishable either way, is free.
- **Retire groundedness entirely.** It saturates, so it looks like a dead metric. Rejected: it
  saturates *on this answerer*. A future answerer that states branches it cannot cite would move it
  immediately, and that is precisely the failure it was chosen to catch. It stays as the companion,
  where a change in it is a loud signal.
- **Redefine groundedness over branches REQUIRED so it stops saturating.** This was already
  rejected once, on 27 Aug 2026, when `CONTEXT.md` contradicted itself: a required-branch denominator
  blends *did it say enough* with *was what it said supported*, and branch coverage already measures
  the first. Re-rejected for the same reason. The fix for a saturated metric is not to redefine it
  into a different one wearing its name.
- **Score prediction 5 as CONFIRMED on branch coverage.** Rejected as dishonest bookkeeping: a
  prediction registered over one statistic is not confirmed by another, however strongly they point
  the same way. Void as written, substance carried on named substituted evidence, and the
  substitution is the Owner's accepted risk rather than a silent rewrite.

## Consequences

**Easy.** The published block now leads with a number that moves: 0.574 against 0.042 across
retrieval strata. A reader who quotes only the first line still learns something true about the
system. The change is one ordering in one function and is pinned by three tests.

**Hard.** A pre-registered decision was changed after seeing the data, which is the shape of exactly
the error this project exists to refuse. What makes it survivable rather than laundering: the change
is to *which* metric leads, not to a threshold, not to a population, and not to a value; it is
recorded here with the measurement that caused it; and it makes the reported number **worse-looking**
(0.472 rather than 1.000), which is the opposite direction from goalpost-moving. Anyone auditing this
should still count it as a spec delta and treat the next such change with more suspicion.

**Lived with.** Nothing is published today either way — judge–human agreement does not exist until
the Owner's 168 hand labels do, and D11's floor gates both figures. This ADR decides what will be
published *when* that lands, deliberately in advance of the run that would otherwise decide it.

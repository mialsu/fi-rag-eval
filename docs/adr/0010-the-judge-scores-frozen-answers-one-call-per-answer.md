# ADR-0010 — the judge scores frozen answers, one call per answer, validated by a control it must not pass by accident

- **Date:** 2026-08-28
- **Status:** accepted

## Context

`SPEC-slice-5` D11 owed this ADR and named it in three places without writing it. Tracer slice 4
builds the judge, and four things had to be settled before a prompt could be written, because a
judge prompt is the hardest artifact in this project to change later: **tracer slice 5's hand
labels are written against whatever the judge was asked**, so a definition baked in here is baked
into 199 human labels.

What was true in the code when this was decided, verified rather than assumed:

1. **The units exist and there are exactly 199.** 125 `required_branches` + 74 `forbidden` across
   the 50 answerable questions in `corpus/golden/*.yaml`, counted. D3's "up to 199" is not an
   estimate; it is the number.
2. **The judge model is already reachable.** `answer.JUDGE = "openai/gpt-oss-120b"`
   (`answer.py:51`), served by the proxy at `litellm.config.yaml:29-32`. A different model
   *family* than the answerer, per `CONTEXT.md:66` and ADR-0008.
3. **A complete, paid-for run of 64 answers is on disk** —
   `eval/runs/answers-tracer3-4b75dfd.json`, produced by tracer slice 3: every answer text,
   citation list, retrieved address set and per-call usage. It is the run whose refusal behaviour
   is already published in the spec.
4. **The four metric definitions are settled and were settled the hard way.** `CONTEXT.md:44,46,47`
   fix groundedness over branches **stated**, branch coverage over branches **required**, and
   over-claim over **forbidden** items — a contradiction that was live in `CONTEXT.md` for a day
   and was resolved on 27 Aug 2026 rather than reinterpreted.
5. **One definition in that set was measured to be wrong**, and this ADR is where it changes: *"a
   refusal emitting any citation is a defect, checked arithmetically"* (`SPEC-slice-5:665`,
   enforced at `metrics.py:445`). Tracer slice 3 found two, and both use the citation for *"here
   is what the excerpts do say instead"*.

## Decision

### 1. The judge scores a frozen answer file, and never generates the answers it scores

`fi-rag-eval judge <run.json>` reads a run written by `answer --all --out` and judges it. The judge
and the answerer are never in the same command.

Three reasons, in the order they matter:

- **A judge prompt is developed by iteration, and iteration needs a fixed input.** `temperature=0`
  becomes `1e-8` at Groq (ADR-0008), so re-answering between two judge prompts means a changed
  verdict cannot be attributed to the prompt. Freezing the input is what makes the prompt
  *measurable* rather than merely changeable.
- **The answers already exist and are already published.** Judging the tracer-3 run means the
  judged metrics and the published refusal numbers describe **the same 64 answers**, so the two
  halves of the answer layer cannot disagree about which run they are talking about.
- **Tracer slice 5 needs a file-reading judge anyway.** The frozen agreement sample *is* a file
  like this one. Building the judge any other way would make tracer 5 a re-architecture instead of
  a labelling job.

### 2. The unit of judgement is the claim, and one call carries every unit of one answer

Per D3 and `CONTEXT.md:43`, a claim is one hand-enumerated **required branch**. One judge call per
answer returns, in a single envelope:

- for each required branch: `stated` (did the answer assert this branch) and `supported` (does the
  chunk it is attached to actually carry it);
- for each forbidden item: `asserted`.

199 units in 50 calls. The judge is never asked to *find* the units — they are handed to it,
numbered, from the golden entry. It answers narrow yes/no questions about a fixed list, which is
what keeps its task stable run-to-run and what makes a hand label comparable to it at all.

### 3. Citation checking splits in two, and only half of it involves the judge

- **Address validity is arithmetic.** Is each emitted citation a parseable chunk address, and is it
  in the set that question actually retrieved? No judge, no network, no floor. This is the answer
  layer's most trustworthy output, on the same logic that makes retrieval metrics win arguments.
- **Claim support is judged.** Does the cited chunk carry the claim it is attached to? That is
  `supported` above, and it is the same question for an answer and for a refusal.

### 4. A refusal's citations: the "any citation is a defect" rule is NARROWED, not kept

Replaced by two checks, both arithmetic:

- **DEFECT — a refusal citing an address outside its own retrieved set.** A refusal asserts the
  retrieved context does not answer the question; pointing outside that context while doing so is
  unambiguously wrong, whether the address is hallucinated or belongs to another authority.
- **DIAGNOSTIC, not a defect — a refusal citing a chunk it did retrieve.** Counted and named, and
  neither direction is wrong.

**Why the old rule goes.** Under this project's own definition of Citation — *"a pointer from a
claim in the answer to the chunk that supports it"* (`CONTEXT.md:40`) — both observed cases are
**correct** citations; the claims they support are simply not answers to the question. Pirkanmaa
`7 §` genuinely says kerbside collection can be joined from outside the area where access allows,
and Lounais-Suomi `1 §` genuinely carries the scope clause. The rule as written therefore punishes
the *better* refusal: *"the excerpts only cover X `[#7]`, not your question"* is both more useful
and **more auditable** than a bare "I don't know", so a defect label on it creates pressure toward
less checkable output. For an instrument, that is backwards.

**What this does not change: nothing that was published.** Refusal recall 0.857 and precision 0.632
are computed from the `refused` field alone and are untouched. Only the reported line changes, plus
one new arithmetic check that currently fires zero times. This is a change to a **definition**,
recorded as a spec delta — never a correction applied to a result.

### 5. The judge is validated by a control before it is trusted on anything

Eight hand-authored bad answers (`corpus/control/known-bad.yaml`), four failure shapes × two
authorities: a wrong citation, a fabricated claim, a flattened conditional, a cross-authority
answer. Each control case **names the unit verdict that must catch it**, so the control tests the
judge's specific discrimination rather than its general disapproval.

The bar is **8/8** and it is a floor, not a proportion — a judge that misses one of four shapes
cannot be trusted on the shape it missed, regardless of its score on the others. `judge --control`
exits non-zero below 8/8. Seen red by **weakening the prompt**, because a control that has never
failed is decoration (PRINCIPLES #2).

### 6. Judge instructions in English; every piece of content in Finnish

The corpus, the questions, the answers and the enumerated claims reach the judge verbatim in
Finnish. The *instructions* — what `stated` means, what `supported` means, the envelope — are in
English. `CLAUDE.md`'s "copy is in the user's language" governs user-facing copy; a judge prompt is
harness vocabulary, and `gpt-oss-120b` follows English instruction-following more reliably. This is
a knob agreement can be re-measured against if it looks wrong, and it is recorded so a later
session finds a decision rather than an accident.

### 7. Tracer slice 4 computes the judged metrics and publishes none of them

D11 forbids groundedness appearing without judge–human agreement beside it, and agreement does not
exist until tracer slice 5. So the four judged metrics are computed and printed marked
**`DIAGNOSTIC — judge unvalidated, agreement NOT MEASURED`**, with the published value withheld.
This exercises AC12's machinery one tracer early, on the strongest possible case: agreement that is
*absent* rather than merely low.

## Rejected alternatives

- **Judge live, inside `answer --all`** — one command, one run, nothing to freeze or pass around,
  and the natural shape for tracer 6's pipeline. Rejected because it makes every judge-prompt
  iteration cost a full 50-minute, $0.76 answer run, and because the answerer's non-determinism
  would then be inside the loop being used to evaluate the prompt. Tracer 6 may compose the two
  commands; it must not merge them.
- **Whole-answer judging** — one verdict per answer, 50 units, far cheaper to label by hand.
  Rejected in D3 and rejected again here: it cannot localise *which* branch was dropped, which is
  the entire reason ADR-0003 built the branch model, and it would make branch coverage
  uncomputable.
- **One judge call per unit** — 199 calls, each maximally focused, no risk of the judge's attention
  being spread across a long list. Rejected on cost and on a subtler ground: a per-unit call cannot
  see the other branches, so it cannot tell "this branch is stated" from "a neighbouring branch is
  stated and this one was folded into it", which is exactly the flattening failure over-claim
  exists to catch.
- **Let the judge enumerate the claims itself** — no hand labelling, scales to any corpus.
  Rejected because the denominator would then be set by the model under measurement's sibling, and
  it would move every run. `CONTEXT.md:43` chose hand enumeration precisely to make the
  groundedness denominator explicit rather than inferred.
- **Keep "any citation on a refusal is a defect"** — internally tidy: `refused: true` with a
  non-empty `citations` array is a contradiction in a machine-readable envelope, and a reader may
  mistake a cited refusal for a partial answer. Rejected as a surface concern; the harness is the
  product, and the measured evidence says the rule labels the better output as worse.
- **A same-family judge (`qwen`), or the answerer judging itself** — cheaper and simpler.
  Rejected in ADR-0008 and not reopened: a same-family judge shares the answerer's blind spots and
  rubber-stamps the fabrications it exists to catch.
- **A judge prompt entirely in Finnish** — symmetric with the product, and arguably better at
  reading Finnish nuance. Genuinely uncertain, and rejected only on instruction-following
  reliability. Recorded as re-measurable rather than settled: if agreement lands low in tracer 5,
  this is the first knob to try.
- **Publish groundedness in tracer 4 with a caveat in prose** — the numbers exist, and withholding
  them feels like false modesty. Rejected because it is exactly the failure the recall/leakage rule
  was written to prevent, one layer up: a number published with a caveat gets quoted without it.

## Consequences

**Easy.** The judge prompt can be iterated for the price of judge calls alone, against an input
that cannot shift under it. Tracer 5 becomes a labelling job. Address validity gives the answer
layer one number that needs no judge, no floor and no network — usable in `make eval` whenever
tracer 6 wants it. The control makes "the judge works" a claim with an exit code behind it.

**Hard.** The judged metrics now describe a run recorded in a **gitignored** file
(`eval/runs/`), so they are not reproducible from a clean clone — the retrieval half's central
property, given up on the answer half. Tracer 5's frozen sample is the deliberate committed copy
that partly repays this, and it is confessed rather than hidden. Worse: that file's own `commit`
field reads **`4b75dfd-dirty`**, so its provenance is "the tree that became `8c6a0d1`" rather than
a commit — tracer 5 should re-freeze from a clean commit or record why it did not.

**Lived with.** The judge is validated on the same 50 questions it scores; there is no held-out
slice to draw a validation set from (already confessed in `SPEC-slice-5`, and the second
independent argument for the N≈85 tranche). And the 8-case control is a floor test at n=8: it can
prove the judge catches four named shapes, and it cannot estimate how often the judge is right in
general. Only judge–human agreement can do that, which is why nothing is published until it exists.

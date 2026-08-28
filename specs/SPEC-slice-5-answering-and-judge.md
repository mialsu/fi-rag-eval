# SPEC — slice 5: the answering layer and its judge

**Status:** shaped 27 Aug 2026 after `/grill-with-docs`. **Awaiting the Owner's explicit go. No
code yet.**
**Weight:** Standard, with Full's paperwork — three ADRs, because three of these decisions are
hard to reverse and one of them spends money.
**Decided by the Owner, against two pre-registered rules that both fired and neither of which
pointed here.** Slice 4 pre-registered: `< 4` synonym-caused zero-overlap misses means the vector
layer must be re-argued from evidence; and prediction 2 refuted means slice 5 is a golden-set
audit. Both conditions held. Neither nominated the answering layer. The Owner chose it on the
evidence below, and the two rules are left standing where they are — the argument that beat them
is recorded here, not by editing them.

---

## Why this slice, when the rules pointed elsewhere

There are four candidates and only one of them can succeed at N=50. That is the whole argument.

**The bar for claiming any retrieval improvement is now brutal, and the project set it itself.**
Comparing two cells is a paired test on the same questions, so the exact two-sided McNemar test
governs. The published cell (`lemma-reasm/0`, `evaluate.py:63`) fails **9 of 50**:

| discordant `d` | split | exact p | registers? |
|---|---|---|---|
| 6 | 6–0 | 0.031 | **yes** |
| 7 | 7–0 | 0.016 | **yes** |
| 7 | 6–1 | 0.125 | no |
| 8 | 7–1 | 0.070 | no |
| 9 | 8–1 | 0.039 | **yes** |

So a retrieval slice must fix **at least six of the nine remaining misses and break essentially
none of them.** Rerankers trade. That is not a bar to walk into voluntarily, and ADR-0007 already
quantified the cost of the ground the project chose to stand on: the N target for detecting a
half-of-misses fix rose from ~51 to ~84, leaving the set **underpowered by ~1.7x for its own
published cell.**

**The answering layer is the only candidate whose metrics do not need that power.** Groundedness,
branch coverage, over-claim rate, citation accuracy, refusal precision/recall and judge–human
agreement are all *first* measurements, not deltas against a baseline. N=50 gates none of them.
Every other candidate is a paired comparison against a nine-failure baseline.

**And its expensive input is already paid for.** `golden.py:70-71` has loaded `required_branches`
and `forbidden` since slice 1, ADR-0003's shape, validated at load and **scored by nothing**:

| Already in `corpus/golden/` | Lounais-Suomi | Pirkanmaa | Total |
|---|---|---|---|
| required claims | 70 | 55 | **125** |
| forbidden items | 41 | 33 | **74** |
| **judgement units** | 111 | 88 | **199** |

199 units, hand-written from the sources with a `label_source` naming the clause and sentence,
accruing zero value for four slices. That is the single largest unspent asset in the repo.

**It is also the only slice that can honestly close the debt that matters most.** The authority
hard filter is recorded **PARTIAL, never CLOSED**, and the reason is structural: `CLAUDE.md`
specifies *refusal*, and refusing needs a layer that answers. `CLAUDE.md`'s own verify-like-a-user
§3 — the project's stated #1 product failure mode — demands *"Ask a question answerable only from
municipality A's rules, with municipality B's filter set → it must refuse."* Today there is
nothing to score. Without this slice that entry enters a sixth slice open.

**The counter-argument, stated fairly.** The domain guard-rail says *"when answer quality and
measurement quality compete for a session, measurement wins."* This slice looks like answer work.
It is not: the deliverable is the **answer-metric instrument**, and the number that decides whether
the slice succeeded is **judge–human agreement**, not groundedness. If the answers are bad and the
instrument says so with a validated judge, this slice is a success.

---

## Problem

Half the instrument does not exist. `DESIGN.md:117-119` describes an answer layer judged by a
model whose agreement with hand labels is reported every run; `CONTEXT.md:35,44,46-48,59-60`
already defines every term for it. None of it is built. The retrieval half is measured across 12
cells with a paired significance test, and the answer half — where this project's named failure
mode actually lives, *"confident wrong answers"* — is unmeasured and unmeasurable.

The consequence is not that answers are bad. It is that **the hard filter, the thing the whole
design exists to guarantee, is unprovable.** A filter assertion at the retrieval layer proves
foreign chunks stay out of the top-k. It does not prove the system *refuses*, and the debt ledger
says so in as many words.

## Solution shape

One command, two phases. The retrieval phase is untouched: offline, deterministic, 50 questions ×
12 cells, zero-tolerance per-cell gate. The answer phase then runs on the **published cell only**
(`lemma-reasm/0`), generates an answer per question through LiteLLM against Groq, judges it with a
different-family model, and scores six metrics.

```
                        ┌─ retrieval phase (offline, unchanged, zero-tolerance) ──┐
make eval ─────────────►│  50 questions × 12 cells → recall / MRR / leakage       │
                        └────────────────────────────┬───────────────────────────┘
                                                     │  published cell top-5
                                                     ▼
   ┌─ answer phase (networked, floor-gated) ─────────────────────────────────────┐
   │  50 answerable + 14 refusal ─► answerer  gpt-oss-20b   (structured JSON)    │
   │                                     │                                      │
   │                                     ├─► arithmetic: citation address        │
   │                                     │   validity, refusal precision/recall  │
   │                                     │   (NO judge involved)                 │
   │                                     ▼                                       │
   │                                judge  llama-3.3-70b  (1 call per answer,    │
   │                                     │   199 unit verdicts)                  │
   │                                     ├─► groundedness, branch coverage,      │
   │                                     │   over-claim, citation support        │
   │                                     ▼                                       │
   │  frozen labelled sample ────────► judge ─► judge–human agreement            │
   │                                              │                              │
   │                                              └─► < 0.85 ⇒ groundedness is   │
   │                                                  DIAGNOSTIC, not published  │
   └──────────────────────────────────────────────────────────────────────────────┘
```

Everything reaches Groq through a **LiteLLM Proxy running in `compose.yaml`** beside Postgres, so
the gateway's per-key budget is a real enforcer of the cost ceiling rather than a demo.

---

## Decisions

Eleven, each with the alternative it beat. D7, D9+D10 and D4+D5 get ADRs because they are
load-bearing and awkward to reverse.

### D1 — slice 5 is the answering + judge layer

*Rejected:* **question tranche 3 to N≈85 plus a held-out slice.** A real option — it buys back the
1.7x power ADR-0007 spent, and the held-out slice is overdue. Rejected because it buys power for
retrieval comparisons that the evidence says are not next, and it would be a third consecutive
instrument slice with the answer half of the instrument still absent.
*Rejected:* **the reranker.** The diagnostic points straight at it — **10 of 10** missed required
chunks in the published cell are `RANKED_OUT`, not `ZERO_OVERLAP` (`metrics.py:26-32`, whose own
comment calls ranked-out *"IDF territory"*), and six sit at rank 6–10 so a candidate pool of ten
reaches them. Rejected on the power table above: it needs a 6–0 sweep, and rerankers trade. It
becomes slice 6 if prediction 5 holds, with a *measured* mandate rather than an inferred one.
*Rejected:* **a golden-set audit**, which slice 4's rule literally names. Rejected because that
rule's premise was tested and not supported: leakage came in at **0.341 Lounais-Suomi vs 0.323
Pirkanmaa**, so "Pirkanmaa's questions are easier" has no evidence behind it and the metric the
spec nominated to find it looked the other way.

### D2 — full M2 in one slice, judge included

The internal order is not a preference, it is a dependency: **answerer → the Owner hand-labels a
frozen sample of real answers → judge → agreement.**
*Rejected:* **judge first, on authored answers.** Attractive because the known-bad control could
be built before anything else. Rejected on validity: a judge calibrated against hand-written bad
answers is calibrated against a failure distribution that is not the model's.
*Rejected:* **answerer now, judge in slice 6.** Rejected because answers would exist that the
harness cannot evaluate for groundedness, which `CLAUDE.md`'s §2 says not to trust.
*Rejected:* **refusal only, no free-text answering.** The smallest honest slice, and it closes the
PARTIAL debt. Rejected because the 199 labels stay inert for a fifth slice.
*Accepted risk:* this is the largest slice yet. If the judge disagrees badly with the Owner, the
slice lands an honest **PARTIAL** with a working answer path — it does not collapse.

### D3 — the unit of judgement is the claim

`CONTEXT.md:91-94` already resolved this: *"A claim is one **required branch**, hand-enumerated in
the golden-set entry. The denominator is therefore set by hand per question rather than inferred
from the answer text."* This slice adopts the project's own vocabulary rather than inventing one.

Judge–human agreement is **published at claim level** over up to 199 units, and rolled up to a
whole-answer figure as a free diagnostic. The power arithmetic that decided it:

| unit | N | ~95% interval at agreement 0.90 |
|---|---|---|
| claim / forbidden item | up to 199 | **±0.05** |
| whole answer | 50 | ±0.08 |
| a hand-picked subsample | ~12 | ±0.17 — *the statistic ADR-0007 retracted* |

**Stated honestly and not waved past: units cluster within an answer.** A bad answer fails several
claims at once, so the effective N is below 199 and the published interval must be cluster-aware
rather than quietly assume independence. A naive binomial interval here would be the same class of
error as slice 3's ±0.18.

*Rejected:* **whole-answer level.** Simpler to label and closer to how a user experiences an
answer. Rejected because it cannot localise which branch was dropped, which is the entire reason
ADR-0003 built the branch model.

### D4 — refusal means out-of-corpus **and** out-of-jurisdiction

This resolves `CONTEXT.md:99-103`, open since 26 Aug: *"whether a question whose subject matter is
genuinely absent from the corpus, as opposed to merely under-determined, is the only true refusal
case."* **Answer: no. There are two kinds.**

1. **Out-of-corpus** — the subject matter is genuinely absent from these jätehuoltomääräykset.
2. **Out-of-jurisdiction** — answerable only from authority A, asked with authority B's filter.
   Retrieval returns B's own plausible, same-topic chunks and the answerer must decline rather than
   answer from them.

Only (2) closes the PARTIAL debt, and it is the harder and more valuable kind.
*Not adopted:* **under-determined figures as refusals.** `CONTEXT.md:96-98` already resolved that a
missing determining variable is a conditional answer with the condition surfaced. Reopening it
would be a spec delta, not a new decision.
*Cost, accepted:* (2) needs a new entry type that deliberately bypasses `golden._parse_question`'s
authority/label consistency check — the check that, per slice 4's spec delta, makes a mislabelled
municipality unrepresentable.

### D5 — R≈14, and refusal recall is a diagnostic

**Out-of-jurisdiction refusals cap out at six, and this was measured, not assumed.** Both clause
lists were read. The documents are topically parallel almost everywhere — including the vocabulary
fork (`8 § Korttelikeräys` ↔ `11 § LÄHIKERÄYSJÄRJESTELMÄ`, which are *both* covered and therefore
not refusals). The genuine asymmetries:

| Topic | Lounais-Suomi | Pirkanmaa |
|---|---|---|
| Kunnan toissijainen jätehuoltopalvelu (TSV) | — | `5 §` |
| Jätteiden putkikeräysjärjestelmä | — | `10 §` |
| Lisäjäte | — | `25 §` |
| Jätemylly | `19 §` | — |
| Hyödyntäminen omassa maanrakentamisessa | `22 §` | — |
| Roskaantumisen ehkäiseminen yleisillä alueilla | `42 §` | — |

So: **6 out-of-jurisdiction + 8 out-of-corpus = R≈14.** Refusal recall's denominator is R alone,
giving a **±0.13** interval, so it is reported as a **diagnostic with its interval stated inline**
and gated as a floor — never as a published headline.

*Rejected:* **pushing R to ~25 with more out-of-corpus cases** to buy ±0.08. Out-of-corpus is the
*easy* refusal — nothing retrieves, so declining is nearly free — while the hard kind stays stuck
at six. Making a metric publishable by diluting it with easy cases is structurally identical to
golden-set leakage, and this project does not get to do that having spent two slices measuring it.
*Rejected:* **six out-of-jurisdiction only.** Leaves the out-of-corpus refusal path built and
unmeasured.

### D6 — two-phase, one command; retrieval zero-tolerance, answers on a floor

`DESIGN.md:149-151` requires that `make eval` reproduce the published table from a clean clone, so
this is one command, not two. But the phases are gated differently and the retrieval phase never
depends on the answer phase:

- **Retrieval phase:** offline, per-cell, zero-tolerance against `eval/baseline.json`. Unchanged.
- **Answer phase:** gated on a **floor derived from the binomial interval at the metric's N** and
  recorded in the baseline — never a number chosen by taste, which would be a standard with no
  enforcer wearing a threshold's clothes.
- **A skipped answer phase makes a published table structurally unavailable**: printed as such, and
  a non-zero exit if a published table was requested. The reduced-N sin must be unrepresentable,
  not merely discouraged.

*Rejected:* **zero-tolerance on answer metrics too.** Consistent with the retrieval gate, and
tempting. Rejected on a provider fact: **Groq converts `temperature=0` to `1e-8`**, so
bit-determinism is unavailable and this gate would go red on noise. A gate that cries wolf gets
ignored, which `CLAUDE.md` calls decoration.
*Rejected:* **a committed response cache**, replaying frozen model outputs so the gate is
deterministic and offline. Genuinely strong — it preserves `DESIGN.md:149-151` exactly and makes CI
free. Rejected because the published number becomes a replay rather than a measurement, and silent
provider-side model drift goes invisible — which is the precise thing judge–human agreement exists
to catch. **Reconsider immediately if the cost ceiling is ever hit.**
*Rejected:* **separate `make eval` / `make eval-answers`.** Keeps the retrieval gate rock-solid and
CI cheap, at the cost of the README table being assembled from two commands — a direct hit on
`DESIGN.md:149-151`.

### D7 — the Owner approves a paid Groq Developer plan → **ADR-0008**

**This reverses a standing note in `CLAUDE.md:227-240`** (*"the Owner intends to use Groq's free
tier, so there is no monetary ceiling to set and no paid run is planned"*), and it was reversed by
arithmetic, not preference.

Measured, not guessed: **990 chars/chunk (Lounais-Suomi), 1209 (Pirkanmaa)** → ~450–550 tokens per
chunk at Finnish token density, so a top-5 context is ~2250–2750 tokens.

| Workload | Calls | ~Tokens |
|---|---|---|
| Answers (50 answerable + 14 refusal) | 64 | 198K |
| Judge on live answers | 50 | 110K |
| Judge on the frozen agreement sample | 50 | 110K |
| | **164** | **≈420K** |

Groq's free tier for `gpt-oss` and `qwen`: **30 RPM, 1K RPD, 8K TPM, 200K TPD.** RPM and RPD are
comfortable. **TPM/TPD is the binding constraint and it binds hard:**

> **One full run is ~2.1x the entire daily token allowance**, and ~52 minutes of saturated
> throughput at 8K TPM. `DESIGN.md:121-122`'s *"`make eval` in CI on every pull request"* is
> **impossible** on the free tier — twenty PRs a month is ~8.4M tokens. And a 52-minute saturated
> run is exactly the *"no unattended eval loops"* the guard-rail forbids.

The guard-rail's own note — *"the binding constraint is now rate limits, not money, and it is a
worse one for this project"* — was right, and worse than it looked.

Paid, splitting the roles by size:

| Role | Model | Tokens | Cost |
|---|---|---|---|
| Answerer, 64 calls | `gpt-oss-20b` @ $0.075 in / $0.30 out per M | 176K in / 22K out | $0.020 |
| Judge, 100 calls | `llama-3.3-70b` (≈$0.15/$0.60 per M assumed) | 190K in / 30K out | $0.047 |
| | | | **≈$0.067/run** |

*Rejected:* **shrinking the live phase to fit 200K TPD** — answer metrics over ~25 questions and a
~20-item sample. Rejected on principle: it publishes answer metrics over a deliberately reduced N,
the one thing the domain guard-rail says destroys this project.
*Rejected:* **splitting rate-limit buckets across model families** to roughly double the free
allowance. Unverified — Groq's docs say limits apply at organisation level and only the account's
own limits page shows the real table — and even if true, one run per day is not a dev loop and CI
is still out.
*Rejected:* **staying free with the recorded-run gate** (see D6's rejected cache). It is the
coherent free-tier answer and it remains the fallback if the ceiling is ever hit.

### D8 — the cost ceiling has three enforcers, and one of them is our code

`CLAUDE.md:227` requires a cost ceiling. It was dormant only because no paid run was planned; it
is not dormant now. The thing that costs money here is not the steady state — seven cents — it is
a runaway: a retry storm, an accidental loop, a bug that re-answers.

1. **Per-run token budget in our own code, hard-failing the run at ~600K tokens (~$0.15)** —
   roughly 2x a legitimate run, so a real run never trips it. A retry storm therefore cannot spend
   more than one run's worth.
2. **The LiteLLM Proxy's per-key budget** (D10) — an independent enforcer at the gateway.
3. **A monthly spend cap set at Groq.** **$25/month, already set by the Owner on 27 Aug 2026**
   — ~370 runs at the measured $0.067.

*Rejected:* **the provider cap alone.** A runaway burns the month's cap in minutes while the
harness retries cheerfully into 429s, and the project finds out from a billing page rather than a
gate. A ceiling that lives only in a dashboard is a standard with no enforcer.

### D9 — answerer `qwen/qwen3.6-27b`, judge `gpt-oss-120b`, and `CONTEXT.md:59` gets tightened → **ADR-0008**

> **AMENDED 27 Aug 2026 by tracer slice 1, before any harness code.** As shaped, this read
> *answerer `gpt-oss-20b`, judge `llama-3.3-70b`*. The Llama does not exist on the account and the
> smoke test disqualified the gpt-oss answerer on comprehension. The original text is left below
> so the reasoning that was overturned stays visible; the evidence is in **Tracer slice 1 —
> measured result** and in ADR-0008's amendment.

`CONTEXT.md:59` currently requires only *"a different model than the one under test"*. **That is
too weak and this slice tightens it to a different model *family*.** A judge sharing the answerer's
architecture and training lineage shares its blind spots, and will rubber-stamp precisely the
fabrications it exists to catch — while judge–human agreement looks healthy, because the human
sample is small and the correlated failures are concentrated in the cases that matter.

So: answerer `groq/openai/gpt-oss-20b` (OpenAI lineage, the cheap tier the guard-rail asks for),
judge `groq/llama-3.3-70b-versatile` (Meta lineage, stronger than the answerer, better documented
on multilingual prose). Both production models, neither withdrawable like a preview.

*Rejected:* **`gpt-oss-20b` answering and `gpt-oss-120b` judging.** Cheapest pairing, both
production, and it satisfies `CONTEXT.md:59` as literally written — which is the argument for
tightening the rule rather than an argument for the pairing.
*Rejected:* **`llama-3.1-8b` answering.** Cheapest possible. Rejected on the risk that 8B is too
weak for dense administrative Finnish: a floor-bound answerer makes every answer metric
uninformative for reasons that have nothing to do with retrieval, and makes a judge problem
indistinguishable from an answerer problem.
*Rejected:* **a preview Qwen judge.** A third family, maximally uncorrelated. Rejected because a
withdrawn preview model silently invalidates a committed agreement number and forces a re-label of
the frozen sample.
**Unverified and to confirm against the live model list at build time, not assumed:** the exact
Groq identifier for the 20b. The docs list `openai/gpt-oss-120b`, so `groq/openai/gpt-oss-20b` is
the likely form.

### D10 — LiteLLM SDK **and** Proxy, the Proxy in `compose.yaml` → **ADR-0009**

`DESIGN.md:71` already decided LiteLLM as the LLM boundary, so this needs no reversal — but the
reasoning was re-examined rather than inherited, and it survived on grounds `DESIGN.md` did not
state:

- `completion_cost()`, `cost_per_token()` and `token_counter()` supply the **dollar arithmetic and
  the provider price table**. Without them D8's ceiling means hand-maintaining Groq's prices in our
  own code, and a stale price table is a *silently wrong* ceiling.
- `num_retries` (tenacity-backed) plus rate-limit cooldowns cover the guard-rail's mandated
  retry-with-backoff. We write only the hard-fail-never-skip half.
- Groq needs no special handling: `model="groq/<name>"`, key read from `GROQ_API_KEY`.

**The Proxy runs in `compose.yaml`** beside Postgres, and it is not decoration: its per-key budget
is D8's second enforcer, which is a function this project actually needs. The Owner's additional
reason is recorded plainly because it is legitimate and this is a portfolio repository: the
LiteLLM **Gateway**, not the SDK import, is what job adverts mean by "LiteLLM", and the SDK alone
would not demonstrate it.

*Rejected:* **the `openai` SDK pointed at Groq's `base_url`.** Groq is OpenAI-compatible, so this
genuinely would work, and it keeps a three-dependency project lean. Rejected because it re-opens a
settled decision to save a dependency while *losing* the cost table and the retry layer we would
then have to build — reuse-before-building points at LiteLLM here, not away from it.
*Rejected:* **SDK only, Proxy as its own later slice.** The disciplined answer, and it keeps the
largest slice yet from growing a service. Overridden by the Owner knowingly.
*Rejected:* **Proxy only, harness on the plain `openai` SDK.** Architecturally cleanest, but no
LiteLLM appears in the Python at all, so a reader of the repo sees `openai`.
*Cost, accepted:* `make eval` gains a service that can be down, and it needs the honesty treatment
Postgres already has — tests skip **loudly**, and a green `make gate` with the proxy stopped proves
less than it looks. Secrets (`GROQ_API_KEY`, the proxy master key) stay out of git behind an
`.env.example`.

### D11 — groundedness is published, never unaccompanied, and void below the floor → **ADR-0010**

The project already has a rule for this shape: the README publishes recall@5 **with** leakage, and
`CLAUDE.md` says *"Never quote the first without the second."* The answer layer inherits it.

- **Groundedness is the published answer-layer number.** It may never appear without judge–human
  agreement **and branch coverage** beside it. Both companions are load-bearing and for different
  reasons: agreement says whether the judge can be trusted, and branch coverage closes the hole
  that groundedness alone leaves open — **groundedness is gameable by saying less, branch coverage
  is gameable by saying everything, and only the pair is a metric.**
- **Agreement additionally gates publishability.** Pre-registered floor: **≥0.85 at claim level**,
  fixed now, before the number exists — because a floor set afterwards is whatever the number
  happened to be. The reasoning: below 0.85 the judge carries ~15% label noise, and a 0.05
  difference in groundedness stops being distinguishable from the judge disagreeing with itself.
- **Below the floor, groundedness is reported as a DIAGNOSTIC with the agreement figure attached
  and is not published.** This upgrades *"never publish a metric it did not compute"* to *"never
  publish a judged metric whose judge is unvalidated."*

*Rejected:* **agreement as the headline.** The purest reading of "the harness is the product", and
a real option. Rejected because the README's answer row would then say nothing about whether the
system answers well, which a reader will reasonably find strange.
*Rejected:* **both side by side, neither gating the other.** Maximum transparency, nothing
suppressed — and it invites groundedness being quoted alone, the exact failure the recall/leakage
rule was written to prevent, reappearing one layer up.
*Rejected:* **branch coverage as the headline.** The most diagnostic of the four, but judge-
dependent exactly like groundedness, so it inherits the validation requirement without being the
metric that carries trust.

---

## Derived, because the evidence forces them

Not decisions — consequences. Recorded so nobody later mistakes them for preferences.

- **Answers come from the published cell only** (`lemma-reasm/0`). 12 cells × 50 questions is 600
  answer calls per run: unaffordable and diagnostically pointless. `evaluate.PUBLISHED` exists to
  make this decision once.
- **One judge call per answer**, returning every claim and forbidden verdict at once — 199 units in
  ~50 calls, not 199.
- **Refusal questions are a separate population.** Complete-set recall cannot be computed over an
  empty required set (`metrics.py:57-61` raises, and it is right to). So the retrieval headline
  stays **N=50** and ADR-0007's continuity is untouched. **Enforced structurally in `metrics.py`,
  not documented** — otherwise a later run pools the populations and the published headline moves
  for a reason nobody chose.
- **Citation checking splits in two.** Address validity is pure arithmetic — is the cited address in
  the retrieved set, is it in `required_chunks` — needing no judge, no floor and no network. Only
  *"does the cited chunk support this claim"* needs the judge. The arithmetic half is therefore the
  most trustworthy number the answer layer produces, on the same logic that makes retrieval metrics
  win arguments.
- **Human labels are written once against a frozen, committed set of answer texts**, never against
  live output. Otherwise every prompt or model change invalidates them and `DESIGN.md:117-119`'s
  "fixed sample each run" is unimplementable.
- **`temperature=0` becomes `1e-8` at Groq.** D6's floor is a consequence of the provider, not a
  hedge.

## The build-order calls I made, which the Owner may override

- **A five-question capability smoke test before any harness code.** Nobody has established that
  `gpt-oss-20b` can read dense administrative Finnish. If it cannot, the answer metrics measure the
  model's Finnish rather than the pipeline, and this slice must be **re-shaped rather than built**.
  This is a stop-and-look, not a warm-up.
- **Known-bad control: 8 authored bad answers** — a wrong citation, a fabricated claim, a flattened
  conditional, a cross-authority answer, and one of each again on the other authority. The judge
  must catch **8/8**. It is a floor test, not a proportion, so 100% is the correct bar and a small
  N is fine. Seen red by weakening the judge prompt.
- **Structured JSON output** with explicit `refused: bool` and `citations: [address]`. A refusal is
  never detected by string-matching prose — that fails silently and mis-scores the metric this
  slice exists to produce.
- **Monthly provider cap: $25**, already set by the Owner at Groq. Not an open question.

---

## Tracer slices

Blockers first. Each cuts the whole stack and is demoable alone.

1. **The capability smoke test.** 5 questions, the published cell's top-5, one model, output read
   by the Owner. Delivers a go/re-shape verdict and nothing else. **Blocks everything.**
2. **The boundary and one real answer.** LiteLLM Proxy in `compose.yaml`, the SDK behind it, one
   question answered with citations printed by address and the cost printed from
   `completion_cost()`. Thin, full-stack, demoable. (blocked by 1)
3. **The refusal path.** The 14 refusal questions, the new out-of-jurisdiction entry type, the
   separate-population enforcement in `metrics.py`, refusal precision/recall as arithmetic. **This
   is the slice that closes the PARTIAL debt.** (blocked by 2)
4. **The judge and its control.** One judge call per answer returning 199 unit verdicts, plus the
   8/8 known-bad control seen red. (blocked by 2)
5. **The frozen sample and agreement.** Freeze the answer texts, the Owner hand-labels at claim
   level, agreement computed with a cluster-aware interval, the void rule wired. **Contains Owner
   work and cannot be done by the Foreman.** (blocked by 4)
6. **The metrics, the floor gate and the baseline.** The four judged metrics, the derived floors,
   `eval/baseline.json` extended, the gate seen red on a deliberate break, cost printed per run.
   (blocked by 3, 5)

---

## Acceptance criteria

Each is falsifiable and names how it will be proven. `/verify-live` fills a verdict **per
criterion**; the slice's verdict is the **worst** among them.

| # | Criterion | Proven by |
|---|---|---|
| AC1 | The capability smoke test ran **before** harness code, and its verdict is recorded | transcript pasted into this spec's Measured result |
| AC2 | The LiteLLM Proxy runs in `compose.yaml`; the harness reaches both models through it; no key literal is in git | `git ls-files -z \| xargs grep` for key patterns returns nothing; a live call through the proxy |
| AC3 | The answerer emits structured JSON with `refused` and `citations`; a malformed response is a **hard error**, never a skip | unit test on a malformed payload, **seen red** |
| AC4 | All **50** answerable questions are answered and judged; N on the table equals 50 | eval output, N stated on the table |
| AC5 | A question that cannot be scored after retries **fails the run**, non-zero exit — never a skip | **seen red** by forcing a persistent provider error |
| AC6 | The per-run token budget hard-fails at the ceiling | **seen red** by setting the ceiling to 1 token |
| AC7 | Refusal questions are a separate population: complete-set recall is still over exactly 50, and the 12 retrieval baseline cells are **unchanged** | eval output shows both N values; `baseline.json` retrieval cells byte-identical |
| AC8 | `metrics.py` structurally refuses to pool the two populations | a test that tries to and gets an error |
| AC9 | Citation **address validity** is computed with no judge and no network | pure unit test |
| AC10 | The judge catches **8/8** known-bad control answers | control run; **seen red** by weakening the judge prompt |
| AC11 | Judge–human agreement is computed at claim level over the frozen sample, with a **cluster-aware** interval, and printed every run | eval output |
| AC12 | Groundedness never appears without agreement beside it; below 0.85 the table marks it **DIAGNOSTIC** and withholds the published value | **seen red** by stubbing agreement to 0.80 and confirming the table changes |
| AC13 | An out-of-jurisdiction question is **refused**, not answered from the wrong authority's rules | the 6 cases scored, with the printed answer for at least one |
| AC14 | A question with no municipality set does not silently pick one | unit test **and** a live case (`CLAUDE.md` §3, second clause) |
| AC15 | The answer-metric floor gate fails on a deliberate break | **seen red** |
| AC16 | The retrieval phase still runs and gates with the answer phase disabled, **and** a published table is structurally unavailable in that mode | two runs, both exit codes shown |
| AC17 | Cost per run is **measured** from `completion_cost()`, not estimated, and printed | eval output |

---

## Pre-registered predictions

Fixed now, so the result cannot be reinterpreted afterwards. Scored honestly in a **Measured
result** section when this lands, **refutations first**.

1. **`gpt-oss-20b` groundedness lands 0.55–0.80** at claim level. The band is wide because nothing
   is known about these models on administrative Finnish; a narrow band here would be false
   confidence.
2. **Agreement clears 0.85 at claim level — but agreement on `forbidden` items is *lower* than on
   required claims.** "Did the answer flatten this conditional" is a harder judgement than "did it
   state this". If over-claim agreement is the *higher* of the two, the judge prompt is probably
   collapsing the two questions into one.
3. **Refusal recall is higher for out-of-corpus (≥7/8) than out-of-jurisdiction (≤4/6).** The hard
   kind fails: retrieval hands the answerer plausible, same-topic chunks from the authority it was
   asked about, and nothing in the prompt tells it the question belongs elsewhere. This is the
   prediction most likely to embarrass the design, which is why it is here.
4. **Branch coverage < groundedness.** The answerer drops required branches more often than it
   fabricates support for the ones it does state.
5. **Answer failures are dominated by retrieval, not generation.** Directly testable: groundedness
   over the 41 questions whose complete set was retrieved, against the 9 where it was not. This is
   the prediction that decides slice 6.
6. **Cost per run lands within 2x of $0.067.**

## Decision rule for slice 6

Fixed now, before the numbers exist.

- **Prediction 5 holds** → **slice 6 is the reranker.** It finally has the mandate the vector layer
  lost: the failure would be *measured* at the answer layer rather than inferred from a plan. Note
  it still faces the 6–0 bar, so its spec must pre-register a fix size, not a hope.
- **Prediction 5 refuted** — groundedness fails on questions whose chunks were all retrieved →
  **slice 6 is prompt and model work**, and the reranker waits. A retrieval fix would then be
  optimising the half that is not broken.
- **Agreement below 0.85** → **slice 6 is the judge**, and no answer number is published until it
  clears. This overrides both of the above.
- **The held-out-slice trigger stays at N≈85 for the retrieval population.** Slice 5 does not move
  it: the 14 refusal questions are a separate population and buy the retrieval headline no power.

---

## Non-goals

No third authority, no embeddings, no pgvector, no custom Postgres image, no reranking, no weighted
hybrid score, no synonym or thesaurus layer, no answer caching, no fine-tuning, no chat UI, no
held-out slice, no CI, no Dockerfile, no Cloud Run, no `18 a §` fix, no Uudenmaan parser fixes, no
momentti-level modelling, no sub-municipal coverage model. `make docker-build` still exits non-zero
on purpose — do not "fix" it.

**Corpus breadth remains the standing explicit non-goal.** The 14 refusal questions are not corpus
breadth: they add questions to the existing two authorities and add no documents.

Answer metrics are computed on the **published cell only**. Extending them across the analyser grid
is not deferred for cost alone — it is not a question the grid can answer, because the answer layer
reads one top-5.

## Definition of done

- All 17 acceptance criteria have a verdict filled by `/verify-live`, with pasted evidence.
- `eval/baseline.json` extended with the answer-layer metrics and their derived floors, in a
  **separate commit** from the code that produced them. The 12 retrieval cells are unchanged in
  that commit, and that is asserted, not eyeballed.
- **ADR-0008** — the paid Groq plan, the model pair, and the `CONTEXT.md:59` tightening, with
  rejected alternatives including the free-tier arithmetic that forced it.
- **ADR-0009** — LiteLLM SDK + Proxy, with the `openai`-SDK alternative and its reasoning recorded.
- **ADR-0010** — the judge design: the claim as the unit, the 0.85 floor, and the void rule.
- **`CLAUDE.md` corrected**, and this is overdue rather than new work:
  - `:22` and `:33` still state the published headline is **0.680 in `snowball/0`**. It is
    **0.820 in `lemma-reasm/0`** and has been since ADR-0007 and commits `d30e3ee`/`bbe8b1a`. The
    highest-precedence project doc currently contradicts `evaluate.py:63` and `eval/baseline.json`.
  - `:227-240` — hard limit #1 rewritten: a paid provider **is** approved for Groq, the ceiling is
    a number, and the enforcers are named.
  - The definition-of-done reference cites `DESIGN.md:122-128`, which is the milestones table. Done
    is at `DESIGN.md:149-151`.
  - "Where this stands" gains the answer layer.
- **`CONTEXT.md`**: `:59` tightened to *different model **family***; `:99-103` resolved by D4; new
  entries for **Refusal case**, **Out-of-jurisdiction refusal**, **Frozen judge sample**,
  **Agreement floor**, **Judgement unit**, **Answer-metric floor**.
- **`DESIGN.md`**: `:121-122`'s CI-on-every-PR note updated now that money is in scope and the
  free-tier impossibility is measured; M2 status recorded honestly.
- **`REVIEW-DEBT.md`**: the hard-filter entry promoted **PARTIAL → CLOSED** *only if* the
  out-of-jurisdiction cases actually score — never on the answer path merely existing. Plus every
  new confession, including the ones this spec already knows it owes (below).
- Predictions scored honestly, refutations first.
- Gates green; `make eval` run from a genuinely clean clone into a fresh environment, per the
  recipe that earned its place in slice 4.

## Confessions this spec already knows it will owe

Written here at shaping time rather than discovered at `/confess`.

- **`make eval` becomes network-dependent and non-deterministic.** `DESIGN.md:149-151`'s "reproduces
  that table from a clean clone" weakens from *exactly* to *within the floor band* for the answer
  metrics. The retrieval half is unaffected.
- **A green `make gate` now proves even less than before.** Postgres down already skipped the
  end-to-end tests; the proxy down will skip the answer tests too. Both must skip **loudly**.
- **The judge is validated on the same 50 questions it scores.** There is no held-out slice to draw
  a judge-validation set from, so the frozen sample overlaps the scored set. The judge is not
  *trained* on them, so this is weaker than leakage — but it is not nothing, and it is the second
  independent argument for the N≈85 tranche.
- **The `18 a §` absorption becomes reachable by a citation.** A Pirkanmaa composting-notification
  question would be answered from `18 §`'s chunk, which silently contains `18 a §`'s text. The
  citation would name a clause that does not have that text under its own number. No golden
  question points there today; an answer layer can nonetheless be *asked*.

---

## Open questions (for the Owner)

Four of the five carried here at shaping time have been answered. What remains is listed first.

### Open

**Two, both raised by tracer slice 3's measured result, neither blocking tracer 4.**

- **Should refusal precision be reported over a restricted denominator?** Measured: the answerer
  refuses 5 of 9 questions whose retrieval was incomplete and 2 of 41 whose retrieval was complete
  (Fisher p=0.0011). As defined, refusal precision charges the answerer for retrieval failures, and
  0.632 understates it. *Recommendation:* **report both** — precision over all 50 as the honest
  system-level number, and precision over the 41 as a diagnostic labelled *"given the answerer had
  what it needed"* — rather than replacing one with the other, because the system-level number is
  what a resident experiences. Not built: it is a metric the spec never shaped, and inventing one
  mid-tracer is scope-filling.
- **Should `ooc-autonrenkaiden-vastaanotto` and `ooj-lisajate-lounais-suomi` be re-labelled?** Both
  are contestable, both are the two misses, and re-labelling either would raise refusal recall from
  0.857 toward 1.0. *Recommendation:* **re-label `ooc-autonrenkaiden-vastaanotto` and keep
  `ooj-lisajate-lounais-suomi`.** The tyre question is genuinely answered by a category rule the
  corpus does carry, which makes the label wrong on its merits; the lisäjäte question asked for
  conditions that do not exist and got "not permitted", which is a defensible miss. **Whatever is
  decided, the 0.857 already published above stands as the number this configuration produced**, and
  any re-label is a change to the *set*, re-measured and re-reported, never a correction to a
  result.

### Answered since shaping

- ~~**Do refusal questions get a groundedness score, and what is groundedness' denominator?**~~
  **RESOLVED 27 Aug 2026 — and answering it exposed a contradiction in `CONTEXT.md` that has been
  there since 26 Aug.** `:47` defined groundedness over *"claims **in an answer**"* (denominator =
  branches stated) while `:92-94` said *"the denominator is therefore set by hand per question"*
  (denominator = branches required). Both were being cited as canonical.

  **Decided: the `:47` reading. Groundedness = supported / branches STATED.**

  | Metric | Denominator | Refusal questions |
  |---|---|---|
  | Groundedness | branches **stated** | excluded entirely |
  | Branch coverage | branches **required** | excluded entirely |
  | Over-claim | **forbidden** items | **included** |
  | Refusal precision / recall | see D5 | the population |

  *Why this reading:* the project already rejected the alternative's shape one layer down.
  `metrics.py`'s docstring refuses per-chunk recall as a headline because it *"awards partial credit
  for a retrieval that produces a confidently wrong answer"*. A required-branch denominator blends
  *did it say enough* with *was what it said supported* into one number, when branch coverage
  already measures the first.

  *Why `:92-94` did not settle it:* **its stated rationale is satisfied by both readings.** The judge
  answers the same narrow yes/no questions — *is branch X stated? is it supported?* — under either;
  only the arithmetic afterwards differs. That paragraph was fixing the claim *unit* and the
  *judge's task*, and its denominator sentence reached into a decision it was not making. Amended
  in `CONTEXT.md`, not quietly reinterpreted.

  *The cost, accepted:* groundedness under this reading **is** gameable by saying less — an answer
  stating one well-supported branch of five scores 1.0. That is exactly why D11 makes **branch
  coverage a load-bearing mandatory companion rather than a diagnostic**, and why a wrongly-refused
  answerable question scores **0 on branch coverage**. Cowardice is punished there, not by
  distorting groundedness into something it cannot compute. A refusal emitting any citation is a
  defect, checked arithmetically.


- ~~**The monthly cap figure at Groq.**~~ **$25/month, set by the Owner on 27 Aug 2026.** ~370 runs.
- ~~**Should the frozen agreement sample be held out from the scored set?**~~ **Not a real
  question** — it is forced at N=50 without shrinking the scored population. **Demoted to a
  confession** (above), where it does useful work as the second independent argument for the N≈85
  tranche.
- ~~**Should `18 a §` be fixed before an answer layer can cite `18 §`?**~~ **Deferred, on a harder
  reason than scope.** Fixing it changes Pirkanmaa's chunk count, which invalidates the manifest's
  `expected` block — and that block exists precisely to *refuse a document that parses differently
  than it did when the labels were hand-written*. Fixing it mid-slice means re-parsing the corpus
  underneath 199 labels. **Cheap guard adopted instead: none of the 14 new refusal questions may
  target Pirkanmaa `18 §`.** Revisit when a golden question genuinely needs that clause.
- ~~**Sastamala.**~~ **The model question stays open and stays the Owner's**, unchanged from slice
  4: whether the design needs a level between authority and municipality. But it does not block
  slice 5, and slice 4's AC8 already pins that the refusal message names the partial coverage.
  Slice 5 makes that message **user-visible for the first time** — Sastamala now gets a refusal a
  person reads rather than a query that quietly does not run. No sub-municipal coverage model.

---

## Tracer slice 1 — measured result (27 Aug 2026)

`5 golden questions x 2 candidate answerers = 10 calls. 40,191 prompt + 5,667 completion tokens,
~$0.01. Real published-cell top-5 from the ingested corpus, not hand-picked chunks.`

**AC1: MET.** The smoke test ran before any harness code and produced a verdict that changed the
slice. The probe itself was throwaway (stdlib `urllib`, job scratch dir) and is not in the repo.

### The verdict

**`gpt-oss-20b` is disqualified as the answerer.** Not for being weak — a weak system under test is
the point — but because on `biojatteen-kerays-jarjestaminen`, **with the required chunk `#15`
retrieved at rank 4**, it inverted the conditional: it stated that properties composting under
`17 §` must collect bio-waste separately, when `15 §` exempts them. An inversion under *perfect
retrieval* makes comprehension failures and retrieval failures indistinguishable, which would make
**prediction 5 — the one that decides slice 6 — untestable.** Its Finnish also carried real errors:
`las` for `lasi`, `maittuminen` (not a word), `jos kiinteistö kompostoivat`, `lukittuihin kaappeihin`
for `lukituissa kaapeissa`.

**`qwen/qwen3.6-27b` passed.** On the same question it reproduced all three of the golden entry's
required branches exactly — the >10 000-resident taajama threshold at one dwelling, the taajama
threshold at five, and the `17 §` exemption — each cited by address in the requested bracket format.

**Revised pair (D9, ADR-0008 amended): answerer `groq/qwen/qwen3.6-27b`, judge
`groq/openai/gpt-oss-120b`.** Different families, strongest available judge.

### Four findings the slice did not anticipate

1. **`llama-3.3-70b-versatile` is not on this account, and there is no Llama at all.** ADR-0008's
   pair was read off the public docs. Caught by listing models before spending anything — the
   cheapest possible place to catch it.
2. **Both candidates are reasoning models, and ADR-0008's token estimate assumed they were not.**
   Reasoning tokens bill as output. Measured: ~450–850 output tokens per answer against the ~350
   assumed. The first probe run returned **empty content** from `gpt-oss-20b` because a 700-token
   cap was consumed entirely by hidden reasoning. **The ~$0.067/run and the ~600K per-run ceiling
   (D8) must both be re-derived from `completion_cost()` once the real pair runs** — and Qwen's
   Groq pricing is unconfirmed, so the figure must not be quoted until measured.
3. **Refusal behaviour depends on reasoning being enabled, and that is a genuine trade-off.** With
   reasoning on, Qwen's trace explicitly concluded the excerpts were insufficient for
   `naapuruston-yhteiskerays`. With `reasoning_effort: none` it answered anyway. Refusal quality may
   therefore be something the project *pays tokens for*, which nothing in the spec anticipated.
   Pre-registered as prediction 7 below.
4. **Per-model parameter vocabulary differs.** `gpt-oss` accepts `reasoning_effort: low|medium|high`;
   `qwen` rejects anything but `none|default` with an HTTP 400. Direct evidence for D10's boundary —
   this is exactly what LiteLLM normalises, and it appeared on the second call of the project.

### The result that most supports the slice's premise

On `naapuruston-yhteiskerays` the required `8 § Korttelikeräys` was **ranked out**, and **neither
model refused.** Both answered confidently from `7 §` kimppa — a *voluntary* neighbour arrangement —
when the question was about *plan-mandated* block collection. A textbook confident wrong answer
produced by incomplete retrieval, on the first five questions ever put to this system. It is exactly
what the answer metrics exist to catch, and it is early support for prediction 5.

### Prediction added before the build, not after

7. **Refusal recall is materially higher with reasoning enabled than with it off**, and the token
   cost of enabling it is 2–4x the completion tokens. If false — refusal quality is indifferent to
   reasoning — then reasoning stays off and the cost model is the cheaper one.

### Spec deltas from this slice

- **D9's pair is amended**, above, with the original left visible.
- **The token and cost figures in D7/D8 and ADR-0008 are now known to be low**, because they
  assumed non-reasoning models. They are not corrected by estimate — they are marked
  *to be re-measured* from `completion_cost()`, which is what D10 chose LiteLLM for.
- **`qwen/qwen3.8-27b` was never tested.** 3.6 is chosen because it is the one measured. Recorded
  rather than quietly upgraded.
- **The slice-4 `Python-urllib` 403 confession generalises.** Groq's edge rejects the default
  urllib User-Agent exactly as tampere.fi did. Not a blocker — LiteLLM and the `openai` SDK set
  their own — but the debt entry is broader than the corpus fetch it was written about.

## Tracer slice 2 — measured result (28 Aug 2026)

`One golden question answered end to end through the gateway, three times (reasoning off, and on
at two caps), plus the red proofs. ~$0.08 total.`

**AC2: MET.** The LiteLLM Proxy runs in `compose.yaml`, the harness reaches both models through
it, and `git ls-files -z | xargs -0 grep` finds no key literal.
**AC3: MET, seen red.** 13 malformed envelopes are rejected; making `_envelope` tolerant turned
three tests red, and they went green again on revert.
**AC6: MET, seen red.** The token ceiling fires; disabling the comparison turned three tests red.
**AC17: MET.** Cost is read from the gateway's `response_cost`, never estimated here.

### What was refuted

**D8's second enforcer did not exist.** The gateway's budget was configured in
`litellm_settings.max_budget` with the harness authenticating as the proxy master key. Measured
while trying to watch it go red: **$0.074910 of spend against a $0.001 budget was served
HTTP 200.** LiteLLM does not apply budgets to its master key. A virtual key was refused
**HTTP 429** at $0.000029 against $0.00001. Corrected in-slice — the harness now spends through a
derived virtual key, whose spend was then watched accruing ($0.0256206, matching the run's reported
cost exactly). **ADR-0009** records it; `REVIEW-DEBT.md` keeps the lesson. The spec said "per-key
budget" and was right; the first implementation was not.

**D8's 600K token ceiling is too low for a legitimate run.** Measured on one real five-chunk
context:

| | prompt | completion | of which reasoning | tokens | cost |
|---|---|---|---|---|---|
| reasoning **off** | 4,866 | 353 | 0 | 5,219 | $0.003980 |
| reasoning **on** (cap 8k) | 4,866 | 6,018 | 5,143 | 10,884 | $0.020974 |
| reasoning **on** (cap 16k) | 4,866 | 7,567 | 6,646 | 12,433 | $0.025621 |

At 64 questions the answer phase alone is ~340K tokens with reasoning off and **~700K with it on**,
before a single judge call. The ceiling was **deliberately left at D8's 600K** rather than fitted
to one measurement — see the confession.

**Prediction 6 is heading for refutation.** It fixed cost per run within 2x of $0.067. The answer
phase alone is ~$0.25 with reasoning off and **~$1.34 with it on**, judge excluded. Scored properly
when a full run exists; recorded now so it cannot be reinterpreted later. Qwen's Groq pricing,
unconfirmed at the end of tracer 1, is **$0.60/M input and $3.00/M output**, derived from three
measured calls and consistent to five decimals.

### The finding that changes prediction 7

Tracer 1 predicted refusal quality depends on reasoning. **Comprehension does too, and more
sharply.** On `biojatteen-kerays-jarjestaminen` with reasoning **off**, `qwen/qwen3.6-27b` produced
the *same inversion of `17 §`* that disqualified `gpt-oss-20b` — it listed self-composting as a
condition that puts a property **in** scope of the separate-collection duty, when `15 §` exempts it.
With reasoning **on**, the same model on the same context stated all three required branches
correctly, named the two determining variables it could not resolve, and cited each branch by
address.

So prediction 7's trade-off is worse than "refusal quality costs tokens": **the cheap configuration
produces confidently wrong answers of exactly the kind this project exists to catch.** If that holds
across the set, reasoning is not optional and the expensive cost model is the real one.

### Four smaller findings

1. **`num_retries` needs `tenacity`, which litellm core does not install.** The first real call
   through the gateway died on *"tenacity import failed"*. D10 counts LiteLLM's backoff as
   satisfying the guard-rail's retry requirement, so the dependency is load-bearing; it is now
   declared.
2. **A 3,000-token cap fails as `json_validate_failed` with an empty `failed_generation`** — the
   same failure tracer 1 saw at 700 tokens wearing a different error code, because the cap covers
   reasoning and answer together. The default is now 8,000, measured.
3. **Qwen returns its `<think>` block inside `content`** while `gpt-oss` reports it as
   `reasoning_tokens` with clean content. `reasoning_format: hidden` is set explicitly rather than
   relying on JSON mode's side effect of suppressing it.
4. **`load_dotenv()` searches from the *caller's file*,** so it found the repository only because
   this is an editable install; a wheel would have found nothing. Changed to search from the
   working directory — the exact "worked in the dev checkout" failure the clean-clone build gate
   exists to catch.

### Spec deltas from this slice

- **D10 is amended by ADR-0009**: the enforcer is a **budgeted virtual key**, not
  `litellm_settings.max_budget`, and the gateway gets **its own Postgres with a persistent volume**
  (the corpus database's `tmpfs` is untouched — the two have opposite persistence requirements).
- **D8's ceiling is contradicted by measurement and left in place**, with the numbers recorded at
  the constant and the re-derivation assigned to tracer 6.
- **`make db-up` now starts only Postgres; `make services-up` starts the gateway too.** Nothing
  that answers can run without the latter.
- **The gateway image is pinned by digest**, not by `main-stable`: a floating tag would silently
  change the provider price table that both the published cost and the ceiling depend on.

## Tracer slice 3 — measured result (28 Aug 2026)

`14 refusal questions authored and enforced, the two populations separated structurally, refusal
precision/recall as arithmetic, and one full 64-question run. Two runs were paid for: the first
died at the 29th answer.`

### AC verdicts

A verdict per criterion; the tracer's is the worst among them.

| # | Verdict | Evidence |
|---|---|---|
| AC5 | **MET, seen red — unintentionally, on the real thing** | The first full run hit a persistent provider error at the 29th of 64 answers, stopped, exited non-zero and reported no table. It was not a drill. |
| AC6 | **MET, seen red on the full-run path** | `--token-ceiling 1` stopped the run after one call (10,884 tokens, $0.0210), exit 1. |
| AC7 | **MET** | `baseline.json` re-recorded after the refusal population landed: identical but for `commit`. Both N values printed (50 answerable, 14 refusal). |
| AC8 | **MET, seen red** | Separate types, plus runtime guards both ways. Disabling the guard in `compute` turned the test red — with a bare `AttributeError`, which is the guard's value. |
| AC13 | **MET** | 5 of 6 out-of-jurisdiction questions refused, each holding five same-authority chunks; printed above. |
| AC14 | **MET, seen red** | `answer <id> --municipality ""` refuses with a message naming the rule, exit 1, before any model call. Removing the guard turned two tests red. |
| AC17 | **MET** | $0.7553 read from the gateway's `response_cost`, never estimated. |
| AC4 | **PARTIAL** | All 50 answerable questions were answered and N=50 held. They are **not judged** — that is tracer 4. |
| AC3, AC2 | carried MET from tracer 2 | unchanged. |

**Tracer verdict: PARTIAL**, on AC4, which this tracer never claimed to close.

### The numbers

`fi-rag-eval answer --all`, published cell `lemma-reasm/0`, `qwen/qwen3.6-27b`, reasoning on,
**64 of 64 questions answered**, exit 0.

```
refusal behaviour — lemma-reasm/0, qwen/qwen3.6-27b, reasoning on   (DIAGNOSTIC, never a headline)
  recall     0.857 [0.60, 0.96] n=14      correct refusals / refusal population
  precision  0.632 [0.41, 0.81] n=19      correct refusals / all refusals emitted
  out-of-corpus       0.875 [0.53, 0.98] n=8
  out-of-jurisdiction 0.833 [0.44, 0.97] n=6
  ANSWERED anyway (2): ooj-lisajate-lounais-suomi, ooc-autonrenkaiden-vastaanotto
  WRONGLY refused (7): miksi-biojatteet-pakataan, biojate-mita-tarkoittaa,
    taloyhtio-kolme-asuntoa-biojate, ei-jateautoa-mokille, pir-jateastia-rikki,
    pir-tyhjennysten-keskeytys-tyhjilleen, pir-ei-jateautoa-mokille
  DEFECT — refusals carrying citations (2): ooj-tieyhteydeton-saari-pirkanmaa,
    ooj-toissijainen-jatehuoltopalvelu-lounais-suomi
  cost       $0.7553 measured at the gateway over 64 calls, 478438 tokens (ceiling 1395200)
  NOTE       the provider rejected 1 generation(s) as invalid JSON and they were retried.
```

**AC7 holds: the 12 retrieval cells are byte-identical.** `eval/baseline.json` re-recorded after the
refusal population landed differs in the `commit` field and in nothing else. The retrieval headline
is still complete-set recall 0.820 over **N=50**.

### Prediction 3 is REFUTED, and it is the good kind of refutation

Prediction 3, registered as *"the prediction most likely to embarrass the design"*: out-of-corpus
**≥7/8**, out-of-jurisdiction **≤4/6**, because *"retrieval hands the answerer plausible, same-topic
chunks from the authority it was asked about, and nothing in the prompt tells it the question
belongs elsewhere."*

- Out-of-corpus: **7/8**. Met exactly.
- Out-of-jurisdiction: **5/6**. **Refuted.**

The mechanism the prediction described is real and was observed working — every out-of-jurisdiction
question retrieved five plausible same-topic chunks from the asked authority — and the answerer
declined anyway, naming what the excerpts *do* say and what they do not. The two kinds are also
statistically indistinguishable at this N (0.875 vs 0.833, intervals almost fully overlapping), so
the *hard/easy* split the population was built around is not visible in the data. It may still be
real; 8 and 6 questions cannot see it.

**This is what closes the hard-filter debt.** `CLAUDE.md`'s third verification layer asks for a
question answerable only from A, asked with B's filter, to be **refused**. Five of six were, with
the answers printed. Sample of the evidence (AC13):

> `ooj-jatemylly-pirkanmaa` — Tampere, retrieved `#41 #18 #22 #25 #28`, all Pirkanmaa:
> *"Annetuissa pykäläotteissa ei ole tietoa keittiön jätemyllyn asentamisesta tai jätteiden
> johtamisesta viemäriin, joten en voi vastata kysymykseen."*

### The real failure is the opposite of the predicted one: over-refusal

**7 of 50 answerable questions were refused**, which is what drags precision to 0.632. But the 7 are
not evenly spread, and the split is the sharpest result in this tracer:

| | refused | answered | refusal rate |
|---|---|---|---|
| complete retrieval | 2 | 39 | **0.049** |
| incomplete retrieval | 5 | 4 | **0.556** |

**Fisher's exact, two-sided: p = 0.0011.** The answerer refuses eleven times more often when its
context is missing a required chunk. Five of the seven "wrong" refusals are therefore the answerer
behaving **honestly** — the excerpts genuinely did not support an answer — and refusal precision as
defined charges it for a *retrieval* failure.

Two consequences, and the second is the important one.

1. **Refusal precision at 0.632 understates the answerer.** Over the 41 questions whose retrieval
   was complete it refused twice. Whether the harness should publish a precision restricted to that
   denominator is **not decided here** — it would be a metric the spec never shaped, and inventing
   one mid-tracer is the scope-filling this project forbids. Recommendation and open question below.
2. **Prediction 5 has its first evidence, and it points at retrieval.** Prediction 5 — *"answer
   failures are dominated by retrieval, not generation"* — is the prediction that decides slice 6,
   and it is stated over **groundedness**, which needs the judge. This is a different statistic. But
   it is arithmetic, it is significant, and it points the same way: the answerer's behaviour tracks
   what retrieval gave it. **Not scored — prediction 5 is scored in tracer 4 or later, on
   groundedness, as registered.** Recorded now so the direction cannot be claimed as a surprise
   afterwards.

### Two of the fourteen labels are contestable, and both are the two misses

Written down rather than quietly fixed, because relabelling until the number improves is the one
move that would destroy this harness.

- **`ooc-autonrenkaiden-vastaanotto`** — the answerer replied that tyres are producer-responsibility
  waste [`#2.tuottajavastuunalaisella`] and go to producer-designated collection points [`#12`].
  Both citations are real and the general rule is applied correctly. The word `rengas` is absent
  from both documents — the drift detector passed — but the **category** is covered. **This is
  exactly the `sakokaivo` failure mode the confession warned about, occurring.**
- **`ooj-lisajate-lounais-suomi`** — asked for the *conditions* under which waste may be left beside
  the bin. The answerer replied that Lounais-Suomi does not permit it, citing `#30` and `#28`. That
  is arguably a correct answer to the question as asked, not a missed refusal. The risk was noticed
  when the question was authored and the phrasing was sharpened to ask for conditions; it was not
  enough.

**The numbers above stand as measured.** No label was changed after seeing the output. Whether
either question should be re-labelled is the Owner's, and it is an open question below — with the
warning that "the answer improved so the label must be wrong" is the reasoning this project exists
to refuse.

### Prediction 6 is REFUTED

Prediction 6 fixed cost per run **within 2x of $0.067**, i.e. ≤$0.134. The answer phase alone, judge
excluded, is **$0.7553** — 11x the prediction and 5.6x its tolerance. Tracer 2 flagged this heading
for refutation from one measurement; it is now measured over 64. The per-answer mean is
**$0.0118** and **7,476 tokens**, below the 10,900 measured on a single question in tracer 2, so
`MEASURED_TOKENS_PER_CALL` is conservative — which is the right direction for a number a ceiling is
derived from.

**The $25/month ceiling is not at risk**: at $0.755 per answer-phase run that is ~33 runs, and the
judge will roughly double it. But `DESIGN.md:121-122`'s CI-on-every-PR is now a different
conversation than ADR-0008's ~$1.34-for-twenty-PRs arithmetic, and that arithmetic should be redone
in tracer 6 when the judge's cost is known.

### The defect no judge would have found

**Two refusals carried citations.** `ooj-tieyhteydeton-saari-pirkanmaa` cited `#7` and
`ooj-toissijainen-jatehuoltopalvelu-lounais-suomi` cited `#1`, both while correctly refusing. The
spec resolved that *"a refusal emitting any citation is a defect, checked arithmetically"* — and it
is, and it fired. Both are the same shape: the model refuses, then cites the chunk it is explaining
*doesn't* answer the question. Whether that is a prompt defect or a definitional one — a citation
supporting "here is what the excerpts do say instead" is not obviously wrong — is worth deciding
before the judge is built, since the judge will be asked about citations too.

### What was refuted, before anything was measured

**Three of D5's six pre-registered out-of-jurisdiction topics are wrong.** D5's table was
harvested by reading the two **clause lists**. Checking the **body text** — which is what the
answerer actually sees — refuted half of it:

| D5's topic | Verdict | Why |
|---|---|---|
| Jätemylly (LS `19 §`) | **kept** | absent from Pirkanmaa entirely |
| Jätteiden putkikeräysjärjestelmä (PIR `10 §`) | **kept** | absent from Lounais-Suomi entirely |
| Lisäjäte (PIR `25 §`) | **kept** | absent from Lounais-Suomi entirely |
| Kunnan toissijainen jätehuoltopalvelu (PIR `5 §`) | **kept, narrowed** | LS `1 §` applies its rules to *"kunnan toissijaiselle jätehuoltovastuulle"* and `41 §` speaks of *"toissijaisen siivoamisvastuun"*. The **word** is in both; the **service and its request procedure** are not. The entry keys on the phrase, and the question asks for the procedure. |
| Hyödyntäminen omassa maanrakentamisessa (LS `22 §`) | **DROPPED** | Pirkanmaa `17 §`: *"Rakennus- ja purkujätteen hyödyntämisestä maarakentamisessa määrätään näiden jätehuoltomääräysten § 19:ssa."* Both authorities regulate it. The clause **title** differs; the coverage does not. |
| Roskaantumisen ehkäiseminen yleisillä alueilla (LS `42 §`) | **DROPPED** | Pirkanmaa has no clause with that title and addresses roskaantuminen in **nine** chunks, `31 §` and `42 §` among them. A refusal label here would have been wrong. |

Three replacements were found by a `ts_stat` diff of the two authorities' lexemes, and each passes
the same two-sided check: **jäteastian puhdistustiheys** (LS `27 §` sets ≥1×/yr for sekajäte and
≥2×/yr for biojäte; Pirkanmaa `26 §` requires cleanliness and **no frequency**), **tieyhteydetön
saari** (LS `15 §`; Pirkanmaa never mentions road-less properties), and **lisäjäte** kept from the
original list. The population is still **6 + 8 = 14**, and 3 are asked in each direction.

**The near-miss that shaped the design.** `sakokaivo` — the colloquial word — is absent from both
documents while `saostussäiliö` is regulated at length. A refusal labelled on that word would have
been **wrong**, and refusing would have been the defect rather than the metric. Nothing in the
harness would have caught it. That is why `absent_lexeme` is documented as a **drift detector, not
a proof**, and why the absence claim itself is hand-made and recorded per entry.

### D5's ±0.13 is the wrong statistic, again

D5 reports refusal recall's interval as **±0.13** at R=14. That is one standard error
(`sqrt(0.25/14) = 0.134`), not an interval. The 95% figure is roughly **±0.25**, and the harness
computes a **Wilson** interval rather than a Wald one — Wald runs past 0 and 1 at these counts and
reports a width of **zero** at a perfect 14/14, which would publish certainty this population
cannot buy.

This is the third time the project has caught itself quoting the wrong statistic (slice 3's ±0.18,
this file's own ±0.18 note, now this). The interval is therefore **computed and printed by the
harness** rather than written in a document, which is the only version of this fix that stays true.

### The 45-minute failure that changed the boundary

**The first full run died at the 29th of 64 answers** on Groq's HTTP 400 `json_validate_failed`
with an empty `failed_generation` — the error code **tracer slice 2 attributed to the token cap**.
It was not the cap. The same question (`tapahtuman-jatehuoltosuunnitelma`) then succeeded twice on
the identical request, using **2,557 reasoning tokens** at both an 8k and a 16k cap.
`temperature=0` becomes `1e-8` at Groq, so the generation is stochastic and occasionally is not
valid JSON. **LiteLLM does not retry a 400** — correctly in general, since a 400 usually means the
request is wrong.

Two things were fixed in-slice, and the run cost ~$0.58 to learn them:

1. **`json_validate_failed` is now retried, bounded, and counted.** Retrying is not skipping: the
   question is still answered and scored, exhausting the retries still kills the run, and the count
   is printed because *"the answerer could not emit its envelope on n of 64 questions"* is a fact
   about the model under test.
2. **The run prints per-question progress.** The first version printed nothing for 45 minutes, so
   the failure arrived as a stack trace with no way to tell which question caused it.

**AC5 nonetheless behaved exactly as specified**, which is the part worth keeping: the run stopped,
exited non-zero, and reported no table over 28 of 64 questions.

### D8's token ceiling, re-derived here rather than in tracer 6

`answer.py` carried D8's 600K constant with a docstring recording that a legitimate 64-question
run is ~700K — a ceiling a correct run would trip. The re-derivation was assigned to *"the tracer
that first runs all 64 questions"*, which turned out to be this one. It is a **formula, not a new
constant**:

    ceiling_for(calls) = max(600_000, 2 x calls x 10_900)

600K is D8's figure kept as a floor; 10,900 is the measured tokens of one reasoning-on answer; 2 is
the headroom. Fitting a new constant would have bought the same problem again at the next question
count. **Seen red on the full-run path:** `--token-ceiling 1` stopped the run after one call
(10,884 tokens, $0.0210), non-zero exit.

### Spec deltas from this slice

- **D5's asymmetry table is corrected**: two topics dropped, one narrowed to a phrase, three
  replacements. R is unchanged at 14.
- **D5's ±0.13 is corrected to a computed Wilson interval** (~±0.25 at n=14), and refusal recall is
  printed as a diagnostic with its interval inline, never as a headline.
- **D8's 600K ceiling is replaced by a derived formula**, closing the confession tracer 2 opened.
- **D6's "one command" is deliberately deferred.** The answer phase is `fi-rag-eval answer --all`,
  a separate command, until tracer 6 derives the floor gate. Wiring an ungated networked phase into
  the zero-tolerance retrieval gate would make the deterministic half of the harness depend on a
  provider. Confessed in `REVIEW-DEBT.md` with tracer 6 named as the closer.
- **`json_validate_failed` has two causes**, and tracer slice 2's diagnosis of it is amended in
  place rather than left asserting the wrong one.

---

## Spec deltas

_None yet. Anything the build teaches that contradicts the above lands here, dated, rather than
being quietly edited into the text as though it always said that._

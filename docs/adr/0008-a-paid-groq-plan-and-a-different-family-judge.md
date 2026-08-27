# ADR-0008 — a paid Groq plan, and a judge from a different model *family*

- **Date:** 2026-08-27
- **Status:** accepted

## Context

Slice 5 builds the answering layer and its judge. Two questions had to be settled before a line of
code could be written, because both are hard to reverse and one spends money.

### The free tier cannot carry this slice, and that was measured rather than assumed

`CLAUDE.md`'s hard limit #1 previously read: *"the Owner intends to use Groq's free tier, so there
is no monetary ceiling to set and no paid run is planned"*, and noted that *"the binding constraint
is now rate limits, not money, and it is a worse one for this project."* That note was right, and
worse than it looked.

The corpus was measured, not estimated: **990 chars/chunk (Lounais-Suomi), 1209 (Pirkanmaa)** →
~450–550 tokens per chunk at Finnish token density, so a top-5 context is ~2250–2750 tokens.

| Workload per `make eval` run | Calls | ~Tokens |
|---|---|---|
| Answers (50 answerable + 14 refusal) | 64 | 198K |
| Judge on live answers | 50 | 110K |
| Judge on the frozen agreement sample | 50 | 110K |
| | **164** | **≈420K** |

Groq's free tier for `gpt-oss` and `qwen`: 30 RPM, 1K RPD, **8K TPM, 200K TPD**. RPM and RPD are
comfortable; TPM/TPD is not:

> **One full run is ~2.1x the entire daily token allowance**, and ~52 minutes of saturated
> throughput at 8K TPM.

Three consequences follow, and none is negotiable by tuning:

1. `DESIGN.md:121-122`'s *"`make eval` in CI on every pull request"* is **impossible** on the free
   tier — twenty PRs a month is ~8.4M tokens against a 6M monthly ceiling.
2. A 52-minute saturated run is precisely the *"no unattended eval loops"* the same hard limit
   forbids.
3. The only free-tier-compatible shapes either publish answer metrics over a **reduced N** — the
   one thing the domain guard-rail says destroys this project — or replace the live measurement
   with a replay.

Paid, at $0.15/$0.60 and $0.075/$0.30 per million: **≈$0.067 per run.**

### A judge that merely differs by *name* is not enough

`CONTEXT.md:59` required only *"a different model than the one under test"*. A judge sharing the
answerer's architecture and training lineage shares its blind spots, and will rubber-stamp
precisely the fabrications it exists to catch — while judge–human agreement looks healthy, because
the hand-labelled sample is small and the correlated failures concentrate in exactly the cases that
matter. The rule was weaker than the thing it was written to guarantee.

## Decision

**1. A paid Groq Developer plan is approved for this project.** Groq alone; any other paid provider
still requires an explicit ask. The ceiling is **$25/month**, set by the Owner at Groq on 27 Aug
2026, against a measured ~$0.067/run (~370 runs).

**2. The ceiling has three enforcers, and the one that matters is ours:** a per-run token budget in
code that hard-fails the run at ~600K tokens (~$0.15, roughly 2x a legitimate run); the LiteLLM
Proxy's per-key budget; and the provider cap. The steady state is seven cents — the thing that
costs money is a runaway, and a ceiling that lives only in a dashboard would let the harness
collect 429s while never noticing.

**3. `CONTEXT.md:59` is tightened from "a different model" to "a different model *family*".**

**4. ~~The pair is answerer `groq/openai/gpt-oss-20b`, judge `groq/llama-3.3-70b-versatile`.~~
AMENDED 27 Aug 2026, before any harness code — see below.** The original pairing was chosen from
Groq's public docs. It did not survive contact with the account.

## Amendment, 27 Aug 2026 — the pair, revised twice by evidence

**First, `llama-3.3-70b-versatile` does not exist on this account.** There is no Llama at all. The
text models actually served are `allam-2-7b` (Arabic-focused), `groq/compound` and `compound-mini`
(agentic systems that bundle tools — wrong for a judge), `openai/gpt-oss-120b`, `openai/gpt-oss-20b`,
`qwen/qwen3.6-27b` and `qwen/qwen3.8-27b`. Caught by listing the models before spending anything.

That created a tension the docs had hidden: **the strongest judge (`gpt-oss-120b`) is the same
family as the cheapest answerer (`gpt-oss-20b`)**, so decision 3 above and "cheapest adequate
model" could not both be honoured with a strong judge.

**Second, the capability smoke test disqualified `gpt-oss-20b` as the answerer — on comprehension,
not on price.** Five golden questions, the published cell's real top-5, both candidates, 10 calls,
~$0.01:

- On `biojatteen-kerays-jarjestaminen`, with the required chunk `#15` retrieved at rank 4,
  **`qwen/qwen3.6-27b` reproduced all three of the golden entry's required branches exactly** —
  the >10 000-resident taajama threshold at one dwelling, the taajama threshold at five, and the
  `17 §` composting exemption — each cited by address in the requested format.
- **`gpt-oss-20b` inverted that same conditional**, stating that properties composting under `17 §`
  are obliged to collect bio-waste separately when `15 §` exempts them. A flattened conditional —
  this project's failure mode #1 — **produced with the required chunk successfully retrieved.** Its
  Finnish also carried real errors (`las` for `lasi`, `maittuminen`, `jos kiinteistö kompostoivat`,
  `lukittuihin kaappeihin` for `lukituissa kaapeissa`).

The disqualifier is precise, and it is not "the answerer is weak" — a weak system under test is
fine, the harness exists to measure it. It is that **an inversion under perfect retrieval makes
comprehension failures and retrieval failures indistinguishable**, which would make the spec's
prediction 5 — the one that decides slice 6 — untestable.

**The revised pair: answerer `groq/qwen/qwen3.6-27b`, judge `groq/openai/gpt-oss-120b`.** Different
families, the strongest available judge, and the answerer chosen on measured Finnish comprehension.
"Cheapest adequate model by default" is honoured on **adequate** rather than on **cheapest**, which
is what the word was there for.

Two consequences carried into the spec rather than buried here: **Qwen's Groq pricing is
unconfirmed**, so this ADR's ~$0.067/run must be re-measured from `completion_cost()` and not
quoted until it is; and **`qwen/qwen3.8-27b` was never tested** — 3.6 is chosen because it is the
one that was measured, which is the only reason this project accepts.

## Rejected alternatives

- **Stay on the free tier with a recorded-run gate** — freeze model outputs in the repo, replay
  them in the gate, spend tokens only on a deliberate, attended re-record. This is the coherent
  free-tier answer: `make eval` stays deterministic and offline, `DESIGN.md:149-151` survives
  exactly, and CI is free. Rejected because the published number becomes a replay rather than a
  measurement, and silent provider-side model drift goes invisible — which is the precise thing
  judge–human agreement exists to catch. **This remains the fallback if the ceiling is ever hit,
  and it should be reconsidered rather than reinvented.**
- **Shrink the live phase to fit 200K TPD** — answer metrics over ~25 questions and a ~20-item
  agreement sample. Rejected on principle, not on cost: it publishes answer metrics over a
  deliberately reduced N.
- **Split rate-limit buckets across model families** to roughly double the free allowance, by
  putting the answerer and judge on different models. Rejected as unverified and insufficient:
  Groq's docs say limits apply at organisation level and only the account's own limits page shows
  the real table — and even if the buckets are per-model, one run per day is not a dev loop and CI
  is still out.
- **`gpt-oss-20b` answering with `gpt-oss-120b` judging.** The cheapest pairing, both production,
  and it satisfies `CONTEXT.md:59` *as previously written* — which is the argument for tightening
  the rule, not an argument for the pairing.
- **`llama-3.1-8b` as the answerer.** Cheapest possible. Rejected on the risk that 8B is too weak
  for dense administrative Finnish: a floor-bound answerer makes every answer metric uninformative
  for reasons unrelated to retrieval, and makes a judge problem indistinguishable from an answerer
  problem. Slice 5 opens with a five-question capability smoke test precisely because this risk is
  unmeasured for the 20b too.
- **A preview Qwen judge.** A third family, maximally uncorrelated with both. Rejected because a
  withdrawn preview model silently invalidates a committed agreement number and forces a re-label
  of the frozen sample.
- **A non-Groq provider (Claude, OpenAI direct).** Not evaluated on merit — the hard limit requires
  an explicit ask per provider, and only Groq was asked for. Recorded so nobody reads Groq's
  selection as a comparative verdict.

## Consequences

**Easy.** The slice can be built and run. CI-on-every-PR becomes affordable (~$1.34 for twenty
PRs). The cheapest-adequate-model rule is honoured by splitting the roles by size rather than by
using one model for both.

**Hard.**

1. **Money is back in scope, so a dormant hard limit is live again.** `CLAUDE.md`'s cost ceiling
   was only dormant because no paid run was planned. It is now a number with enforcers, and the
   in-code one has to be **seen red** like any other gate.
2. **Rate limits do not disappear on the paid plan.** The requirement they created stands and is
   load-bearing: retry-with-backoff, and a **hard failure** when a question cannot be scored —
   never a skip. A table over a silently reduced N is the failure this project cannot survive.
3. **`temperature=0` becomes `1e-8` at Groq**, so bit-determinism is unavailable at the provider.
   The answer-metric gate is therefore a derived floor rather than zero-tolerance, and
   `DESIGN.md:149-151`'s "reproduces that table from a clean clone" weakens from *exactly* to
   *within the floor band* for the answer metrics. The retrieval half is unaffected.

**Living with.** The exact Groq identifier for the 20b is unconfirmed — the docs list
`openai/gpt-oss-120b`, so `groq/openai/gpt-oss-20b` is the likely form, to be checked against the
live model list at build time rather than assumed.

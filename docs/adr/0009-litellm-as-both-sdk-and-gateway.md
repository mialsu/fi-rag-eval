# ADR-0009 — LiteLLM as both the SDK and the gateway, with the budget on a virtual key

- **Date:** 2026-08-28
- **Status:** accepted

## Context

`DESIGN.md:71` named LiteLLM as the LLM boundary before any code existed. Slice 5 is the first
slice that actually calls a model, so the decision had to be either honoured or reversed — and
`SPEC-slice-5` D10 re-examined it rather than inheriting it. It survived, but on grounds
`DESIGN.md` never stated, and the shape it survived in is not the shape D10 wrote down.

Three facts were established by measurement during tracer slice 2, not by reading documentation:

1. **The gateway needs a database or its budgets are ornamental.** LiteLLM reads the running spend
   total from `DATABASE_URL`; with no database client the budget check is skipped and requests are
   served past the limit, silently.
2. **The gateway does not apply budgets to its own master key.** Watched, in the attempt to see the
   gate go red: **$0.074910 of accumulated spend against a `max_budget` of $0.001 was served
   HTTP 200.** A virtual key with `max_budget: 0.00001` was refused **HTTP 429 — "Budget has been
   exceeded"** at $0.000029. The first configuration of this gateway authenticated with the master
   key, so its cost ceiling would have enforced nothing at all.
3. **`num_retries` is tenacity-backed and tenacity is not installed by litellm core.** The first
   real call through the gateway failed with *"tenacity import failed please run `pip install
   tenacity`"*. D10 counts LiteLLM's retry-with-backoff as satisfying the guard-rail's mandated
   retry requirement, which makes that dependency load-bearing rather than incidental.

## Decision

**LiteLLM is used twice: as the Python SDK the harness calls, and as the Proxy that call goes
through.** The Proxy runs in `compose.yaml` beside Postgres, on port 4010, pinned by image digest.

**The harness spends through a budgeted virtual key, never the master key.** The key's value is
*derived* from the master key (`sk-fi-rag-eval-<sha256(master)[:16]>`, `gateway.py`), so it is
stable across runs — which is what lets spend accumulate and the budget actually trip — and needs
no second secret in `.env`. The master key is used only to administer the gateway.

**The gateway gets its own Postgres with a persistent volume**, separate from the corpus database.
The two have opposite requirements: the corpus must *not* survive (it is dropped and rebuilt by
`create_schema` on every ingest) while the spend ledger must, or a monthly cap resets to zero on
every `make db-down`.

## Rejected alternatives

- **The `openai` SDK pointed at Groq's `base_url`** — rejected. Groq is OpenAI-compatible so this
  genuinely works and keeps the dependency list short, but it re-opens a settled decision to save a
  dependency while *losing* the provider price table and the retry layer we would then write
  ourselves. Reuse-before-building points at LiteLLM here, not away from it.
- **SDK only, the Proxy as a later slice** — rejected by the Owner knowingly. It is the
  disciplined answer and it keeps the largest slice yet from growing a service. Overridden because
  the per-key budget is a real enforcer this project needs, and because the LiteLLM *Gateway* is
  what job adverts mean by "LiteLLM" in a portfolio repository.
- **Proxy only, harness on the plain `openai` SDK** — rejected. Architecturally cleanest, but then
  no LiteLLM appears in the Python at all and a reader of the repo sees `openai`.
- **`litellm_settings.max_budget` alone, authenticating with the master key** — rejected because it
  was **measured not to work** (fact 2 above). This was the original configuration; it is recorded
  here rather than quietly fixed, because it is the exact shape of a "standard with no enforcer"
  and it survived writing, reviewing and committing right up until someone tried to watch it fail.
- **A fresh virtual key generated per run** — rejected. It would leave the enforcer looking
  installed and enforcing nothing: spend would reset to zero every run, so a budget denominated in
  a month could never be reached.
- **A virtual key created by hand and pasted into `.env`** — rejected. It breaks "clone it and run
  `make eval`", which is this project's own reproducibility claim, and it adds a second long-lived
  secret whose rotation nobody would remember.
- **One Postgres for both the corpus and the spend ledger** — rejected. One container has one
  persistence policy, and these two need opposite ones. Reversing the corpus database's `tmpfs` to
  serve the gateway would trade a real guarantee (the corpus cannot go stale) for an unrelated one.
- **Pinning the gateway image to `main-stable`** — rejected in favour of the digest. A floating tag
  silently changes the gateway, *including its provider price table*, and both the published cost
  figure and the token ceiling depend on that table.

## Consequences

**Easier.** Cost is a measured number rather than a maintained one: `response_cost` comes back on
every call from LiteLLM's price table, and the figure the harness reports is the same figure the
budget enforcer acted on. Per-model parameter differences (`reasoning_effort` accepts
`low|medium|high` on `gpt-oss` and only `none|default` on `qwen`) have one place to live.

**Harder.** `make eval` gains two services that can be down, and the honesty treatment Postgres
already has must extend to them: the boundary tests skip **loudly** when the gateway is absent, so
a green `make gate` with the gateway stopped proves less than it looks. There is now a $25/30d
budget on a key that, if genuinely exhausted, blocks the harness until it resets — which is the
enforcer working, and will not feel like it at the time.

**Lived with.** A spent budget and a rate limit arrive as the same HTTP 429, separated only by the
gateway's message text, so the boundary string-matches `"budget has been exceeded"` to avoid
retrying a refusal that will never succeed. That is fragile and is confessed in `REVIEW-DEBT.md`.

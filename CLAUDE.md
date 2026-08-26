# CLAUDE.md — fi-rag-eval

Guard-rails for every session on this project. Adopt every section verbatim except **Domain
guard-rails**, which you fill during `/new-project`. Precedence when docs disagree: the Owner's
live instructions > this file > any summary of it.

This project follows the **devkit method** (see the devkit repo: METHOD.md, PRINCIPLES.md).
Domain profile: **cli-tools**, with a `/ship`-only deploy check grafted from `web` and a
project-specific eval-integrity layer. The choice and its rejected alternatives are recorded in
`docs/adr/0001-domain-profile-cli-tools-hybrid.md` — read it before assuming a stock profile.

## Where this stands (26 Aug 2026)

**Nothing is implemented.** This repo is scaffold plus design docs: `DESIGN.md` (the approved
product design, milestones M1–M3) and `README.md`. There is no ingestion, no retrieval, no
answering, no golden set, and no CI.

- `make gate` is green — and that green proves the **toolchain only**. The single test asserts that
  the package imports. Do not read it as evidence about retrieval, answering, or metrics.
- `make eval` and `make docker-build` **exit non-zero on purpose.** They are honest stubs, not
  bugs. Do not "fix" them by making them pass — `make eval` must never print a metric table it did
  not compute. They go green when the thing behind them exists (M1 / M3).
- Read `REVIEW-DEBT.md` before assuming any capability exists, and `/verify-claim` anything a doc,
  an old note, or a past session says already works.

## Hard limits (immutable)
- Never push, open a PR, deploy, publish, or release without the Owner's explicit go. Local
  commits are fine; anything that leaves this machine is an explicit keystroke.
- Never spend money, add API keys, or send anything to a real external recipient without asking.
- Never run a destructive command on shared or irreplaceable state.
- When a permission layer refuses an action, **stop and stage it** — do not work around it.

## Build gates (green before every commit)

Run them all with `make gate`. Every one below has been run, and has been proven able to fail.

- Typecheck: `uv run mypy` (strict, over `src` and `tests`)
- Lint: `uv run ruff check .`
- Format: `uv run ruff format --check .`
- Tests: `uv run pytest`
- Build: `uv sync --locked && uv run python -c "import fi_rag_eval"` — proves a clean clone
  reproduces this environment. This is the per-commit build gate; the container image
  (`make docker-build`) is a `/ship`-time gate, not a per-commit one.
- Live exercise: see **Verify like a user** below.

A gate you haven't run is not a gate. Green tests gate; they do not prove.

## Definition of DONE
Built + gates green + **exercised the way a user hits it, with evidence** (`/verify-live`) +
copy is in the user's language + every cut corner confessed to REVIEW-DEBT.md + tracked.
Never ship: dead screens, fake zeros, raw IDs on a surface, "coming soon"/"unsupported".

For this project specifically, done is `DESIGN.md:122-128`: the README opens with a filled metric
table, `make eval` reproduces it from a clean clone, and CI fails on regression.

## Verify like a user

Three layers. The first is the `cli-tools` recipe; the second is this project's own and is the one
that matters most; the third applies only at `/ship`.

### 1. Run the harness for real
- Run `make eval` from a **clean clone into a fresh environment**, not your dev checkout, on the
  real corpus. A harness that only works in your working tree isn't done.
- Happy path: the metric table prints, exit code `0`.
- Bad-input path: missing corpus, unknown municipality, absent golden set → a helpful message on
  **stderr** and a **non-zero exit**. CI depends on this exit code, so it is a feature.
- **Report the N.** Never accept a table from a run where questions errored and were skipped. If
  the golden set has 50 questions, the run answered 50 or the table is void.
- Paste the actual terminal output as evidence. Not a summary of it.

### 2. Verify the measurement, not just the code
The instrument is the product. A green number from a broken harness is this project's worst
possible output, because everything else is trusted against it.
- **No circularity.** Golden-set chunk labels were hand-written from the sources. If any label was
  derived from what the retriever returned, `recall@k` is measuring the retriever against itself.
- **The judge fails a known-bad control.** Feed it answers with deliberately wrong citations and
  fabricated claims. If they pass as grounded, the judge is broken — fix the judge, not the answer.
- **Report judge–human agreement as a number** on the fixed sample, every run (`DESIGN.md:97-100`).
  "Spot-checked" is not a measurement.
- **Prove the regression gate goes red.** Break something on purpose — drop a chunk, downgrade the
  reranker, swap the model — and confirm CI actually fails. A gate never seen red is decoration.
- **Keep a held-out slice** the tuning never touches, or the numbers stop predicting real quality.
- Trust the arithmetic over the model: `recall@k` and MRR involve no judge, so when the two layers
  disagree, retrieval metrics win the argument.

### 3. The municipality hard filter (the #1 product failure mode)
`DESIGN.md:15,67` make cross-municipality answers structurally impossible rather than discouraged.
Verify that structurally:
- Ask a question answerable only from municipality A's rules, with municipality B's filter set →
  it must **refuse**, not answer from B's rules.
- Ask with no municipality set → it must not silently pick one.

### 4. At `/ship` only (grafted from the `web` profile)
- Hit the deployed Cloud Run URL and confirm the **served version matches the commit you merged**.
- Run one real query and one refusal case against the deployed URL, not localhost.
- Not adopted from `web`: browser-persona walks, restricted-user login, empty/error-state
  screenshots — there is no UI or auth in scope.

## What green tests can't prove here (watch for these)
- A metric that is green because the harness is circular (labels derived from retriever output).
- A judge that agrees by default, making groundedness look perfect.
- A metric averaged over a silently reduced N after questions errored out.
- Golden-set leakage: scores climb while real answer quality doesn't.
- The municipality filter applied *after* rerank, or skipped when the field is absent.
- Finnish compound words and inflection sinking lexical recall — it will look like a model problem
  and it isn't (`DESIGN.md:118`).
- Latency and cost per query measured on a warm cache.
- A regression gate that cannot actually go red.

## Process rules
- Shape before build: `/grill-with-docs` → agree a spec → wait for an explicit "go".
- One question at a time, each with a recommendation. Verify claims against the code, never
  memory. Ambiguity goes to CUSTOMER-QUESTIONS / the spec's open-questions, never a silent guess.
- Slice end-to-end; gate every commit; confess at every landing; fold review fixes into commits.
- Reuse before building. Write load-bearing decisions down as ADRs at the moment of decision.
- Build the golden set **before** tuning anything. `DESIGN.md:117` makes this the top risk; the
  milestone order in `DESIGN.md:107-111` does not enforce it, so the discipline lives here.

## Domain guard-rails  (authored by the Owner, 26 Aug 2026)

- **Scope (one sentence):** An evaluation harness for Finnish waste-regulation QA — it answers
  with citations or refuses, and it measures that behaviour well enough to fail CI on a
  regression. *The harness is the product; the RAG pipeline is the thing being measured.* When
  answer quality and measurement quality compete for a session, **measurement wins** — "retrieval
  got better but the harness can't prove it" is a failure, not progress.

- **Explicit non-goal:** **Corpus breadth.** No municipalities beyond the handful chosen for
  format variety until the existing ones' metrics are trustworthy. Adding a municipality feels
  like progress, costs a day, raises the document count, improves the instrument by nothing, and
  dilutes a hand-labelled golden set you then have to redo. (`DESIGN.md:40-44` additionally binds:
  no chat product, no auth/accounts/memory, no fine-tuning, no real-time ingestion.)

- **Must never do:** **Never publish a metric it did not compute.** No hand-written values in the
  README table. No table from a run that skipped or errored questions. Every published number is
  traceable to a run, with its N and its commit. Every other failure here degrades the project;
  this one destroys it, because the numbers are the only reason to trust anything else.

- **Project-specific hard limits:**
  1. **Cost ceiling on eval runs.** Cheapest adequate model by default; no unattended eval loops;
     the CI eval carries a hard cap. Ask before any run projected to exceed the ceiling.
     ⚠️ *The ceiling has no number yet — until the Owner sets one, ask before **any** paid run.*
     Recall the shape of the spend: ~50 questions × the model under test × a separate judge model,
     on every pull request.
  2. **No personal data, ever.** The corpus is public documents reached through the manifest only.
     Never log raw end-user queries or anything identifying. Note the unresolved tension:
     `DESIGN.md:74` says no personal data, while `DESIGN.md:35` specifies structured per-query
     logging — and a resident's real question can itself be personal data. Logging is where this
     bites; resolve it before any query log leaves this machine.

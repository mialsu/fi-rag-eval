# CLAUDE.md — fi-rag-eval

Guard-rails for every session on this project. Adopt every section verbatim except **Domain
guard-rails**, which you fill during `/new-project`. Precedence when docs disagree: the Owner's
live instructions > this file > any summary of it.

This project follows the **devkit method** (see the devkit repo: METHOD.md, PRINCIPLES.md).
Domain profile: **cli-tools**, with a `/ship`-only deploy check grafted from `web` and a
project-specific eval-integrity layer. The choice and its rejected alternatives are recorded in
`docs/adr/0001-domain-profile-cli-tools-hybrid.md` — read it before assuming a stock profile.

## Where this stands (27 Aug 2026)

**Slices 1–3 are built: the measurement spine, an honest golden set, and a lemmatising analyser
measured as a grid.** One authority (Lounais-Suomi, 50 clauses → 82 chunks) is ingested into
Postgres and retrieved lexically. `make eval` scores 21 hand-labelled questions in **12 cells**
— 4 analysers × 3 `ts_rank` normalisations — prints a table plus a per-question × cell pass
matrix, and exits non-zero if **any** cell regresses. Nothing else exists.

- **Published headline: complete-set recall@5 = 0.762 (N=21, k=5) in the `snowball/0` cell.
  Lexical leakage = 0.372.** Never quote the first without the second. The published cell is
  deliberately still the snowball control: **`lemma-reasm/1` measures 0.857**, and moving the
  published headline is the Owner's decision with a deliberate re-baseline, not something the
  winning number does by itself. `evaluate.PUBLISHED` is the single place that decides, and the
  gate fails if it moves without a re-record.
- **Lemmatisation is voikko, in Python — not `dict_voikko`.** Every doc written before 27 Aug
  named a Postgres text-search dictionary that **does not exist**: `postgres:17-alpine` ships only
  `dict_snowball`/`dict_int`/`dict_xsyn`, and neither libvoikko nor a Finnish hunspell dictionary
  is in the Alpine repositories. See `docs/adr/0005-lemmatisation-in-python-as-a-measured-grid.md`.
  Requires the **system packages** `libvoikko1` and `voikko-fi`; `uv sync` cannot supply them.
- **`ts_rank` normalisation 32 was the wrong flag, and that is a slice-3 correction.** It is
  `rank / (rank + 1)` — strictly monotonic, so it cannot reorder anything. The settings that
  divide by document length are 1 and 2. Slice 1's length finding holds, but correcting it is
  **not** a free win: normalisation 1 costs the control cell 0.143 of its headline and only *gains*
  recall in the compound-splitting cell. That sign flip is the interaction the grid existed to find.
- **Zero-overlap misses are gone: 4 → 0** under the reassembling analyser. Every remaining miss is
  reachable and lost in the *ranking*, which is a different failure with a different fix. That
  includes `taloyhtiö`/`asunto`/`keskusta` (#13/#15), so slice 2's "unreachable" finding is now
  sharper: the resident's words do reach those clauses and carry no weight in them.
- **Leakage rose 0.372 → 0.619 across the lemma cells with no question edited**, exactly as the
  debt entry predicted. The gate survived it **by construction**: leakage is recorded and compared
  per cell, so each is measured against its own reference. Do not "fix" a leakage rise by editing a
  question — that is the failure mode the metric exists to catch.
- **Not built:** embeddings, pgvector, reranking, any LLM call, a judge, answer generation,
  citations, refusal, a second authority, CI, Docker, Cloud Run. `make docker-build` still exits
  non-zero on purpose — do not "fix" it.
- **The authority hard filter is still unverified** — one authority means nothing to leak from.
  Read `specs/SPEC-slice-2-golden-set-rewrite.md` for why the corpus-breadth non-goal moved it.
- **Slice 4 is the vector layer for #13/#15**, per the slice-3 spec's pre-registered decision rule.
  It needs a cost-ceiling number from the Owner first — see the hard limits below.
- Read `REVIEW-DEBT.md` before assuming any capability exists, and `/verify-claim` anything a
  doc, an old note, or a past session says already works.

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
- Live exercise: `make eval` (which runs `make db-up` then `make ingest` first). See
  **Verify like a user** below. `make gate` does *not* run it, and the end-to-end tests inside
  `make test` **skip** when Postgres is down — so a green `make gate` with the database
  stopped proves the pure functions and nothing else. The analyser tests skip on the same terms
  when `voikko-fi` is absent; the reassembly rule itself is pinned by pure tests that always run.
  Requires Docker, `poppler-utils`, `libvoikko1` and `voikko-fi`.

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
- Golden-set leakage: scores climb while real answer quality doesn't. **Measured every run and
  gated to never rise, per cell.** It was 60% in slice 1 and is 37% now in the published cell; the
  reference for real questions is 39%. A rising headline with rising leakage is not an improvement.
  Note that a *better analyser* raises leakage on its own, with no question edited (0.372 → 0.619
  in slice 3) — which is why each cell is gated against its own recorded value and never against
  another cell's. Comparing across cells would fail the gate for a reason that has nothing to do
  with the golden set getting easier.
- The authority filter applied *after* rerank, or skipped when the field is absent.
- Finnish compound words and inflection sinking lexical recall — it will look like a model problem
  and it isn't (`DESIGN.md:118`).
- Latency and cost per query measured on a warm cache.
- A ranker whose defaults are wrong for the corpus: `ts_rank`'s default normalisation (0) does
  not divide by document length, so short chunks lose systematically. Measured: definition
  chunks are 39% of the corpus and were 0% of every top-5.
- **A knob that looks like a fix and is a no-op.** `ts_rank(..., 32)` is `rank / (rank + 1)`:
  monotonic, so it reorders nothing. It scored identically to the default in all eight cells of
  the first slice-3 run, which is the only reason it was caught. Read the flag's *formula*, not
  its name — and be suspicious of an axis whose cells agree to three decimals.
- **A junk lexeme from a hand-rolled morphological rule.** Its damage is displaced: it lowers
  precision on questions *other* than the one it was built for, so it surfaces as an unrelated
  cell regressing rather than as a bug in the rule.
- **A lemma index that is silently empty.** Three of the four `tsvector` columns are written by
  the application, not generated by Postgres, so an empty one makes a chunk unretrievable in that
  cell and the miss is attributed to the analyser. Asserted at ingest and again at every eval.
- A query stemmed a different number of times than the index. `to_tsquery` re-stems lexemes
  that came out of `to_tsvector`; that bug shipped in the first run of this harness and made
  the number look *worse*, not better, which is why nothing looked wrong.
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

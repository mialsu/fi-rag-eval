# CLAUDE.md — fi-rag-eval

Guard-rails for every session on this project. Adopt every section verbatim except **Domain
guard-rails**, which you fill during `/new-project`. Precedence when docs disagree: the Owner's
live instructions > this file > any summary of it.

This project follows the **devkit method** (see the devkit repo: METHOD.md, PRINCIPLES.md).
Domain profile: **cli-tools**, with a `/ship`-only deploy check grafted from `web` and a
project-specific eval-integrity layer. The choice and its rejected alternatives are recorded in
`docs/adr/0001-domain-profile-cli-tools-hybrid.md` — read it before assuming a stock profile.

## Where this stands (27 Aug 2026)

**Slices 1–4 are built: the measurement spine, an honest golden set, a lemmatising analyser
measured as a grid, and a second authority.** Two authorities are ingested into Postgres and
retrieved lexically — Lounais-Suomi (50 clauses → 82 chunks) and Pirkanmaa (48 clauses → 89
chunks), 171 chunks total. `make eval` scores **50** hand-labelled questions in **12 cells**
— 4 analysers × 3 `ts_rank` normalisations — prints a table, a per-authority breakdown, a
per-question × cell pass matrix and a paired-power matrix, and exits non-zero if **any** cell
regresses. Nothing else exists.

- **Published headline: complete-set recall@5 = 0.680 (N=50, k=5) in the `snowball/0` cell.
  Lexical leakage = 0.332.** Never quote the first without the second. **This is NOT comparable to
  the old 0.762 (N=21)** — the population changed. Per authority, as a diagnostic: Lounais-Suomi
  0.724 (N=29), Pirkanmaa 0.619 (N=21).
- **The instrument has statistical power for the first time.** Two cells are scored on the same
  questions, so comparing them is a **paired** test: six discordant questions must flip one way for
  p<0.05, at any N. At N=21 no comparison in the grid could reach that at any effect size. At N=50
  `lemma-reasm/0` (0.820) beats the published cell at **d=9, p=0.039**. `make eval` prints d and
  the exact McNemar p for every pair of cells, so nobody has to assume a 0.048 delta means
  something. **The ±0.18 absolute interval that slice 3 and this file used was the wrong
  statistic** — corrected in both specs; the correction made the argument for slice 4 *stronger*.
- **The published cell is still `snowball/0`, and moving it is now an evidence-backed question
  rather than a preference.** `evaluate.PUBLISHED` is the single place that decides, and the gate
  fails if it moves without a re-record. The cost of moving is quantified: the N target for
  detecting a half-of-misses fix rises from ~51 to ~84 on a lemma cell.
- **Slice 4's strongest prediction was REFUTED, and it changes slice 5.** The two authorities do
  use different words for the same things (`jäteastia`/`keräysväline`,
  `korttelikeräys`/`lähikeräysjärjestelmä`, `aluekeräyspiste`/`aluejätepiste`) and it *does* cost
  recall — a paired question passes for Pirkanmaa and fails for Lounais-Suomi from identical text.
  But zero-overlap misses stayed at **0**: the fork surfaces as a **ranking** failure, not an
  unreachable one, because a question shares plenty of other lexemes with its target. Per the
  spec's pre-registered decision rule (`< 4` synonym-caused zero-overlap misses), **the vector
  layer's case has weakened twice and must be re-argued from evidence, not from the plan.**
  Prediction 2 was also refuted: Pirkanmaa scores *higher* than Lounais-Suomi in 5 of 12 cells,
  and its questions are *less* leaky, so "its questions are easier" is not supported by the metric
  nominated to test it. **Slice 5 is the Owner's call and is not pre-registered.**
- **A slice-3 finding was retracted by the bigger set.** "Length normalisation helps only the split
  analyser" is false at N=50: normalisation 1 now *helps* `lemma-baseform` and is *neutral* for both
  split analysers. It rested on a one-question gain at N=21 (d=3, p=0.25) — never resolvable. The
  surviving claim is narrow: length normalisation costs the control cell and does not clearly help
  any lemma cell.
- **Lemmatisation is voikko, in Python — not `dict_voikko`.** `postgres:17-alpine` ships only
  `dict_snowball`/`dict_int`/`dict_xsyn`, and neither libvoikko nor a Finnish hunspell dictionary is
  in the Alpine repositories. See `docs/adr/0005-lemmatisation-in-python-as-a-measured-grid.md`.
  Requires the **system packages** `libvoikko1` and `voikko-fi`; `uv sync` cannot supply them.
- **A second authority adds ZERO distractors to an existing question.** The filter is applied
  before ranking and `ts_rank` has no IDF. Measured: with Pirkanmaa ingested and the questions
  untouched, all 12 cells scored *identically* to the N=21 baseline. `SPEC-slice-2`'s claim that
  the headline "should be expected to fall when the corpus grows, and the second authority roughly
  doubles it" is **corrected there** — that claim would otherwise excuse a drop from elsewhere.
- **The authority hard filter is verified at the retrieval layer, PARTIAL not CLOSED.** Every
  question's top-k is asserted to hold zero foreign-authority chunks, inside `evaluate`, for 50×12;
  seen red by deleting the WHERE clause, with a companion test proving foreign chunks really do
  enter the top-5 without it. But `CLAUDE.md`'s specified behaviour is *refusal*, and refusing needs
  an answering layer. Do not read a green filter assertion as a verified refusal.
- **ADR-0002 is amended: a municipality does NOT always resolve to exactly one authority.**
  Pirkanmaa's 1 § claims Sastamala only "(Mouhijärven ja Suodenniemen osalta)", so Sastamala is
  omitted from the map and refuses with a message naming the partial coverage. A Mouhijärvi
  resident is refused an answer that exists — accepted, and the *model* question (a level between
  authority and municipality) is the Owner's.
- **`18 a § KOMPOSTOINTI-ILMOITUS` is a real Pirkanmaa clause missing from the corpus.** It is
  absent from the document's own table of contents, so the body/TOC cross-check is silent and its
  text is absorbed into 18 §'s chunk. Two clauses, one address. No golden question points at
  Pirkanmaa 18 § — do not add one before this is fixed.
- **Not built:** embeddings, pgvector, reranking, any LLM call, a judge, answer generation,
  citations, refusal, a third authority, CI, Docker, Cloud Run. `make docker-build` still exits
  non-zero on purpose — do not "fix" it.
- **No held-out slice yet.** Deferred deliberately to N≈85: holding out 10 of 50 leaves a tuning set
  that cannot reach d=6 and a held-out set that never can.
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
  gated to never rise, per cell.** In the SNOWBALL CONTROL cell it was 60% in slice 1, 37% at N=21,
  and is **33.2% at N=50** — the 29 questions slice 4 added are *less* leaky than the 21 they
  joined, so the set got harder, not easier. The **published** cell now reads **55.0%**, which is a
  different analyser reading the same unedited questions and is **not** comparable to 33.2%. The
  reference for real harvested questions is 39%. A rising headline with rising leakage is not an improvement.
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
  1. **Cost ceiling on eval runs.** Cheapest adequate model by default; no unattended eval loops.
     **Resolved 27 Aug 2026: the Owner intends to use Groq's free tier, so there is no monetary
     ceiling to set and no paid run is planned.** Still ask before introducing *any* paid provider.
     Recall the shape of the spend it would carry: ~50 questions × the model under test × a
     separate judge model, on every pull request.
     **The binding constraint is now rate limits, not money, and it is a worse one for this
     project.** A free tier throttles; a throttled eval run means some questions error. This
     harness must never publish a table over a silently reduced N, so the answering slice needs
     retry-with-backoff and a **hard failure** when a question cannot be scored — never a skip.
     That requirement is now load-bearing and belongs in the answering slice's spec.
     Two smaller consequences: Groq serves open models rather than Claude, which is *fine* and even
     helpful for `CONTEXT.md`'s rule that the judge must be a different model than the one under
     test; and a free tier's data-usage terms want reading once, though the corpus is public
     documents and the queries are golden-set questions, so the no-personal-data limit is not at
     risk today.
  2. **No personal data, ever.** The corpus is public documents reached through the manifest only.
     Never log raw end-user queries or anything identifying. Note the unresolved tension:
     `DESIGN.md:74` says no personal data, while `DESIGN.md:35` specifies structured per-query
     logging — and a resident's real question can itself be personal data. Logging is where this
     bites; resolve it before any query log leaves this machine.

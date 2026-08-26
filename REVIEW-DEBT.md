# REVIEW-DEBT.md — fi-rag-eval

The standing ledger of everything the green tests do NOT prove. Written at the moment a corner
is cut (`/confess`), read first by any architecture or review session, dispositioned by the
Owner (fixed / accepted-with-reason / promoted-to-issue). A stale or empty-but-should-not-be
ledger is worse than none, because sessions trust it.

<!-- Newest first. Template for an entry: -->
<!--
## YYYY-MM-DD — <one-line title>
- **What:** <what is stubbed / faked / deferred / weaker than spec>
- **Where:** <file:line anchors>
- **What green tests do NOT prove here:** <the specific gap>
- **Disposition:** open
-->

## 2026-08-26 (slice 1) — the golden set leaks its own source vocabulary

- **What:** The eight questions were written with the source PDF open, so they reuse the
  document's exact terms. Measured, not suspected: **60% of each question's stemmed content
  words appear verbatim in its target chunk** (per question 33–80%). A resident asks
  *"milloin biojätteet viedään?"*, not *"kuinka usein biojäteastia on tyhjennettävä
  kesäaikana?"*.
- **Where:** `corpus/golden/lounais-suomi.yaml`; quantified in
  `specs/SPEC-slice-1-measurement-spine.md` (Measured result).
- **What green tests do NOT prove here:** the headline `complete-set recall@5 = 0.875` is
  honestly computed and still nearly meaningless as a quality estimate — it measures an
  instrument easier than the task. Worse, the harness cannot currently *detect* a retrieval
  improvement or regression in the vocabulary gap that matters, because its questions do not
  contain that gap. This is `CLAUDE.md`'s golden-set-leakage failure mode, arrived on day one.
- **Disposition:** open — **the highest-priority item in the project.** Rewriting the
  questions in a resident's vocabulary comes before any retrieval change (measurement wins
  ties). Blocks trusting slice 3's numbers.

## 2026-08-26 (slice 1) — the headline is computed over N=8

- **What:** The golden set has 8 questions and 10 required chunks against `DESIGN.md`'s ~50.
  The 95% interval on 0.875 is roughly ±0.23. Only 2 of 8 questions span more than one chunk,
  so complete-set recall and per-chunk recall nearly coincide — the very distinction ADR-0003
  exists to draw is not yet visible. The miss diagnostic has 1 data point, so its
  slice-3 decision rule cannot fire.
- **Where:** `corpus/golden/lounais-suomi.yaml`, `eval/baseline.json`.
- **What green tests do NOT prove here:** the regression gate compares exact values and will
  fire correctly, but a single question flipping moves the headline by 0.125. Any change
  smaller than that is invisible, and any conclusion drawn from a difference this size is
  noise.
- **Disposition:** open — grows with the golden set. Every published number carries its N.

## 2026-08-26 (slice 1) — definition sub-keys are a paragraph prefix, not the defined term

- **What:** ADR-0004 addresses a definition chunk as `#2.biojate`. The real definiendum is a
  **bolded phrase** ("Saostus- ja umpisäiliölietteellä"), and `pdftotext` cannot see bold, so
  the phrase boundary is not recoverable from the text. The sub-key is instead the shortest
  leading-word prefix that is unique within the clause: `#2.biojatteella`,
  `#2.kunnan-jarjestamalla`. Three definitions open with "Kunnan" and only those pay for it.
- **Where:** `src/fi_rag_eval/chunking.py` (`_definition_sub_keys`); ADR-0004 corrected.
- **What green tests do NOT prove here:** the addresses are stable and unique *for this
  document*. Adding a definition that newly collides with an existing one-word key would
  lengthen that key and invalidate the label pointing at it. `pdftohtml -xml` does expose the
  bold runs and would make the term exact, at the cost of a second extractor.
- **Disposition:** open — accepted. Revisit if a new document version collides.

## 2026-08-26 (slice 1) — the ranker has a known-wrong property, left in on purpose

- **What:** `ts_rank` runs at its default normalisation (0), which does **not** divide by
  document length. Long clauses therefore out-rank short ones on accumulated term weight:
  definition chunks are 39% of the corpus and were 0% of every top-5, and the run's single
  miss is a 40-word definition losing to 2,000-character clauses (length/rank correlation
  +0.673). This is a real retrieval defect and slice 1 deliberately does not fix it.
- **Where:** `src/fi_rag_eval/db.py` (`search`); measured in the spec's Measured result.
- **What green tests do NOT prove here:** the baseline is green *including* this defect, so a
  green gate is not a claim that retrieval is adequate. It is a claim that retrieval has not
  got worse.
- **Disposition:** open — this is slice 3's first and cheapest candidate
  (`ts_rank(tsv, q, 32)`), to be measured only after the golden set is fixed.

## 2026-08-26 (slice 1) — the end-to-end tests skip when Postgres is down

- **What:** `tests/test_retrieval.py` is the only place extraction, chunking, addressing,
  indexing and ranking are exercised together. It skips — loudly, with the connection error
  in the skip reason — when the database is unreachable. `make gate` can therefore be green
  having proven only the pure functions.
- **Where:** `tests/conftest.py` (`corpus` fixture).
- **What green tests do NOT prove here:** exactly what the skip says. Verified by pointing
  `FI_RAG_EVAL_DATABASE_URL` at a dead port: 10 tests skip, `make gate` still passes.
- **Disposition:** open — closes when CI exists (M3) and runs the gate with a service
  container, making the skip impossible there.

## 2026-08-26 (slice 1) — one chunk address covers two editions of the document

- **What:** The ingested PDF is the base regulations (in force 1.8.2024) **with 25 § amended
  22.10.2025**. The address uses the in-force date read from 49 §, so both editions of 25 §
  would address as `lounais-suomi@2024-08-01#25`.
- **Where:** `corpus/manifest.yaml`, `src/fi_rag_eval/ingest.py` (`read_effective_date`).
- **What green tests do NOT prove here:** which text a `#25` label actually meant. The
  content hash stored beside each chunk detects the difference, and ingesting the other
  edition would collide on the primary key and fail loudly rather than drift — but the
  address alone does not distinguish them.
- **Disposition:** open — accepted for one authority and one version. Must be settled before
  a second version of the same document is ingested.

## 2026-08-26 — momentti-level applicability is not modelled

- **What:** **1 §** scopes which clauses bind non-residential properties *by sub-clause* — `17 §
  Kompostointi, momentit 1–3, 5, 7–9`, `23 § Jäteastiatyypit, momentit 1–3, 6`. (Written up as 3 §
  during shaping; the list is in 1 § Soveltamisala — verified against the source at ingest, and
  corrected in ADR-0004.) Chunks are whole clauses, so no chunk can express "only momentit 1–3, 5,
  7–9 apply to you". Deferred deliberately:
  it matters for business properties, and the users in `DESIGN.md:22-26` are the advisor and the
  resident.
- **Where:** decided in `docs/adr/0004-clause-chunking-carve-outs-and-stable-addressing.md`; will
  land in the chunker once it exists.
- **What green tests do NOT prove here:** nothing in the golden set will fail because of this unless
  business-property questions are added *as a known-fail class*. Without that, the gap is invisible:
  the system answers a business-property question using clauses that do not bind it, confidently and
  with a correct-looking citation.
- **Disposition:** open — accepted for the MVP. Revisit if the advisor persona turns out to field
  business-property questions in practice.

## 2026-08-26 — slice 1 does not exercise the hard filter

- **What:** Slice 1 ingests one authority, so there is no second jurisdiction to leak from. The
  authority filter and the chunk address are built, but the adversarial cross-authority case — ask a
  Kuopio-only question with `authority=lounais-suomi` and require a refusal — cannot run until the
  second authority lands in slice 2.
- **Where:** `specs/SPEC-slice-1-measurement-spine.md` (non-goals, and slice 2).
- **What green tests do NOT prove here:** a green slice-1 eval says nothing about `DESIGN.md:15`'s
  worst failure mode. "Cross-municipality answers are structurally impossible" stays an unverified
  claim for the whole of slice 1, and the filter is untested code.
- **Disposition:** open — closes at slice 2, which exists primarily to close it.

## 2026-08-26 — `make eval` is a stub that exits non-zero

- **What:** The project's headline command, and its definition of done, does not exist. `make eval`
  prints an explanation to stderr and exits 1. Chosen over omitting the target so the contract is
  visible, and over a passing no-op so it can never be mistaken for a green run.
- **Where:** `Makefile:36-42`
- **What green tests do NOT prove here:** `make gate` is green while the product does not exist.
  The gate proves the toolchain, not the pipeline. Nothing in CI yet computes a metric, so nothing
  yet defends against the regression this project was built to catch.
- **Disposition:** **CLOSED 26 Aug 2026 (slice 1).** `make eval` computes a real metric table and
  exits 0, and was seen to exit non-zero on all five failure paths: a degraded chunk (metric fell),
  a deleted chunk (unresolvable label), a shrunk golden set (N mismatch), a changed `k`, and an
  empty corpus. What remains open is the *quality* of the measurement — see the golden-set leakage
  entry above — and CI, which is still absent.

## 2026-08-26 — `make docker-build` is a stub; no Dockerfile exists

- **What:** No container image, so the Cloud Run deploy in the design is unreachable. The target
  exits non-zero rather than pretending.
- **Where:** `Makefile:44-46`
- **What green tests do NOT prove here:** The build gate proves a clean `uv sync --locked` and an
  import — it says nothing about whether this runs in a container or on Cloud Run.
- **Disposition:** open — closes at M3 (20 Sep 2026).

## 2026-08-26 — the only test asserts an import

- **What:** `tests/test_smoke.py` asserts the package imports and reports a version. That is all
  the test suite does. The gate's `test` step is therefore near-vacuous today.
- **Where:** `tests/test_smoke.py:9-11`
- **What green tests do NOT prove here:** Literally everything. "1 passed" here means the venv
  works. It must not be read as evidence about retrieval, answering, or metrics.
- **Disposition:** **CLOSED 26 Aug 2026 (slice 1).** 53 tests: extraction normalisation and
  chunking against the real document's own hazards, addressing, metric arithmetic, and 10
  end-to-end tests over a live corpus. Superseded by the narrower entry above — those 10 skip
  when Postgres is down.

## 2026-08-26 — no CI workflow exists

- **What:** The regression gate described in the design (`make eval` on every pull request, metric
  table posted as a PR comment, fail on a drop past threshold) is not wired. There is no
  `.github/workflows/`.
- **Where:** repo root — absent by omission.
- **What green tests do NOT prove here:** Gates proven on this machine are not proven in CI. Until
  a workflow exists and has been seen to go red on a real regression, the central claim of this
  project is untested.
- **Disposition:** open — closes at M3.

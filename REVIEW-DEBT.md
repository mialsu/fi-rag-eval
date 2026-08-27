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

## 2026-08-27 (slice 3) — the compound reassembler is a hand-rolled morphological rule

- **What:** `reassembled_parts` folds voikko's `WORDBASES` morphs back into words using a rule I
  wrote, not one voikko supplies. It is the component that buys the `määräyksistä` /
  `jätehuoltomääräyksistä` match — and its first draft emitted the lexeme `'tyhjentää)tävä'` and
  left bound prefixes standing alone as junk. Measured on this corpus: of 2,513 distinct word
  forms, **76 produce at least one part that voikko itself cannot analyse as a word**
  (`peräinen`, `pisteinen`, `määräyksinen`, `kiinteis`). Most come from voikko's own `-inen`
  over-analysis, which arrives as a second reading and is kept under D9.
- **Where:** `src/fi_rag_eval/analyse.py` (`parse_wordbases`, `reassembled_parts`); pinned by 12
  recorded-`WORDBASES` fixtures in `tests/test_analyse.py`.
- **What green tests do NOT prove here:** that the rule is right for Finnish. It is right for the
  12 shapes in the fixture set and it does not crash on the other 2,501. A junk lexeme's damage is
  **silent and displaced**: it lowers precision on questions *other* than the one it was built
  for, which shows up as an unrelated cell regressing. Two mitigations, both structural rather
  than linguistic: the baseform is always emitted first, so a bad split can only add noise and
  never remove signal; and the conservative split is measured alongside, so the reassembler has to
  out-score it or be deleted.
- **Disposition:** open — **the reassembler earned its place this slice** (best reasm cell 0.857
  vs best safe cell 0.810, exactly one question). Kept. The fixture set is the thing to grow, and
  it grows from real misses, never from invented words.

## 2026-08-27 (slice 3) — lemmatisation costs precision, and the cost is now visible

- **What:** Lemmatisation is not free. `kerata-vai-kompostoida` passes in `snowball/0` and fails
  in **every one of the eight lemma cells**; `kuka-hankkii-jateastiat` passes at `snowball/0` and
  fails in the best cell. The net is positive (16/21 → 18/21) but it is a net, not a gain: the
  aggregate hides one question won and one lost in the baseform cell, which is why "cause 1 alone
  flips no whole question" was right about the number and wrong about the mechanism.
- **Where:** the per-question × cell matrix printed by `make eval`; `lemma-reasm/1` detail.
- **What green tests do NOT prove here:** which of the two effects dominates on questions this
  golden set does not contain. With N=21 a one-question regression is 0.048 of the headline and
  well inside the ±0.18 interval, so "lemmatisation helps" is a claim about 21 questions.
- **Disposition:** open — accepted. The regressed questions are not repaired by editing them;
  that would be the leakage failure mode with extra steps.

## 2026-08-27 (slice 3) — the lemma indexes are written by the application, not by Postgres

- **What:** The morphology lives in Python (ADR-0005), so `lemma_base_tsv`, `lemma_safe_tsv` and
  `lemma_reasm_tsv` cannot be `GENERATED` columns the way `tsv` is. A row inserted by anything
  other than this ingest gets an empty index in three of the four cells. The
  database-enforced invariant "the index always agrees with the body" is given up for those three.
- **Where:** `src/fi_rag_eval/db.py` (`SCHEMA`, `set_lemma_vectors`,
  `assert_lemma_vectors_populated`); `src/fi_rag_eval/ingest.py` (`index_lemmas`).
- **What green tests do NOT prove here:** that the columns *agree with the body*. They prove only
  that every column is non-empty for every chunk — checked at ingest and again at the start of
  every eval — and that the harness refuses to score a corpus where one is not. A body edited in
  place without re-running the ingest would leave a stale lemma index and a correct `tsv`, and
  nothing would notice. The mitigation that exists is the same one the corpus has: ingestion is a
  full reload, never incremental.
- **Disposition:** open — accepted, and cheaper than the rejected alternative (a custom Postgres
  image with a voikko dictionary built from source, which would put a build step in front of
  `docker compose up` and make the image ours to maintain). `tsv` deliberately **stays** generated
  rather than being demoted for symmetry, so the published cell keeps its invariant.

## 2026-08-27 (slice 3) — the stopword decision is borrowed from snowball, not chosen

- **What:** The lemma analysers drop a word when Postgres's `finnish` configuration drops it,
  asked of Postgres per token rather than answered from a vendored list. Not in the spec — decided
  during implementation, because without it the lemma cells would index and query `olla`, `ja` and
  `mitä` while the control cell does not, and every cell-to-cell delta would be
  lemmatisation *plus* the absence of stopping. Two variables, one number.
- **Where:** `src/fi_rag_eval/db.py` (`snowball_stopwords`), `analyse.Morphology.positioned`.
- **What green tests do NOT prove here:** that snowball's Finnish stop list is the right one for a
  lemmatised index. It is a *surface-form* list, so an inflected function word that snowball keeps
  is kept here too. It was chosen to hold the variable still, not because it is optimal — and it
  silently sets the denominator of the leakage metric, which is the least visible thing about it.
- **Disposition:** open — accepted for this slice. Revisit only with a lemma-level stop list
  measured as its own grid axis, never tuned by hand on these 21 questions.

## 2026-08-27 (slice 3) — the raw-token fallback keeps a word findable only in one inflection

- **What:** 55 of 2,513 forms (2.2%) get no analysis at all and fall back to their lowercased
  surface token: `bokashilla`, `fermentoidaan`, `esim`, `840-1`, URLs. So the corpus indexes
  `bokashilla` and a resident asking about `bokashi` still misses it. The fallback prevents the
  word vanishing from the index; it does not make it reachable.
- **Where:** `analyse.word_lexemes`; `tests/test_analyse.py::test_an_unanalysable_word_falls_back_to_its_raw_token`.
- **What green tests do NOT prove here:** any coverage of loanwords and neologisms, which is
  exactly where a waste-composting vocabulary keeps its jargon. No golden question currently
  depends on one, so the gap is invisible in the metrics.
- **Disposition:** open — accepted. A question about `bokashi` would surface it honestly, and is
  a better fix than a hand-written synonym list.

## 2026-08-27 (slice 3) — a better cell is measured than the one the README publishes

- **What:** `lemma-reasm/1` scores 0.857 against the published `snowball/0`'s 0.762. The README
  still publishes `snowball/0`, deliberately: which cell is the headline is the Owner's decision
  and comes with a re-baseline, not something the winning number does by itself. Until that
  decision, the published table understates what the retriever can do — and the gate enforces the
  gap by failing if `PUBLISHED` moves without a re-record.
- **Where:** `src/fi_rag_eval/evaluate.py` (`PUBLISHED`), `report.compare`.
- **What green tests do NOT prove here:** that 0.857 would survive publication. It is one cell of
  twelve chosen after seeing all twelve, on 21 questions, with no held-out slice — which is the
  overfitting surface `CLAUDE.md` warns about, and the reason the choice is a decision rather than
  an automatic promotion.
- **Disposition:** **open, and awaiting the Owner.**

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
- **Disposition:** **LARGELY CLOSED 27 Aug 2026 (slice 2).** Leakage is now computed on every
  run, published beside the headline, and **gated to never rise**. The set was rewritten to 21
  questions — 6 copied verbatim from the authority's own resident-facing pages, 15 authored under
  the rule *name the thing with the document's noun, ask with a person's verb* — and leakage fell
  60% → 37%, below the 39% measured for real harvested questions. The headline fell 0.875 → 0.762
  with it. What stays open is the two entries below: leakage understates itself, and 21 is not 50.

## 2026-08-27 (slice 2) — lexical leakage understates itself, and will rise on its own

- **What:** Leakage is measured *after* stemming, so a word the question and its target chunk
  both contain but which stems **apart** counts as clean. `biojäteastia` → `biojäteast` in a
  query while `biojäteastiaan` → `biojäteastia` in the corpus; a human eye sees one shared word,
  the metric sees none. Consequence: **leakage will rise when lemmatisation lands in slice 3,
  through no change whatsoever to the questions**, and the gate will fire.
- **Where:** `src/fi_rag_eval/metrics.py` (`lexical_leakage`), pinned in
  `tests/test_retrieval.py::test_the_same_word_stems_differently_in_query_and_corpus`.
- **What green tests do NOT prove here:** that 0.372 is the true overlap between these questions
  and their targets. It is the overlap *the current analyser can see*, which is a floor.
- **Disposition:** **CLOSED 27 Aug 2026 (slice 3) — by construction, not by waiver.** Measured:
  leakage is 0.372 under snowball, **0.506** under baseform lemmatisation, **0.568** with the
  conservative split and **0.619** with the reassembled one — a 0.247 rise with not one question
  edited, and well above the 0.42–0.48 the slice-3 spec predicted. The gate did not have to be
  waved through, because the baseline now records leakage **per cell** and each cell is compared
  only against itself: a lemma cell's leakage is measured against the lemma cell's own reference,
  which compares like with like. The rule "leakage must never rise" is intact and now has twelve
  independent guards instead of one. What the entry got right and is worth keeping: 0.372 was
  never the true overlap, only the overlap the old analyser could see.

## 2026-08-27 (slice 2) — the headline is computed over N=21, and refusals are still unsupported

- **What:** 21 questions and 24 required chunks against `DESIGN.md`'s ~50; the 95% interval on
  0.762 is roughly ±0.18. Only 3 of 21 span more than one chunk, so complete-set and per-chunk
  recall still nearly coincide and the distinction ADR-0003 exists to draw is not yet visible.
  Separately, the harness **rejects** a golden entry with empty `required_chunks`, so genuine
  refusal cases cannot be represented — one real candidate is already in hand, LSJH's own
  *"Miten kompostorin saa toimimaan?"*, which the regulations do not answer.
- **Where:** `corpus/golden/lounais-suomi.yaml`; the rejection is deliberate in
  `src/fi_rag_eval/golden.py` and `metrics.py` (an empty required set scores a vacuous 1.0).
- **What green tests do NOT prove here:** the miss diagnostic now has 6 data points rather than
  1, which was enough to confirm slice 1's claim 1 — but a single question flipping still moves
  the headline by ~0.048, and no refusal behaviour is measured at all.
- **Disposition:** open — the next tranche of questions is better written against two
  authorities, so it rides with slice 3 or 4. Refusal entries land with the answering slice.

## 2026-08-26 (slice 1) — superseded: the headline was computed over N=8

- **What:** 8 questions, 10 required chunks, 1 miss — the diagnostic had no power and its
  slice-3 decision rule could not fire.
- **Disposition:** **CLOSED 27 Aug 2026 (slice 2).** Superseded by the N=21 entry above. The
  diagnostic now has 6 misses and did fire: 4 of 6 are zero-overlap, so slice 3 is lemmatisation.

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
- **Disposition:** open — **measured in slice 3, and the cheap candidate was the wrong one.**
  `ts_rank(tsv, q, 32)` is documented as "divides the rank by itself + 1" — that is
  `rank / (rank + 1)`, a strictly monotonic rescale that **cannot reorder a single result**. The
  first run of the slice-3 grid scored all eight cells identically at 0 and 32, which is what sent
  us back to the manual. The settings that do divide by document length are 1 and 2, and they are
  now the grid's second axis. The finding itself holds — both put the missed definition chunk into
  the top 5 — but the fix is **not** a free win: normalisation 1 *costs* the control cell 0.143 of
  its headline and normalisation 2 costs it 0.333, because most golden targets are full clauses
  rather than definitions. It gains recall only in the compound-splitting cell. Pinned by
  `test_normalisation_32_cannot_reorder_anything` and
  `test_length_normalisation_helps_only_the_split_analyser`.

## 2026-08-26 (slice 1) — the end-to-end tests skip when Postgres is down

- **What:** `tests/test_retrieval.py` is the only place extraction, chunking, addressing,
  indexing and ranking are exercised together. It skips — loudly, with the connection error
  in the skip reason — when the database is unreachable. `make gate` can therefore be green
  having proven only the pure functions.
- **Where:** `tests/conftest.py` (`corpus` fixture).
- **What green tests do NOT prove here:** exactly what the skip says. Verified by pointing
  `FI_RAG_EVAL_DATABASE_URL` at a dead port: 10 tests skip, `make gate` still passes.
- **Disposition:** open — closes when CI exists (M3) and runs the gate with a service
  container, making the skip impossible there. **Widened in slice 3:** the analyser tests skip on
  the same terms when `voikko-fi` is absent, because the dictionary is a system package `uv sync`
  cannot supply. The reassembly rule itself is pinned by *pure* tests over recorded `WORDBASES`
  strings, which run regardless — what skips is the proof that those recordings still match
  today's dictionary. CI must install `libvoikko1` and `voikko-fi` or it inherits the same hole.

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

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

## 2026-08-31 — a golden label was WRONG for two slices, and the detector guarding it could not have caught it

- **What:** `ooc-autonrenkaiden-vastaanotto` asserted that `rengas` appears in neither authority
  *"missään muodossa"*. Both `2 §` definitions enumerate `renkaat`, and `12 §` says where
  producer-responsibility waste goes. The corpus answered the question outright. The answerer
  answered it correctly and was scored as having **missed a refusal** — the failure direction that
  makes a good answerer look worse. The entry is removed (14 → 13) and a lemma-aware check now runs
  beside the substring one.
- **Where:** `corpus/golden/refusals.yaml` (tombstone); `src/fi_rag_eval/db.py`
  (`chunks_matching_lemmas`, `lemma_tsquery`); `src/fi_rag_eval/evaluate.py`
  (`ABSENCE_ANALYSER`, `needle_lemmas`, `_present`).
- **What green tests do NOT prove here:** **that the other twelve labels are right.** The sweep that
  found this one cleared eleven and corrected one, but it could only look for what a *lemma* check
  can see. It provably cannot see a synonym under a different compound —
  **`ooc-romuajoneuvon-toimituspaikka` is the standing example and it is still in the set**:
  `romuautot` is in the same enumeration, so half that question is answerable from the corpus, and
  neither check will ever say so. The Owner kept the label (its second half — deregistration,
  romutustodistus — genuinely is not in the documents) and the false `label_source` was corrected in
  place. Every remaining entry rests on a hand-made claim in `absence_source`; the lexeme only keeps
  it from rotting. **The prior of "one wrong label in this population" is no longer zero, and the
  only reason this one surfaced is that the answerer challenged it.** Labels a compliant answerer
  never challenges are still never checked.
- **A second gap this exposed:** the detector had been reachable **only** through `fi-rag-eval
  answer` — a ~$0.76, ~50-minute, network-dependent command. A gate nobody runs before a commit is
  not a gate, and this one was not run between 27 and 31 August. It is now in `make eval`.
- **Disposition:** open — the invisible-synonym class is accepted for now and named here. Revisit
  when the N≈85 tranche re-authors the population, which is the natural moment to re-derive every
  `absence_source` from the clause lists rather than to spot-check it.

## 2026-08-31 — precision* and the D11 inversion were both built without going through shaping

- **What:** Two changes landed on the Owner's live decision rather than through
  `/grill-with-docs` → `/to-spec` → go. (1) **`precision*`**, the restricted refusal-precision
  reading — which the spec's own open-questions entry had explicitly called *"a metric the spec never
  shaped, and inventing one mid-tracer is scope-filling"*. (2) **D11's inversion** (ADR-0012), a
  post-hoc change to a pre-registered publication decision, made after seeing the data that motivated
  it.
- **Where:** `src/fi_rag_eval/metrics.py` (`restricted_precision`, `excused`);
  `src/fi_rag_eval/report.py` (`_restricted_precision_lines`, `format_judged`);
  `docs/adr/0012-*.md`; `specs/SPEC-slice-5-answering-and-judge.md` (D11 amendment banner).
- **What green tests do NOT prove here:** that either was the right *shape*. The tests pin the
  arithmetic and the ordering; they cannot pin that a second precision denominator is a metric worth
  having rather than one more number to quote selectively. On D11: changing a pre-registered decision
  after seeing the data is the exact shape this project exists to refuse. The mitigations are
  recorded in ADR-0012 and are real but partial — the change moves *which* metric leads rather than a
  threshold, a population or a value, and it makes the reported figure **worse-looking** (0.472 rather
  than 1.000). An auditor should still count this as a spec delta and treat the next such change with
  more suspicion, not less.
- **Disposition:** open — accepted by the Owner, recorded rather than fixed.

## 2026-08-31 — the inverted judged table has been seen only in tests, never in a live run

- **What:** `format_judged` now leads with branch coverage, and three tests assert it (including the
  ordering and the never-alone rule). **No live `fi-rag-eval judge` run has rendered it**, because
  that costs ~$0.07 and ~7 minutes and needs `make services-up` plus a filled `.env`, and no spend
  was authorised for it.
- **Where:** `src/fi_rag_eval/report.py:format_judged`; `tests/test_judge.py`
  (`TestD11IsEnforcedWhereTheTableIsRendered`).
- **What green tests do NOT prove here:** that the real table reads well — column alignment against
  real values, and whether the `<- THE HEADLINE` marker sits where a reader's eye lands. The
  *arithmetic* is unaffected: no metric changed, only the order and the wording.
- **Disposition:** open — clears itself on the next judge run, which tracer 5 needs anyway.

## 2026-08-31 — the refusal population is smaller, so its intervals are wider

- **What:** Removing one entry took the refusal population from 14 to 13. Recall reads
  **0.923 [0.67, 0.99]** where it read 0.857 [0.60, 0.96]. The point estimate rose; the interval did
  not narrow, and at n=13 a 95% interval is roughly ±0.26.
- **Where:** `src/fi_rag_eval/judging.py:score_refusals_offline`;
  `src/fi_rag_eval/report.py:format_offline_refusals`.
- **What green tests do NOT prove here:** that 0.923 means anything more than 0.857 did. It does
  not. Both are floors and directions, never published numbers, and the *reason* the number moved is
  that the set changed — not that the answerer improved. Anyone quoting the rise as progress is
  quoting a re-labelling. The frozen sample still holds the removed question's answer, real and paid
  for, excluded by name on every table.
- **Disposition:** open — resolves at the N≈85 tranche, which is the only thing that buys a
  narrower interval here.

## 2026-08-28 (slice 5, tracer 3) — two of the fourteen refusal labels are contestable, and they are the two misses

- **What:** The run answered 2 of 14 refusal questions instead of refusing, and on inspection both
  labels are arguable:
  - **`ooc-autonrenkaiden-vastaanotto`** — the answerer said tyres are producer-responsibility waste
    [`lounais-suomi@2024-08-01#2.tuottajavastuunalaisella`] and go to producer-designated collection
    points [`#12`]. Both citations are real; a general **category** rule answers the question. The
    word `rengas` is genuinely absent, so the drift detector passed — **this is the `sakokaivo`
    failure mode the sibling confession warned about, actually occurring.**
  - **`ooj-lisajate-lounais-suomi`** — asked for the *conditions* under which waste may be left
    beside the bin; the answerer said Lounais-Suomi does not permit it, citing `#30` and `#28`. That
    is arguably a correct answer rather than a missed refusal. The risk was noticed at authoring
    time and the phrasing was sharpened; it was not enough.
- **Where:** `corpus/golden/refusals.yaml`; the spec's Tracer slice 3 measured result.
- **What green tests do NOT prove here:** that the other twelve labels are right. Two contestable
  out of fourteen is a **14% label-error rate on a population of 14**, discovered only because those
  two happened to be the failures. Labels that a compliant answerer never challenges are never
  examined at all.
- **The trap this entry exists to name:** re-labelling both would raise refusal recall from 0.857
  toward 1.0. *"The answer improved, so the label must be wrong"* is the reasoning that destroys a
  harness. The measured 0.857 is published as-is; any re-label is a change to the **set**, followed
  by a **re-measurement**, never a correction applied to a result.
- **Disposition:** open, **the Owner's**. Raised in the spec's open questions with a
  recommendation: re-label the tyre question (wrong on its merits), keep the lisäjäte one.

## 2026-08-28 (slice 5, tracer 3) — two refusals emitted citations, and it is not obvious that is wrong

- **What:** `ooj-tieyhteydeton-saari-pirkanmaa` cited `#7` and
  `ooj-toissijainen-jatehuoltopalvelu-lounais-suomi` cited `#1` **while correctly refusing**. The
  spec resolved that *"a refusal emitting any citation is a defect, checked arithmetically"*; the
  check exists, fired, and named both.
- **Where:** `src/fi_rag_eval/metrics.py` (`RefusalMetrics.refusals_with_citations`);
  `src/fi_rag_eval/report.py` (`format_refusals`).
- **What green tests do NOT prove here:** that the rule is right. Both answers use the citation for
  *"here is what the excerpts do say instead"* — Pirkanmaa `7 §` on when kerbside collection is
  possible, Lounais-Suomi `1 §` on the scope clause. That is arguably a **better** refusal than a
  bare one, not a defect.
- **Why it matters now rather than later:** the judge is asked about citations too (tracer 4), so a
  definition that is wrong here will be wrong there, and the frozen agreement sample (tracer 5) will
  be hand-labelled against whichever definition stands.
- **Disposition:** **CLOSED 28 Aug 2026 — the rule was WRONG and is narrowed, not kept.** Decided
  before the judge prompt was written, which is why this entry demanded it. ADR-0010 decision 4
  splits the one check in two: citing an address **outside** the retrieved set stays a defect (the
  half that was always unambiguous — a refusal asserting the context does not answer the question
  while pointing outside that context contradicts itself), and citing a chunk it **did** retrieve
  becomes a counted diagnostic. The deciding argument is this project's own definition of Citation
  (`CONTEXT.md:40`): both observed cases are *correct* citations whose claims happen not to be
  answers, so the rule labelled the more auditable refusal as the worse one and pressured the
  answerer toward output nobody can check.
  **No published number moved.** Recall 0.857 and precision 0.632 are computed from the `refused`
  field alone. Only the reported line changed (`metrics.py` `refusals_citing_context` /
  `refusals_citing_outside`, `report.py` `format_refusals`), plus one new arithmetic check that
  currently fires zero times. A change to a *definition*, logged as a spec delta — never a
  correction applied to a result.

## 2026-08-28 (slice 5, tracer 3) — `json_validate_failed` is now retried, and tracer 2's diagnosis of it was incomplete

- **What:** Groq validates JSON-mode generations server-side and returns HTTP **400**
  `json_validate_failed` with an empty `failed_generation`. Tracer slice 2 met this error and
  attributed it to the token cap covering reasoning and answer together — correct for the case it
  had. Tracer slice 3 met the identical code at an ample cap: it killed a 64-question run at the
  **29th** answer, and the same request then succeeded **twice**, using 2,557 reasoning tokens both
  times. `temperature=0` becomes `1e-8` at Groq, so generation is not deterministic. The cap is one
  cause; non-determinism is another.
- **Where:** `src/fi_rag_eval/answer.py` (`JSON_RETRIES`, `_is_stochastic_json_failure`,
  `complete`); `tests/test_answer.py::TestStochasticJsonFailuresAreRetriedAndCounted`.
- **What green tests do NOT prove here:** that 4 attempts is enough. It was chosen because one
  retry sufficed in the only case observed, which is a sample of one. The count of retries a run
  needed is printed, so the number can be revised from evidence rather than from taste.
- **Why retrying is not skipping:** the question is still answered and still scored, and if the
  retries run out the run still dies rather than reporting 63 of 64. What would be dishonest is
  hiding the frequency, so `json_validation_retries` is carried on the run and printed. "The
  answerer could not emit its envelope on n of 64 questions" is a fact about the model under test.
- **What this cost, and why it is worth writing down:** a **45-minute, ~$0.58 run was destroyed by
  one transient 400** — and, because the first version printed nothing until it finished, the
  failure arrived with no indication of which question caused it. Per-question progress output was
  added in the same change. An expensive long-running command that reports nothing is unusable for
  the thing it exists to do.
- **Disposition:** open (the bound is unvalidated), the immediate defect fixed.

## 2026-08-28 (slice 5, tracer 3) — "out-of-corpus" is a hand-made claim; the enforcer only stops it rotting

- **What:** Each of the 14 refusal questions asserts that its topic is not answerable where it was
  asked. The harness checks an `absent_lexeme` against the real corpus at every run — two-sided for
  the out-of-jurisdiction kind (absent where asked, **present** where the answer lives) — and both
  directions have been seen red. But **a lexeme check cannot establish absence.** A word can be
  missing while the topic is covered under another name.
- **Where:** `corpus/golden/refusals.yaml` (`absent_lexeme`, `absence_source`);
  `src/fi_rag_eval/evaluate.py` (`assert_refusal_absences`); `src/fi_rag_eval/db.py`
  (`chunks_containing`); `tests/test_refusals.py::TestAgainstTheCorpus`.
- **What green tests do NOT prove here:** that any of the 14 topics is genuinely absent. They prove
  the *claim has not changed since it was written*. The claim itself came from reading both clause
  lists by hand, recorded per entry in `absence_source`, and is exactly as good as that reading.
- **The concrete near-miss, kept as the standing example:** `sakokaivo` is absent from both
  documents while `saostussäiliö` is regulated at length. A refusal labelled on that word would
  have been **wrong**, and refusing would have been the defect rather than the metric. It was
  caught by reading, not by any check that exists.
- **Cost accepted:** the alternative is a judge deciding whether a topic is covered, which puts a
  model inside the one part of the answer layer that is currently pure arithmetic — and arithmetic
  is why these numbers can be trusted against a judge when the two disagree.
- **Disposition:** open, accepted. Re-read the clause lists whenever an edition changes; the
  manifest's `expected` block already refuses a document that parses differently, which is the
  event that should trigger it.

## 2026-08-28 (slice 5, tracer 3) — three of D5's six pre-registered asymmetries were wrong

- **What:** `SPEC-slice-5` D5 named six out-of-jurisdiction topics, harvested by reading both
  **clause lists**. Checking the **body text** refuted three: `maanrakentaminen` (Pirkanmaa 17 §
  cross-references its own 19 § for exactly this), `roskaantuminen` (no clause with that title, but
  addressed in nine Pirkanmaa chunks), and `toissijainen jätehuoltopalvelu` (survived, but only as a
  *phrase* — Lounais-Suomi's 1 § and 41 § both use the word `toissijainen` for different things).
  Three replacements were found the same way.
- **Where:** `corpus/golden/refusals.yaml` header; the spec's Tracer slice 3 measured result.
- **What green tests do NOT prove here:** that the six now in the file are the *best* six, or that
  the remaining three are the only surviving asymmetries. The sweep that found the replacements was
  a `ts_stat` diff of the two authorities' lexemes, which is thorough for single words and blind to
  a mechanism described in two documents with no shared vocabulary.
- **Disposition:** open, accepted. The population is six either way (D5's number), and the entries
  that survived are individually stronger than the ones they replaced.

## 2026-08-28 (slice 5, tracer 3) — every refusal question is `authored`, so their wording is ours

- **What:** All 14 carry `phrasing: authored`. Not one is harvested from a resident-facing page.
- **Where:** `corpus/golden/refusals.yaml`;
  `tests/test_refusals.py::test_the_committed_file_declares_every_entry_authored`.
- **What green tests do NOT prove here:** that a real resident would ask any of these. Lexical
  leakage — the measure this project uses to catch questions written *from* the source text — is
  not computed over this population at all, because these questions have no target chunks to leak
  from. So the anti-circularity instrument that guards the answerable set has **no equivalent
  here**, and the questions were written by the same person who knows what the corpus contains.
- **Why it is not fixable cheaply:** no public FAQ asks a question its own regulations cannot
  answer. Harvesting would mean finding residents' questions that the authority *declined*, which
  is not published.
- **Disposition:** open, accepted, and stated so nobody reads refusal recall as evidence about real
  traffic. It is evidence about the behaviour under a constructed adversarial set.

## 2026-08-28 (slice 5, tracer 3) — the answer phase is not in `make eval`, so a green gate still proves nothing about answering

- **What:** `fi-rag-eval answer --all` is a separate command. `make eval` remains offline,
  deterministic and gated at zero tolerance, and knows nothing about refusal metrics.
- **Where:** `src/fi_rag_eval/cli.py` (`_answer_all`); `Makefile` (`eval` unchanged).
- **What green tests do NOT prove here:** anything about answering. `make gate` is green with the
  gateway down, and `make eval` is green without a single model call. The refusal numbers exist
  only in the terminal output and `eval/answers.json` of a run a human chose to make.
- **Why deliberately:** D6 requires one command, but the answer phase has no **floor gate** until
  tracer 6 derives one, and wiring an ungated networked phase into the retrieval gate would make
  the deterministic half of the harness depend on a provider. That is a real regression in the
  half that currently works.
- **Disposition:** open, **closes in tracer 6**, which owns the floors, the baseline extension and
  the published table's structural unavailability when the answer phase is skipped (AC16).

## 2026-08-27 (slice 4) — the harness had never actually been run from a clean clone

- **What:** `make eval` from a fresh `git clone` failed with **HTTP 403** on the Pirkanmaa source.
  `urllib` sends `Python-urllib/<version>` and tampere.fi rejects it, while serving the same public
  PDF to a request that names itself. It worked in my tree only because the PDF was already on disk.
- **Where:** `src/fi_rag_eval/ingest.py` (`fetch`, `USER_AGENT`). Fixed in 12c328d.
- **What green tests do NOT prove here — and this is the point of the entry:** `make gate` was green
  and every one of 190 tests passed while the project's headline reproducibility claim was false.
  No unit test can catch this, because the fixture corpus is whatever is already in `data/raw/`.
  The **only** thing that caught it was the profile's own recipe: *run it from a clean clone into a
  fresh environment, not your dev checkout.* That recipe earned its place this slice.
- **Still open after the fix:** nothing verifies it *stays* fixed. A unit test asserts the header is
  still sent, but the download path itself is exercised only by a human running a clean clone. When
  CI exists, the clean-clone ingest belongs in it.
- **Disposition:** fixed; the gap in the *gate* is open.

## 2026-08-27 (slice 4) — this project has no CODING_STANDARDS.md, so the review's Standards axis has nothing to read

- **What:** `/code-review`'s Standards axis reads `CODING_STANDARDS.md` by exact filename, and the
  devkit's `/harness` is meant to install it at bootstrap. It does not exist here, nor does a
  boundary gate or a drift gate (`scripts/` is absent entirely). The rules this project actually
  runs on live in prose in `CLAUDE.md` and `CONTEXT.md`.
- **Where:** repository root; `Makefile` (`gate` runs lint/format/typecheck/test/build and no
  standards harness).
- **What green tests do NOT prove here:** that the conventions the code follows are *enforced*
  rather than merely habitual. `CONTEXT.md`'s `_Avoid_` table -- "say `ts_rank`, not BM25", "say
  Authority, not Turku's regulations" -- is exactly what a drift gate would make executable, and
  today nothing checks it. `ANTI-PATTERNS.md` calls this "a standard with no enforcer".
- **Disposition:** open, and **not** slice 4's to fix. Pre-existing since bootstrap; recorded here
  because a review axis that silently has no input is worse than one that is absent.

## 2026-08-27 (slice 4) — new evidence for an old entry: the lemma indexes really can disagree with the body

- **What:** Proving the regression gate red (AC10) produced an unplanned demonstration. Corrupting
  one chunk's `body` directly in Postgres dropped **only the six snowball cells**; all six lemma
  cells scored unchanged, because `tsv` is a generated column and the three lemma columns are
  written by the ingest. The corpus was internally inconsistent and `assert_lemma_vectors_populated`
  was perfectly happy, because it checks that they are non-empty and not that they match the text.
- **Where:** `src/fi_rag_eval/db.py` (`SCHEMA`, `set_lemma_vectors`,
  `assert_lemma_vectors_populated`); the existing slice-3 entry on application-written indexes.
- **What green tests do NOT prove here:** exactly what that entry already said — and it is no longer
  hypothetical. A cheap closure exists: store a hash of the body alongside each lemma vector and
  assert it at eval time, the same way `content_sha256` guards the chunk text.
- **Disposition:** open, promoted from "theoretical" to "demonstrated".

## 2026-08-27 (slice 4) — the per-authority breakdown is a diagnostic and is NOT gated

- **What:** `make eval` prints complete-set recall, per-chunk recall, MRR and leakage per authority,
  but `report.compare` gates only the **pooled** row of each cell. One authority could regress while
  the other improved by the same amount and the gate would stay green.
- **Where:** `src/fi_rag_eval/report.py` (`compare`, `format_by_authority`);
  `src/fi_rag_eval/evaluate.py` (`EvaluationRun.by_authority`).
- **What green tests do NOT prove here:** that a per-authority regression is caught. Deliberate per
  D11 — a per-authority row over ~25 questions cannot register an improvement on its own, so gating
  it would add a tripwire that fires on noise. But "deliberate" is not "safe", and the asymmetry is
  worth stating rather than leaving a reader to infer it from the word "diagnostic".
- **Disposition:** open, accepted. Revisit when either authority alone reaches N~50.

## 2026-08-27 (slice 4) — a real clause is missing from the corpus, and both halves of the document agree it is not there

- **What:** Pirkanmaa's body contains `18 a § KOMPOSTOINTI-ILMOITUS`, a clause added by amendment.
  Its own table of contents **does not list it**. `_CLAUSE` matches `^\d+\s*§`, so `18 a §` is
  never a heading candidate, and the TOC cross-check cannot catch the omission because the TOC is
  missing it too. The clause's text is therefore **absorbed into 18 § KOMPOSTOINTI's chunk**: one
  address, 5,328 characters, two clauses. `23 §` and three other places cite "18 a §", so the
  document itself refers to a clause the corpus cannot address.
- **Where:** `src/fi_rag_eval/chunking.py` (`_CLAUSE`, `split_clauses`); `addressing._PATTERN`,
  whose `#(?P<clause>\d+)` cannot express `#18a` either.
- **What green tests do NOT prove here:** the strongest invariant this project has — "every body
  heading is cross-checked against the document's own table of contents" — defends against the body
  carrying *extra* `N §` headings. It is **silent** when a letter-suffixed clause is absent from
  both halves. The two halves "agree" while both are wrong, so 48 clauses / 89 chunks / 41
  definitions is a green assertion over an inventory that is genuinely incomplete.
- **Cost, measured:** a resident asking about the composting notification would be cited "18 §"
  when the rule is in "18 a §". No golden question points at Pirkanmaa 18 § — slice 4's D7
  excluded biojäte and kompostointi from all 29 new questions for unrelated reasons, which happens
  to keep the set clear of the one chunk known to be wrong. That is luck, not design.
- **Disposition:** open. **Not fixed in slice 4 deliberately:** supporting `18 a §` changes the
  clause inventory (49 clauses, 90 chunks), the address grammar, and therefore the golden labels —
  a re-read of the document, not a patch. Fix it before any question targets Pirkanmaa 18 §, and
  before a third authority whose amendments use letter suffixes more heavily.

## 2026-08-27 (slice 4) — `extract.py`'s dot-leader requirement is a Lounais-Suomi assumption wearing an invariant's clothes

- **What:** `extract` locates the table of contents by finding lines containing 4+ consecutive dots
  and hard-fails when there are none. That is not a property of Finnish waste regulations; it is a
  property of the one document the rule was written against.
- **Where:** `src/fi_rag_eval/extract.py` (`_DOT_LEADER`, `extract`).
- **Measured evidence, from running five real candidate authorities through this project's own
  pipeline** (not judged by eye):

  | Candidate | extract | parse_toc | split_clauses | chunk | Gap |
  |---|---|---|---|---|---|
  | Lounais-Suomi | ok | 50 cl, 11 ch | ok | 82 chunks | — |
  | Pirkanmaa | ok | 48 cl, 0 ch | ok 48 | ok 89 | (adopted, slice 4) |
  | HSY / Helsinki | **fails** | — | — | — | TOC has no dot leaders |
  | Oulu | **fails** | — | — | — | TOC aligns page numbers with spaces |
  | Savo-Pielinen / Kuopio | **fails** | — | — | — | same, + 21pp of justifications |

  HSY, Oulu and Savo-Pielinen all have **clean, complete tables of contents**. They simply do not
  use dot leaders. Three of five candidates are blocked by one line of regex.
- **What green tests do NOT prove here:** that any authority other than these two can be ingested.
  The failure is a loud hard error with a good message, so it is documented debt rather than a
  lurking bug — but "the extractor is general" is not a claim this project may make.
- **Disposition:** open, accepted for slice 4. Generalising the entry rule would make a third
  authority nearly free and the reconnaissance is already paid for, but no golden question
  exercises it, and building intake for authorities nobody has chosen is layer-only progress.
  **First candidate to fix when a third authority is wanted.**

## 2026-08-27 (slice 4) — Uudenmaan failed on our bug, not on their document

- **What:** `parse_toc` treats "4+ dots" as the only entry terminator. In the bilingual Uudenmaan
  regulations `pdftotext` compressed 31 §'s dot leader to a **single dot**, so 31 § swallowed 32 §
  and the inventory came out with a hole. 32 § is present in both the TOC and the body; the
  document is fine. Relaxing the terminator yields 46 clauses and then fails again on a wrapped
  heading, so there are **at least two** bugs here and the tail is unmeasured.
- **Where:** `src/fi_rag_eval/chunking.py` (`parse_toc`, `_DOT_LEADER`, `_TOC_TAIL`).
- **What green tests do NOT prove here:** the parser's robustness to `pdftotext`'s own variability.
  The same document extracted by a different poppler version could lose a different leader.
- **Disposition:** open. Honest estimate of the remaining work: **unknown**, not "small" — the
  wrapped-heading failure was reached but not diagnosed.

## 2026-08-27 (slice 4) — one address now spans SIX editions of Pirkanmaa's text

- **What:** Escalation of the open ADR-0004 entry below. `pirkanmaa@2021-07-01#N` is keyed on
  Voimaantulo (`47 §`: *"tulevat voimaan 1.7.2021"*) while the front matter records amendments on
  7.6.2023, 6.3.2024, 9.4.2025 and 22.10.2025 and the authority publishes the text as
  **1.5.2026 alkaen**. Six editions share one address space.
- **Where:** `corpus/manifest.yaml` (pirkanmaa `effective_date`, `edition`); ADR-0006; the existing
  entry "the chunk address cannot distinguish two editions of one document" below.
- **Note on the trigger:** that entry's trigger reads *"before a second **version** of the same
  document is ingested"*. Pirkanmaa is a second **authority**, so the trigger does not technically
  fire. Recording that plainly is more useful than pretending it did.
- **What green tests do NOT prove here:** that two editions could coexist. They cannot — the
  address is the primary key. What ADR-0006 *does* buy is that the misleading date never reaches a
  human: the citation carries `1.5.2026 alkaen`, and `ingest.assert_edition` fails the run if the
  front matter's date list moves, so the label cannot go stale silently.
- **Disposition:** open, **partially mitigated** by ADR-0006 where it is read. The addressing fix
  (re-key to the latest amendment date) is still owed and still costs relabelling every question.

## 2026-08-27 (slice 4) — Sastamala is refused an answer the regulations do give it

- **What:** Pirkanmaa's `1 § SOVELTAMISALA` claims Sastamala only "(Mouhijärven ja Suodenniemen
  osalta)". The manifest lists 16 of the 17 municipalities and records Sastamala under
  `partial_municipalities`, so `resolve_municipality("Sastamala")` raises.
- **Where:** `corpus/manifest.yaml` (pirkanmaa `partial_municipalities`);
  `manifest.resolve_municipality`; ADR-0002's amendment note;
  `tests/test_jurisdiction.py::test_a_partially_covered_municipality_refuses_and_says_why`.
- **What green tests do NOT prove here:** anything about sub-municipal coverage, which is not
  modelled at all. A Mouhijärvi resident is refused an answer that exists.
- **Cost accepted:** an honest refusal for a minority beats a confident wrong answer for the
  majority — the same trade already made for taajama boundaries. **But this will recur:** Finnish
  municipal mergers routinely leave former municipalities under different waste authorities, so
  this is not a Pirkanmaa quirk.
- **Disposition:** open, and the *model* question is **the Owner's**: whether the design needs a
  level between Authority and Municipality. Raised in the slice-4 spec's open questions.

## 2026-08-27 (slice 4) — the authority hard filter is verified at the retrieval layer only: PARTIAL, never CLOSED

- **What:** With two authorities loaded, `evaluate` now asserts that every question's top-k
  contains **zero** foreign-authority chunks, read from the stored row rather than re-parsed from
  the address, for all 50 questions in all 12 cells. It has been **seen red** by deleting the
  jurisdiction WHERE clause, and a second test proves foreign chunks genuinely do enter the top-5
  without it — so the check is not decoration.
- **Where:** `src/fi_rag_eval/evaluate.py` (`assert_one_authority`); `tests/test_jurisdiction.py`.
- **What green tests do NOT prove here — and this is the whole entry:** `CLAUDE.md` specifies the
  filter as *"ask a question answerable only from municipality A's rules with municipality B's
  filter set → it must **refuse**"*. That is **not** what is verified. Refusing requires an
  answering layer, which does not exist. What is verified is **retrieval-layer isolation**: a
  foreign chunk is never a candidate. A future answering layer could still answer from an empty or
  wrong context, and nothing here would catch it.
- **Disposition:** ~~open, **PARTIAL**~~ → **CLOSED 28 Aug 2026 (slice 5, tracer 3).** The
  condition this entry set — *"promote to CLOSED only when a refusal case can be scored"* — is met.
  Six out-of-jurisdiction questions now exist, each asked with the wrong authority's filter, each
  reaching the answerer holding **five plausible same-topic chunks from the authority it was asked
  about**; `CLAUDE.md`'s specified behaviour was measured rather than assumed and **5 of 6 refused**,
  with the answers printed. Example, verbatim: *"Annetuissa pykäläotteissa ei ole tietoa keittiön
  jätemyllyn asentamisesta tai jätteiden johtamisesta viemäriin, joten en voi vastata
  kysymykseen."*
- **What is CLOSED and what is not.** Closed: refusal is now a scored behaviour with a number, not
  an untested design claim, and it is the number this project publishes rather than a hope.
  **Not** closed and not claimed: 5/6 is not 6/6, the interval is [0.44, 0.97] at n=6, and the one
  miss (`ooj-lisajate-lounais-suomi`) has a **contestable label** — see the next entry. Read this as
  "the mechanism is verified and measured at 0.833 with a wide interval", never as "the filter
  cannot fail".

## 2026-08-27 (slice 4) — the extractor damages text in three measured ways, and none was fixed

- **What:** Three artefacts, all found by ingesting a second document and all left alone because
  D5 fixed only the definitions carve-out:
  1. **A genuine compound hyphen is destroyed at a line break.** `dehyphenate`'s only guard is a
     coordinating-conjunction list, so `ruoka-` + `aineksia` joins to `ruokaaineksia` — a junk
     lexeme inside `2 §`'s elintarvikejäte definition.
  2. **A table header is fused into a word.** The other of Pirkanmaa's two joins is
     `Lasi-` + `lukumäärä` → `Lasilukumäärä`, inside `15 §`'s separate-collection duty table, which
     golden questions do target.
  3. **37 bare page-number lines survive in Pirkanmaa's body and 0 in Lounais-Suomi's.** Page
     numbers become indexed tokens for one authority and not the other — e.g. `paperilla`'s
     definition chunk ends with a stray "10".
- **Where:** `src/fi_rag_eval/extract.py` (`dehyphenate`, `_COORDINATING`, `extract`).
- **What green tests do NOT prove here:** that the two authorities' text is normalised *comparably*.
  Artefact 3 is an asymmetry **between** authorities, which is exactly the kind of thing that could
  surface as an unexplained per-authority gap in the metric table and be attributed to retrieval.
- **Disposition:** open, deliberately not fixed. A change to extraction normalisation moves the
  numbers for both authorities and must be measured as its own change, not slipped in beside a
  golden-set slice. Stripping bare numeric lines is a no-op for Lounais-Suomi (0 of them), so it is
  a cheap and well-isolated first fix. **Flagged to the Owner.**

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
- **Update 27 Aug 2026 (slice 4):** the argument has changed from a preference into evidence. At
  N=50 `lemma-reasm/0` beats the published `snowball/0` on the **paired** test — 9 discordant
  questions, 8 of them in its favour, exact McNemar **p=0.039**. At N=21 no comparison in the grid
  could reach p<0.05 at any effect size, so "0.857 vs 0.762" was never a claim the instrument could
  support. It now is. Note the cost D6 attaches to moving: the N target for detecting a
  half-of-misses fix rises from ~51 to ~84 if the headline sits on a lemma cell.
- **Disposition:** **CLOSED 27 Aug 2026 — the Owner moved the published cell to `lemma-reasm/0`.**
  Recorded in ADR-0007 with four rejected alternatives, and re-baselined in its own commit. The
  entry closes because the README now publishes the best cell this project can defend, and the
  defence is a paired p-value rather than a preference.
  **Two costs replaced it, both accepted before the change rather than discovered after:**
  (1) the published leakage figure rises 0.332 -> 0.550, which is the analyser seeing overlap the
  stemmer split apart and **not** the golden set getting easier — leakage stays gated per cell
  against its own value, so `lemma-reasm/0` is still defended from rising above 0.550, and nobody
  may compare the new published leakage against the old; (2) the instrument spends power — this
  cell fails 9 of 50 rather than 16, so the N target for detecting a half-of-misses fix rises from
  ~51 to ~84, which makes the held-out-slice trigger at N~85 do double duty.

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
- **Disposition:** **LARGELY CLOSED 27 Aug 2026 (slice 4).** N=21 -> **N=50** (29
  Lounais-Suomi, 21 Pirkanmaa), 53 required chunks, and the harness now prints the discordant
  count and exact McNemar p for every pair of cells so its own power is stated rather than
  assumed. The threshold D6 was chosen to clear is met: at least one cell beats the published cell
  at p<0.05, which was impossible at N=21. Still open: **no held-out slice** (D8 defers it to
  N~85, because holding out 10 of 50 leaves a tuning set that cannot reach d=6 and a held-out set
  that never can), and refusals remain unsupported for the same structural reason.
  Superseded detail — open — the next tranche of questions is better written against two
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

## 2026-08-28 — no automated test makes a live model call

- **What:** `tests/test_answer.py` covers the envelope contract, the token ceiling, the per-model
  reasoning shim and the context format — all pure. The only gateway test lists models, which
  spends nothing. **Nothing in `make gate` proves an answer can actually be generated.**
- **Where:** `tests/test_answer.py:1-12` (the docstring states this deliberately)
- **Why:** `make gate` runs before every commit. A test that spends money on every commit is a
  test that gets deleted the first time it is inconvenient, and this project's cost ceiling exists
  precisely to stop unattended spend.
- **What green tests do NOT prove here:** that the answering path works at all. 226 green tests are
  compatible with a gateway that 401s on the first real call. The live exercise is
  `fi-rag-eval answer <id>`, run by a human, and it is the only thing that proves this layer.
- **Disposition:** open — the answer phase's own `make eval` integration (tracer 6) will exercise
  it on every eval run, which is where a networked assertion belongs.

## 2026-08-28 — a spent budget is detected by string-matching the gateway's message

- **What:** An exhausted key budget and an ordinary rate limit both arrive as HTTP 429. The
  boundary distinguishes them with `"budget has been exceeded" in str(exc).lower()`.
- **Where:** `src/fi_rag_eval/answer.py`, the `RateLimitError` branch of `complete()`
- **Why:** The distinction is load-bearing — a rate limit is worth retrying and an exhausted budget
  never is — but LiteLLM surfaces no structured code that separates them at this boundary.
- **What green tests do NOT prove here:** nothing tests this branch, because reaching it means
  actually exhausting a $25 budget. If LiteLLM rewords the message, the harness will silently
  retry an exhausted budget three times and then report it as a rate limit.
- **Disposition:** open. Cheap partial fix available: assert the message shape against a
  deliberately-tiny budget on a throwaway key, which is how the behaviour was measured in the
  first place.
- **UPDATED 28 Aug 2026 (tracer 3): this pattern now has a second instance.**
  `_is_stochastic_json_failure` matches `"json_validate_failed" in str(exc)` for the same reason —
  every provider 400 arrives here as one `BadRequestError`, and the harness has to tell a
  *retryable* one (the model emitted invalid JSON, which is stochastic) from a *permanent* one (the
  request is wrong). This branch, unlike the budget one, **is** covered by tests, but they assert
  against a message string this project does not control. Two string matches on provider prose is
  the point at which this stops being an oddity and becomes a pattern worth a structured fix.

## 2026-08-28 — D8's 600K token ceiling is known to be wrong and was left alone

- **What:** `answer.TokenBudget` ships with `TOKEN_CEILING = 600_000`, the figure `SPEC-slice-5` D8
  specified. Tracer slice 2 measured one answer at ~10,900 tokens with reasoning on, which puts a
  64-question answer phase at **~700K tokens — a legitimate run would trip the ceiling**, the one
  thing a ceiling must never do.
- **Where:** `src/fi_rag_eval/answer.py`, `TOKEN_CEILING` (its docstring carries the measurement)
- **Why:** Raising it now would be fitting the spec's number to a single measurement. The right
  denominator is a full 64-question run, which does not exist until tracer 6, and prediction 7
  decides whether reasoning is on at all — which changes the answer by a factor of two.
- **CLOSED 28 Aug 2026 (tracer 3), earlier than planned and not by fitting a new constant.** The
  first full 64-question run arrived here rather than in tracer 6, so the re-derivation came with
  it. The fix is a **formula, not a number**: `ceiling_for(calls) = max(600_000, 2 x calls x 10_900)`,
  where 600K is D8's figure kept as a floor, 10,900 is the measured tokens of one reasoning-on
  answer, and 2 is the headroom. Every input is a figure this project measured and can re-measure,
  and the ceiling now scales with the run instead of needing revision each time the question set
  grows. Seen red on the full-run path: `--token-ceiling 1` stopped the run after one call
  (10,884 tokens, $0.0210) with a non-zero exit.
- **What green tests do NOT prove here:** the tests prove the ceiling *fires*, not that it is set
  to a sensible number. A gate at the wrong threshold is green until the day it stops the work.
- **Disposition:** open — closes in tracer 6, re-derived from a real run.

## 2026-08-28 — the gateway's budget was decorative for the length of one commit

- **What:** The gateway's first configuration put `max_budget: 25.0` in `litellm.config.yaml` and
  authenticated with the proxy master key. Measured: **$0.074910 of spend against a $0.001 budget
  was served HTTP 200.** LiteLLM does not apply budgets to its master key. Corrected in the same
  slice — the harness now spends through a derived virtual key (`gateway.py`), which was watched
  refusing at HTTP 429.
- **Where:** `litellm.config.yaml` (the comment now records what was measured),
  `src/fi_rag_eval/gateway.py`
- **Why it is recorded although it is fixed:** it is the project's own "standard with no enforcer"
  anti-pattern, and it survived being written, reviewed and reasoned about — right up until
  someone tried to watch it fail. The lesson is the entry, not the bug.
- **Disposition:** **CLOSED 28 Aug 2026 (slice 5, tracer 2)**, by ADR-0009 and a red proof.

## 2026-08-28 (slice 5, tracer 4) — the judge is NON-DETERMINISTIC, and nobody had priced that in

- **What:** three judge runs over the *identical* frozen answer file returned different verdicts.
  Aggregate branch coverage was stable at 0.472 (59/125) in two of them, but `supported` moved by
  one branch and the non-contiguous-quote count moved from **9 answers to 2**. On one question
  (`biojatteen-kerays-jarjestaminen`) the same judge said `stated 2/3` and then `stated 3/3`
  twenty minutes later.
- **Where:** `src/fi_rag_eval/answer.py` `_complete_once` sets `temperature=0`, which Groq rewrites
  to `1e-8` (ADR-0008). The judge goes through the same boundary as the answerer, so it inherits
  the same non-determinism — which was recorded for the *answerer* and never reasoned about for the
  *judge*.
- **What green tests do NOT prove here:** nothing in `make gate` makes a live model call, so no test
  can see this. The unit tests pin the arithmetic given a verdict; they cannot pin the verdict.
- **Why it matters:** judge–human agreement (tracer slice 5, D11's publishability gate at ≥0.85)
  is measured against *one* judge run. If the judge disagrees with **itself**, that
  self-consistency is a **ceiling** on any agreement it can reach — two runs that differ cannot
  both match a human. `CONTEXT.md` now carries **Judge self-consistency** as a term for it.
- **MEASURED, so the ceiling is a number rather than a worry — and the first figure published for
  it was computed the way this project has since documented as wrong.** Tracer slice 4 reported
  **0.975 over D3's 199 units**. That pooled in the **31 units under refused answers**, where both
  runs are structurally forced to the same verdict — the exact inflation ADR-0011 then excluded from
  judge–human agreement. Excluding them, as `fi-rag-eval agreement --against` now does:
  **0.964 [0.93, 1.00] over 274 field-verdicts in 43 questions**, cluster-robust; **0.970** counting
  a branch as one unit. Per field: `asserted` 62/62 = 1.000, `stated` and `supported` 101/106 =
  0.953 each. The 1.000 is consistent *for free* — 61 of 62 were unanimous negatives.
  **The ceiling is still well clear of the 0.85 floor**, so this changes the number and not the
  plan. **0.964 is the figure to quote**; 0.975 is superseded and should not be cited from tracer
  slice 4's section, which now says so.
- **Not fixed, and the options are not equal:** re-running the judge N times and taking a majority
  would raise consistency and multiply cost by N; caching a verdict per unit would make the harness
  deterministic and freeze in whatever the first run happened to say. Both are real designs and
  neither is a tracer-4 decision.
- **A definitional gap this measurement exposed, which tracer slice 5 must close:** D3 says
  agreement is published over 199 units, but a **branch** unit carries *two* judgements (`stated`
  and `supported`) while a forbidden item carries one. So "199 units" does not by itself say what
  agreement on a branch means. Scored strictly — a branch agrees only when both fields do — the
  figure is 0.975 over 199. Scored per field it is 0.969 over 324, and that denominator is
  misleading anyway, because `parse_verdicts` forces `supported` false whenever `stated` is false,
  so the two fields are coupled by construction and every one of the five observed flips moved
  both. **Settled in the code rather than in prose: `fi-rag-eval agreement` reports the field-level
  figure**, which is the more conservative of the two, and prints the strict equivalent beside it.
- **Disposition:** open. The number exists and has a command behind it
  (`agreement --against`). What remains is that tracer slice 5 must report its agreement figure
  against **0.964** rather than against 1.0, and must not re-derive the unit definition.

## 2026-08-28 (slice 5, tracer 4) — groundedness saturates at 1.000, so the published metric carries no information

- **What:** measured over all 50 answers, groundedness is **1.000 (59/59)** in one run and **0.983
  (58/59)** in another. Split by whether retrieval was complete, it is **1.000 in both strata**.
  Branch coverage over the same runs is **0.472**.
- **Where:** `CONTEXT.md:47` and `SPEC-slice-5` D11, which make groundedness *the published
  answer-layer number* with branch coverage as its mandatory companion.
- **Why it happens:** the denominator is branches **stated**, and `qwen/qwen3.6-27b` does not state
  a branch it cannot cite. It drops branches instead. So the metric measures a failure mode this
  answerer does not have, and every bit of the signal is in the companion.
- **What green tests do NOT prove here:** the arithmetic is right and tested. A metric can be
  correctly computed and still be uninformative, and no test detects that.
- **Consequence for D11, stated plainly:** a README row reading *"groundedness 1.000, branch
  coverage 0.472"* invites the first number to be quoted and the second ignored — which is the
  exact failure the recall/leakage rule exists to prevent, one layer up. The pairing rule is
  necessary and, on this evidence, not sufficient.
- **Disposition:** open, and it is the **Owner's**: whether the published answer-layer headline
  should move from groundedness to branch coverage. D11 already considered and rejected branch
  coverage as the headline, on the ground that it is judge-dependent — but so is groundedness, and
  that argument does not separate them. Raised as an open question in the spec rather than decided.

## 2026-08-28 (slice 5, tracer 4) — judge self-consistency has no command, only a script

- **What:** the number in the measured-result section was produced by
  `$CLAUDE_JOB_DIR/tmp/consistency.py`, a throwaway script over two `judge --out` files. The
  *arithmetic* is shipped and tested (`metrics.unit_agreement`, `metrics.cluster_robust_interval`),
  but nothing in the CLI computes it.
- **Where:** `src/fi_rag_eval/metrics.py` (`unit_agreement`); no caller in `src/fi_rag_eval/cli.py`.
- **Why it was left:** tracer slice 5 computes judge–human agreement with the same function and
  will need a surface for it. Building that surface now, before there are human labels to shape it,
  risks designing it twice.
- **Reproduction, so the number is not stranded:** two runs of
  `fi-rag-eval judge <run.json> --out <file>` and `unit_agreement` over the two files, keyed on
  `(question_id, unit, index, field)`.
- **Disposition:** open. Tracer slice 5 gives it a command, or explains why it should not have one.

## 2026-08-28 (slice 5, tracer 4) — the judged metrics are computed over a gitignored, dirty-tree artifact

- **What:** every judged number in this tracer describes
  `eval/runs/answers-tracer3-4b75dfd.json`, which is **gitignored** and whose own `commit` field
  reads **`4b75dfd-dirty`**. So the answer layer's numbers are not reproducible from a clean clone,
  and their provenance is a tree rather than a commit.
- **Where:** `.gitignore` (`eval/runs/`); the run file's `commit` field; `judging.RecordedRun`.
- **Why it was accepted:** re-answering costs $0.76 and ~50 minutes for input that already exists,
  and ADR-0010's first argument is that a judge prompt cannot be developed against an input that
  moves. The answers are also the ones already published in tracer slice 3's result, so the two
  halves of the answer layer describe the same 64 answers.
- **How it is not hidden:** `judge` prints a `!!` line naming the dirty provenance on every table,
  and a drift check re-retrieves all 50 contexts and refuses the run if the corpus has moved.
- **Disposition:** open. Tracer slice 5's frozen sample is the deliberate committed copy that
  partly repays this, and it should be re-frozen from a **clean commit** rather than inheriting
  `-dirty`.

## 2026-08-28 (slice 5, tracer 5, Foreman half) — one labeller, so inter-annotator agreement is unmeasurable

- **What:** judge–human agreement will be agreement with **one** human. Nothing in the protocol can
  say whether a second person, labelling the same 168 units blind, would produce the same labels.
- **Where:** `docs/adr/0011-*.md` (Consequences); `src/fi_rag_eval/labelling.py`;
  `eval/frozen/labels-owner.yaml` once it exists — the filename says `owner` for this reason.
- **What green tests do NOT prove here:** the tests prove the protocol is blind, resumable and
  arithmetically sound. None of that speaks to whether the labels are *right*. A confidently wrong
  single labeller produces a clean 0.95 agreement and a judge validated against a misconception.
- **Why it is accepted rather than fixed:** a second labeller is a second person, which this project
  does not have. The mitigation that is available and taken: the label file carries a `note` field
  per unit, and contestable units are expected to use it — two of the fourteen refusal labels turned
  out arguable, so the base rate for "hand label needing a second look" in this project is ~14%.
- **Disposition:** open, accepted. Revisit only if a second reader ever exists.

## 2026-08-28 (slice 5, tracer 5, Foreman half) — the labelling burden is 168 units and nobody has done any of it

- **What:** `fi-rag-eval label` exists, is blind, resumable and tested, and **has never been run to
  completion**. `eval/frozen/labels-owner.yaml` does not exist. Judge–human agreement, D11's
  publishability gate, therefore does not exist, and no judged metric is publishable.
- **Where:** `src/fi_rag_eval/labelling.py`; `src/fi_rag_eval/cli.py` (`_label`, `_agreement`).
- **What green tests do NOT prove here:** that a human can actually get through 168 units with this
  surface. It was verified by a **scripted** session of a handful of units, not by a person doing the
  real thing for two hours. The estimate of 20–40 seconds a unit is an estimate and is labelled as
  one; it has never been measured.
- **The specific risk:** if the surface turns out to be unusable at unit 40, the protocol changes and
  the first 40 labels may not survive the change. Cheapest mitigation available and not taken:
  labelling ten units for real before writing this entry.
- **Disposition:** open. The Owner's next action, and the gate on the rest of slice 5.

## 2026-08-28 (slice 5, tracer 5, Foreman half) — `--partial` can print an agreement figure that is not a result

- **What:** `fi-rag-eval agreement --partial` computes over whatever is labelled so far. The labelled
  subset is the *first* n units in golden-set order, which is not a random sample of the 168.
- **Where:** `src/fi_rag_eval/cli.py` (`_agreement`); `src/fi_rag_eval/report.py`
  (`format_agreement`, the `PARTIAL` block).
- **What green tests do NOT prove here:** that the warning is enough. The table prints
  `!! PARTIAL` and says no number may be quoted, and the flag's help says the same — but a number
  printed with a caveat is a number that gets quoted without it, which is the exact failure the
  recall/leakage rule exists to prevent.
- **Why it exists at all:** a two-hour labelling job with no way to check progress is a job that gets
  abandoned. The alternative considered was printing counts only and no rate; rejected because the
  rate is the thing a person wants at the halfway point.
- **Disposition:** open. If it is ever quoted, delete the flag.

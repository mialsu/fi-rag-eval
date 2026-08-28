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
- **Disposition:** open, **PARTIAL**. Promote to CLOSED only when a refusal case can be scored,
  which is the answering slice. Do not let a green filter assertion be read as a verified refusal.

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

## 2026-08-28 — D8's 600K token ceiling is known to be wrong and was left alone

- **What:** `answer.TokenBudget` ships with `TOKEN_CEILING = 600_000`, the figure `SPEC-slice-5` D8
  specified. Tracer slice 2 measured one answer at ~10,900 tokens with reasoning on, which puts a
  64-question answer phase at **~700K tokens — a legitimate run would trip the ceiling**, the one
  thing a ceiling must never do.
- **Where:** `src/fi_rag_eval/answer.py`, `TOKEN_CEILING` (its docstring carries the measurement)
- **Why:** Raising it now would be fitting the spec's number to a single measurement. The right
  denominator is a full 64-question run, which does not exist until tracer 6, and prediction 7
  decides whether reasoning is on at all — which changes the answer by a factor of two.
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

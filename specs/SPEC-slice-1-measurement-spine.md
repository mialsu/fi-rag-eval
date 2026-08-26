# SPEC — Slice 1: the measurement spine

Written after `/grill-with-docs` on 26 Aug 2026, before any code. Weight: **Standard**.
Vocabulary is defined in `CONTEXT.md`; load-bearing decisions are in ADR-0002, ADR-0003, ADR-0004.

## Problem

The deliverable is a measurement you can trust, and none exists. `make eval` is a stub that exits
non-zero. This slice cuts the thinnest possible path all the way through the *measurement* — source
document to a printed metric table — before any model is involved, so that every later retrieval
decision is justified by a number rather than by faith.

It answers one question: **how good is lexical-only retrieval on Finnish waste regulations?**
`DESIGN.md` asks for exactly that comparison ("Test BM25 alone early; add lemmatisation if recall is
poor") and it has never been run.

One correction to that framing, which this spec adopts throughout: **Postgres `ts_rank` is not
BM25.** It scores term frequency and document length but carries no inverse document frequency, so
it cannot down-weight a term that appears everywhere in the corpus. Slice 1 therefore measures
`ts_rank`, a weaker baseline than BM25, and every number it produces is labelled as such. True BM25
in Postgres needs an extension, which slice 1 deliberately does not add.

## Solution shape

```
manifest.yaml  (1 authority: lounais-suomi)
      │
      ▼
  fetch ──► pdftotext -layout ──► chunk ──► Postgres (FTS, 'finnish')
                                    │
golden.yaml (6–8 entries) ──► retrieve ──► score ──► make eval → metric table, exit 0
```

- **Manifest** — one authority, one document version. The `effective_date` is read out of the
  document at ingest, not assumed (see ADR-0004's closing note).
- **Extraction** — `pdftotext -layout`, verified during shaping to preserve the 26 § interval table
  and its footnote.
- **Chunking** — § whole; `2 § Määritelmät` split per defined term; cross-reference lists and tables
  atomic. Per ADR-0004.
- **Addressing** — `lounais-suomi@<effective_date>#<clause>[.<sub>]`, content hash stored alongside.
  An unresolvable address is a hard error.
- **Retrieval** — Postgres full-text search with the `finnish` configuration, ranked by `ts_rank`.
  **No pgvector, no embeddings, no reranker, no BM25 extension.**
- **Golden set** — 6–8 entries, `required_chunks` only. Branch checklists arrive with the answering
  slice; the entry file format is ADR-0003's from the start so nothing is relabelled later.
- **Surface** — `make eval` prints the metric table, asserts N, and exits 0 green / non-zero on
  regression or on any unresolvable label.

- **Miss diagnostic** — for every required chunk that was *not* retrieved, record whether it shares
  any stemmed token with the query. Pure arithmetic, no model, no extra cost. This separates the two
  confounded causes of a low score: a **morphology** failure (zero overlap — the chunk was
  unreachable) from a **ranking** failure (overlap existed but the chunk ranked below k, which is
  where IDF would have helped). Without it, a disappointing number cannot tell us what slice 3
  should be.

**Metrics:** complete-set recall@5 (headline) · per-chunk recall@5, MRR (diagnostics) · miss
breakdown, zero-overlap vs ranked-out · N.

## Pre-registered prediction

Written **before** the first run, deliberately, so the result confirms or refutes a stated
hypothesis instead of being rationalised after the fact. Revised 26 Aug 2026 after further
measurement corrected part of the original grounds — see the note at the end of this section.

### The number

> **Complete-set recall@5 will land between 0.25 and 0.50**, using the `finnish` text-search
> configuration and `ts_rank` (**not** BM25 — see below).

Two forces pull in opposite directions, which is why the range is wide:

| Direction | Cause |
|---|---|
| **Down** | No compound splitting — 4 of 4 term-pair tests failed |
| **Down** | No IDF in `ts_rank`, against a corpus where `jätteiden` (76×), `kiinteistön` (71×) and `kunnan` (54×) act as near-stopwords |
| **Up** | The corpus is only ~89 chunks (~60 clauses + 29 definition entries), so top-5 covers 5.6% of it — far easier than any published benchmark |

### The mechanism — the falsifiable half

A wide range is hard to be wrong about. These are the real claims:

1. **Most misses will be zero-overlap, not ranked-out** — the required chunk shares no stemmed token
   with the query at all, rather than being retrieved and ranked below 5.
2. **`kunnan` stems to `kun`**, colliding with one of the commonest Finnish conjunctions, so expect
   precision noise on any question mentioning the municipality.
3. **The 29 short definition chunks will be over-retrieved**, because without IDF short chunks
   dense in common terms score well.

Claim 1 is what decides slice 3, and the diagnostic below is what tests it:

- mostly zero-overlap → slice 3 is **lemmatisation** (`dict_voikko`, which splits compounds)
- mostly ranked-out → slice 3 is **a BM25 extension**, because the missing signal is IDF

**If any of this is wrong, the reason must be understood before touching retrieval.** A pleasant
surprise is a finding, not a licence to move on.

### Measured grounds

Against a live Postgres 17, `finnish` configuration:

| Test | Result | Reading |
|---|---|---|
| `biojäte` finds `biojäteastia` | false | compound not split (`biojät` vs `biojäteast`) |
| `erilliskeräys` finds `erilliskeräysvelvoite` | false | compound not split |
| `tyhjennys` finds `tyhjennysväli` | false | compound not split |
| `jäteastia` finds `jäteastioiden` | false | stem-boundary failure (`jäteast` vs `jäteastio`) |
| `taajama` finds `taajamassa` | true | inessive handled |
| `biojäte` finds `biojätteet` / `biojätteen` / `biojätettä` | **true** | all stem to `biojät` |
| `jätteiden` → `jät`, `kunnan` → `kun` | — | over-short stems, collision risk |

**Correction to the original grounds.** The first version of this spec claimed Finnish snowball
"fails even ordinary inflection on this vocabulary". That was overstated. Inflection mostly works —
the whole `biojäte` family shares one stem. The `jäteastia` case is a specific stem-boundary
failure, not the general rule. Compound splitting is the genuine, reproducible gap, and the missing
IDF is the second one. Recorded rather than quietly edited, because a pre-registered prediction
whose grounds change silently is worth nothing.

## Tracer slices

1. **Slice 1 — the measurement spine** (this spec). Demoable alone: `make eval` prints a real
   metric table from a clean clone, at €0.
2. **Slice 2 — second authority and the filter's proof** (blocked by 1). Adds Savo-Pielinen, then
   the adversarial case: a Kuopio-only question asked with `authority=lounais-suomi` must refuse.
3. **Slice 3 — retrieval improvement** (blocked by 1). Scope is *decided by slice 1's number*:
   lemmatisation (voikko/omorfi), trigram matching, or the vector layer. Not chosen in advance.
4. **Slice 4 — answering** (blocked by 2 and 3). Conditional answers with per-branch citations,
   refusal, branch coverage, over-claim rate, and a judge whose agreement with hand labels is
   reported.

## Non-goals

Slice 1 deliberately does **not** include: embeddings · pgvector · a reranker · any LLM call · a
judge · answer generation · citations · the refusal path · a second authority · momentti-level
applicability · Docker or Cloud Run · any API key or paid call.

## Open questions

- **Cost ceiling (deferred, with a trigger).** No number is set. Slice 1 spends €0 and needs no key,
  so it is not blocked. The trigger to decide is the first slice needing an embedding or judge model
  — set it against a measured per-run token count, not a guess. Until then `CLAUDE.md` binds every
  session to ask before any paid run.
- **What counts as a true refusal case.** A missing determining variable is *not* a refusal
  (ADR-0003). Whether a question whose subject matter is genuinely absent is the only real refusal
  case is unresolved, and blocks nothing until slice 4.
- **Which 6–8 golden questions.** Slice 1 can only cover single-authority answerable questions,
  keyword traps, and genuine unanswerables. The cross-authority divergence and contamination
  categories from `DESIGN.md:82-85` require slice 2.

## Decisions

- Authority, not municipality, is the jurisdiction key → **ADR-0002**
- Conditional answers, branch-labelled golden entries, complete-set recall headline → **ADR-0003**
- Clause chunking with two carve-outs, and stable chunk addressing → **ADR-0004**
- Domain profile: `cli-tools` + deploy graft + eval-integrity layer → **ADR-0001**

---

## Measured result — 26 Aug 2026

Run on commit `81c496c` + this slice, `k=5`, N=8 questions / 10 required chunks, at €0.
Reproduce with `make eval`.

| Metric | Value | N |
|---|---|---|
| **complete-set recall@5** (headline) | **0.875** | 8 questions |
| per-chunk recall@5 (diagnostic) | 0.900 | 10 chunks |
| MRR (diagnostic) | 0.812 | 8 questions |
| misses: zero-overlap / ranked-out | 0 / 1 | 1 of 10 chunks |

### The number: prediction REFUTED

Predicted 0.25–0.50. Measured **0.875** — not a near miss, a different regime. The
prediction was not conservative, it was wrong, and the reason matters more than the number.

**The dominant cause is the golden set, not the retriever.** Measured, not guessed: on
average **60% of each question's stemmed content words appear verbatim in its target
chunk** (per question: 33%, 40%, 44%, 50%, 67%, 67%, 78%, 80%). The questions were written
with the source PDF open, so they inherited its vocabulary — "biojäteastia",
"tyhjennysväli", "erilliskeräysvelvoite", "kesäaikana" are the document's own words. A
resident asks *"milloin biojätteet viedään?"*. This is `CLAUDE.md`'s golden-set leakage
watch-item, arriving on day one and self-inflicted.

So 0.875 is a real number honestly computed, and it measures **an instrument that is
easier than the task**. It is not evidence that lexical-only retrieval is good enough.

### A harness bug the first run hid

The first execution of this harness reported **0.750**. That number was void: `or_tsquery`
builds a tsquery literal over lexemes the stemmer has already produced, and it was being
passed through `to_tsquery`, which stems them **again** — `biojät` → `biojä`, `tarkoit` →
`tarkoi`. Queries silently stopped matching chunks containing the term verbatim, and the
miss diagnostic mislabelled a reachable chunk as `zero-overlap`.

Worth stating plainly: the bug made the harness report a *lower* number, so nothing looked
wrong. It was caught only because a `zero-overlap` verdict on a chunk that shares a word
with the question is arithmetically impossible, and the diagnostic made that visible. Fixed
by casting instead of parsing; `tests/test_retrieval.py` pins it.

### The mechanism claims

| Claim | Verdict | Evidence |
|---|---|---|
| 1. Most misses will be zero-overlap | **undetermined** | 1 miss total, and it is ranked-out. N gives the claim no power |
| 2. `kunnan` stems to `kun`, causing precision noise | **confirmed** | `kunnan` → `kun`; bare `kun` is a stopword and is dropped entirely. Bonus finding: `Turku` → `turku` but `Turun` → `turu`, so the municipality name does not stem consistently across its own inflections — this lands in slice 2, where municipality enters the query |
| 3. The short definition chunks will be over-retrieved | **refuted, mechanism inverted** | Definition chunks are 39% of the corpus and **0% of every top-5** |

Claim 3 was wrong because the premise was wrong. `ts_rank` at its **default normalisation
(0) does not divide by document length**, so a long clause accumulates more matched-term
weight than a short one. Definition chunks average 203 characters against 1,202 for whole
clauses; on the one failing question the correlation between chunk length and `ts_rank` is
**+0.673**, and all eight top-ranked chunks are longer than the 40-word definition that was
the answer. Short chunks are systematically *under*-retrieved, not over-retrieved.

### What this changes for slice 3

The decision rule in the prediction ("mostly zero-overlap → lemmatisation; mostly
ranked-out → BM25") cannot fire: one miss decides nothing. The measurement instead surfaced
a candidate that was not on the list, and a cheaper one:

1. **`ts_rank` normalisation.** The only failure this run produced is a short chunk losing
   to long ones on unnormalised term weight. `ts_rank(tsv, q, 32)` — or `2`, dividing by
   length — is a one-argument change addressing the one observed failure. Measure it before
   anything larger.
2. **Fix the golden set first, though.** With 60% leakage the harness cannot detect an
   improvement or a regression in the thing it is meant to measure. Rewriting the questions
   in a resident's vocabulary is now the highest-value work in the project, and it comes
   before any retrieval change — measurement wins ties (`CLAUDE.md`).

Lemmatisation (`dict_voikko`) and a BM25 extension stay on the list, unranked, because this
run produced no evidence for either. Compound splitting remains a demonstrated corpus-level
gap (4 of 4 term-pair tests) that simply did not bind on these eight questions.

### What the number does not say

- Nothing about the authority hard filter: one authority is ingested, so there is no second
  jurisdiction to leak from (`REVIEW-DEBT.md`).
- Nothing about answer quality, groundedness, citations or refusal — no model ran.
- Little about complete-set vs per-chunk recall: only 2 of 8 questions span more than one
  chunk, so the two metrics nearly coincide here. They diverge on the ~50-question set.
- Nothing generalisable: 8 questions puts the 95% interval on 0.875 at roughly ±0.23. The
  headline is a single-digit-precision figure and must be read as one.

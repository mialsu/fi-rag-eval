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

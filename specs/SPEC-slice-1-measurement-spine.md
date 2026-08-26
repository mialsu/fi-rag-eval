# SPEC — Slice 1: the measurement spine

Written after `/grill-with-docs` on 26 Aug 2026, before any code. Weight: **Standard**.
Vocabulary is defined in `CONTEXT.md`; load-bearing decisions are in ADR-0002, ADR-0003, ADR-0004.

## Problem

The deliverable is a measurement you can trust, and none exists. `make eval` is a stub that exits
non-zero. This slice cuts the thinnest possible path all the way through the *measurement* — source
document to a printed metric table — before any model is involved, so that every later retrieval
decision is justified by a number rather than by faith.

It answers one question: **how good is lexical-only retrieval on Finnish waste regulations?**
`DESIGN.md:118` asks for exactly that comparison ("Test BM25 alone early; add lemmatisation if
recall is poor") and it has never been run.

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
- **Retrieval** — Postgres full-text search with the `finnish` configuration. **No pgvector, no
  embeddings, no reranker.**
- **Golden set** — 6–8 entries, `required_chunks` only. Branch checklists arrive with the answering
  slice; the entry file format is ADR-0003's from the start so nothing is relabelled later.
- **Surface** — `make eval` prints the metric table, asserts N, and exits 0 green / non-zero on
  regression or on any unresolvable label.

**Metrics:** complete-set recall@5 (headline) · per-chunk recall@5, MRR (diagnostics) · N.

## Pre-registered prediction

Written **before** the first run, deliberately, so the result confirms or refutes a stated
hypothesis instead of being rationalised after the fact.

> **Complete-set recall@5 will be under 0.3** using the `finnish` text-search configuration.

Grounds, measured during shaping against a live Postgres 17:

| test | result |
|---|---|
| `biojäte` finds `biojäteastia` | false |
| `erilliskeräys` finds `erilliskeräysvelvoite` | false |
| `tyhjennys` finds `tyhjennysväli` | false |
| `jäteastia` finds `jäteastioiden` | false |
| `taajama` finds `taajamassa` | true |

Compound splitting is absent, as expected of a Snowball stemmer. The fourth row is the real problem:
that is not a compound but the *same word inflected* — `jäteastia` stems to `jäteast`, while
`jäteastioiden` stems to `jäteastio`. Finnish snowball produces two stems for one lemma on this
vocabulary.

**If recall lands materially higher than 0.3, the prediction was wrong and the reason must be
understood before touching retrieval.** A pleasant surprise is a finding, not a licence to move on.

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

# fi-rag-eval

Finnish-language document question answering over municipal waste regulations — built so that
**answer quality is measured, not asserted**.

> **Status: the harness runs; the pipeline it measures is one slice deep.** `make eval`
> ingests one authority's regulations, retrieves with Postgres full-text search alone, scores a
> hand-labelled golden set, prints the table below and fails on regression. No embeddings, no
> reranker, no language model, no judge yet — those are the next slices.
>
> **Read the caveat under the table before quoting any number.**

## Why this exists

Getting a language model to answer from a pile of PDFs is a weekend's work. Knowing *how well* it
answers, and whether last week's change made it better or worse, is the part that decides whether a
system can go to production. This project treats the evaluation harness as the product and the RAG
pipeline as the thing being measured.

## The problem it solves

Finnish waste regulations (`jätehuoltomääräykset`) are issued by regional waste authorities, each
acting for many municipalities at once, on top of national waste law — Turku is one of eighteen
municipalities under a single board. Answering a resident's question — *"how often must the bio-waste
bin be emptied at a property in Turku?"* — means finding the right authority's document and then
reporting what the regulation actually says, which is conditional: it depends on whether the property
lies in a built-up area of over 10,000 inhabitants, how many dwellings it has, whether the household
composts, and what kind of bin it is. One of those facts is not even in the regulations — the area
boundaries live in a separate map service.

So the honest answer has branches and a citation on each, and the system has to know which facts it
cannot resolve. Keyword search does not do this, and an unmeasured chatbot cannot be trusted with it.

## What it will do

- Ingest and chunk public Finnish waste regulations and national waste law.
- Retrieve with a hybrid of lexical full-text and vector search, then rerank.
- Answer with inline citations — conditionally, one citation per branch — and **refuse** when the
  retrieved context doesn't support an answer.
- Score itself against a golden set on every pull request, and fail CI on regression.

## Measured quality

Every number here was computed by `make eval`, never typed in. A dash means the slice that
would compute it does not exist yet.

Retrieval: **lexical only** — Postgres `ts_rank` over the `finnish` text-search configuration.
That is deliberately the weakest sensible baseline, and it is **not BM25**: `ts_rank` has no
inverse document frequency and, at its default normalisation, no document-length normalisation
either.

| Metric | Value | N | Notes |
| --- | --- | --- | --- |
| **Complete-set recall@5** | **0.875** | 8 questions | headline: did retrieval find *every* clause the answer depends on |
| Per-chunk recall@5 | 0.900 | 10 chunks | diagnostic — awards partial credit, so never the headline |
| MRR | 0.812 | 8 questions | diagnostic |
| Misses: unreachable / out-ranked | 0 / 1 | 1 chunk | zero stem overlap vs. matched but below k |
| Answer groundedness | — | | needs the answering slice |
| Branch coverage | — | | needs the answering slice |
| Over-claim rate | — | | needs the answering slice |
| Citation accuracy | — | | needs the answering slice |
| Refusal precision / recall | — | | needs the answering slice |
| Judge–human agreement | — | | needs the judge |
| p95 latency / cost per query | — | | no model runs yet; this slice costs €0 |

**The caveat, because the number is flattering and shouldn't be trusted:** the golden set has
only 8 questions, and they were written with the source PDF open. Measured consequence — **60%
of each question's stemmed content words appear verbatim in its target chunk.** The harness is
currently easier than the task, and 0.875 will fall when the questions are rewritten in a
resident's vocabulary. That rewrite outranks every retrieval improvement on the list. The
prediction registered before this run was 0.25–0.50; it was refuted, and *why* is written up in
[the slice spec](specs/SPEC-slice-1-measurement-spine.md#measured-result--26-aug-2026).

## Stack

Python · FastAPI · PostgreSQL + pgvector · LiteLLM · Docker · GitHub Actions · Google Cloud Run

## Running it

Needs Docker, [uv](https://docs.astral.sh/uv/), and `poppler-utils` (for `pdftotext`).

```sh
make dev     # create the environment
make eval    # start Postgres, fetch + chunk + load the corpus, score, print the table
```

`make eval` is reproducible from a clean clone: the source PDFs are not in git, but
[`corpus/manifest.yaml`](corpus/manifest.yaml) pins their URLs and SHA-256 digests, and
ingestion refuses to load a document that does not match — or one that parses to a different
number of clauses than the golden labels were written against.

It exits non-zero when a metric falls below [`eval/baseline.json`](eval/baseline.json), when a
golden label points at a chunk that does not exist, when the question set changes size, or when
the corpus is empty. All five paths have been exercised.

Other targets: `make gate` (lint, format, types, tests, build — the commit gate), `make ingest`,
`make db-up` / `make db-down`, `make eval-baseline` to re-record the baseline deliberately.

## Known weaknesses

Kept honestly, and at more length in [REVIEW-DEBT.md](REVIEW-DEBT.md).

- **The golden set leaks its source vocabulary** (60%, measured). The top item above; it makes
  the headline optimistic and, worse, blinds the harness to the vocabulary gap it exists to
  measure.
- **N=8.** The 95% interval on 0.875 is about ±0.23, and one question flipping moves it by
  0.125. Only 2 of 8 questions span multiple chunks, so complete-set and per-chunk recall have
  not yet diverged the way ADR-0003 expects them to.
- **The ranker's defaults are wrong for this corpus, on purpose.** `ts_rank` at normalisation 0
  does not divide by document length, so short chunks lose: definition chunks are 39% of the
  corpus and 0% of every top-5. Left in as the baseline; fixing it is a slice-3 candidate.
- **The authority hard filter is untested.** Only one authority is ingested, so the worst
  failure mode in the design — answering from the wrong jurisdiction — has nothing to leak
  from yet.
- **Finnish compounds are not split.** `biojäte` does not match `biojäteastia` under snowball
  stemming (4 of 4 term-pair tests failed). It did not bind on these eight questions; it will.
- **No CI.** The regression gate has been proven red by hand on this machine, which is not the
  same as proven in CI.

## Licence

MIT — see [LICENSE](LICENSE).

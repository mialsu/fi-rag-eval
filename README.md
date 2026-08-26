# fi-rag-eval

Finnish-language document question answering over municipal waste regulations — built so that
**answer quality is measured, not asserted**.

> **Status: design phase.** Nothing here runs yet. This repo currently contains
> [DESIGN.md](DESIGN.md) and its acceptance criteria. Build starts 31 Aug 2026.

## Why this exists

Getting a language model to answer from a pile of PDFs is a weekend's work. Knowing *how well* it
answers, and whether last week's change made it better or worse, is the part that decides whether a
system can go to production. This project treats the evaluation harness as the product and the RAG
pipeline as the thing being measured.

## The problem it solves

Finnish municipalities each publish their own waste regulations (`jätehuoltomääräykset`) on top of
national waste law. Answering a resident's question — *"how often does a two-person household in
Turku need the bio-waste bin emptied?"* — means knowing which municipality's rules apply, finding the
clause, and refusing to guess when the answer isn't in the source. Keyword search does not do this,
and an unmeasured chatbot cannot be trusted with it.

## What it will do

- Ingest and chunk public Finnish waste regulations and national waste law.
- Retrieve with a hybrid of BM25 and vector search, then rerank.
- Answer with inline citations, and **refuse** when the retrieved context doesn't support an answer.
- Score itself against a golden set on every pull request, and fail CI on regression.

## Measured quality

Filled in from the first real evaluation run. Until then it stays empty rather than aspirational.

| Metric | Value | Notes |
| --- | --- | --- |
| Retrieval recall@5 | — | |
| Retrieval MRR | — | |
| Answer groundedness | — | share of claims supported by cited context |
| Citation accuracy | — | cited chunk actually contains the claim |
| Refusal precision / recall | — | correctly declining unanswerable questions |
| p95 latency | — | |
| Cost per query | — | |

## Stack

Python · FastAPI · PostgreSQL + pgvector · LiteLLM · Docker · GitHub Actions · Google Cloud Run

## Running it

Will be documented here once there is something to run. The bar is: clone, `make dev`, `make eval`,
and you get the same table as above on your own machine.

## Known weaknesses

To be filled in honestly alongside the metrics. A README that lists no weaknesses has not been
evaluated.

## Licence

MIT — see [LICENSE](LICENSE).

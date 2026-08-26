# fi-rag-eval

Finnish-language document question answering over municipal waste regulations — built so that
**answer quality is measured, not asserted**.

> **Status: design phase.** Nothing here runs yet. This repo contains
> [DESIGN.md](DESIGN.md) and its acceptance criteria, plus the project scaffold and its build
> gates. `make gate` is green — which proves the toolchain and nothing more. `make eval` exits
> non-zero by design until there is a metric table to actually compute. Build starts 31 Aug 2026.

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
- Retrieve with a hybrid of BM25 and vector search, then rerank.
- Answer with inline citations — conditionally, one citation per branch — and **refuse** when the
  retrieved context doesn't support an answer.
- Score itself against a golden set on every pull request, and fail CI on regression.

## Measured quality

Filled in from the first real evaluation run. Until then it stays empty rather than aspirational.

| Metric | Value | Notes |
| --- | --- | --- |
| **Complete-set recall@5** | — | headline: did retrieval find *every* clause the answer depends on |
| Per-chunk recall@5 / MRR | — | diagnostics only |
| Answer groundedness | — | share of claims supported by cited context |
| Branch coverage | — | share of the required conditional branches the answer states |
| Over-claim rate | — | answers that flatten a conditional or resolve what the sources can't |
| Citation accuracy | — | cited chunk actually contains the claim |
| Refusal precision / recall | — | correctly declining unanswerable questions |
| Judge–human agreement | — | the judge is validated, not trusted |
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

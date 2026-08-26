# Product design document — fi-rag-eval

**Author:** Miska Sulander · **Written:** 26 Aug 2026 · **Status:** approved for build

---

## 1. Problem

Residents and municipal advisors need answers from waste regulations that differ per municipality and
sit on top of national law. The documents are public but fragmented, written in dense administrative
Finnish, and published as PDFs of varying quality.

Two failure modes matter more than average accuracy:

1. **Confident wrong answers** — quoting one municipality's rule for another's resident.
2. **Silent degradation** — a prompt or model change quietly making retrieval worse, with nobody noticing.

The second is the one this project is really about.

## 2. Users

| User | Needs |
| --- | --- |
| Municipal customer-service advisor | A fast, cited answer they can repeat to a resident without checking it themselves |
| Resident (secondary) | A plain-language answer with a link to the actual clause |
| Me, as the maintainer | To know whether a change helped or hurt, before shipping it |

## 3. Scope

**In scope**

- Ingestion and chunking of Finnish PDF/HTML regulations, with municipality as a first-class filter.
- Hybrid retrieval: PostgreSQL full-text search (BM25-ish) plus pgvector similarity, then a reranker.
- Answer generation with inline citations and an explicit refusal path.
- An evaluation harness with a hand-built golden set, run locally and in CI.
- Structured logging of latency, token counts and cost per query.
- Containerised deploy to Cloud Run.

**Out of scope**

- A polished chat UI. A minimal one exists only to make the demo watchable.
- Multi-tenant auth, user accounts, conversation memory.
- Fine-tuning. If the base model can't do this with good retrieval, the retrieval is the problem.
- Real-time ingestion of regulation updates.

## 4. Architecture

```
PDF/HTML sources
      │
      ▼
  ingest ──► chunk (structure-aware, clause-level) ──► embed ──► PostgreSQL + pgvector
                                                                   │
query ──► retrieve (BM25 ∪ vector, municipality filter) ──► rerank ─┘
      │
      ▼
  answer (LiteLLM) ──► citations + refusal check ──► response
      │
      └──► structured log: latency, tokens, cost, retrieved ids
```

**Key decisions**

- *LiteLLM as the LLM boundary* — so the same eval harness can compare models without touching call sites.
- *Clause-level chunking, not fixed windows* — regulations are structured; a chunk that straddles two
  clauses produces citations that don't defend the claim.
- *Municipality as a hard filter, not a soft signal* — cross-municipality answers are the worst failure
  mode, so they are made structurally impossible rather than discouraged by prompt.
- *Refusal is a first-class output*, evaluated like any other answer.

## 5. Data

Public sources: national waste law (`jätelaki`) and the waste regulations of a handful of
municipalities, chosen for format variety. No personal data. Raw documents stay out of git
(`data/raw/` is ignored); ingestion is reproducible from a manifest of source URLs.

## 6. Evaluation plan

The core of the project.

**Golden set** — ~50 questions, hand-written and hand-answered from the sources, deliberately including:
- questions answerable only from one municipality's rules,
- questions whose answer differs between municipalities,
- questions the corpus genuinely cannot answer (the refusal cases),
- questions where the obvious keyword match is the wrong clause.

**Metrics**

| Layer | Metric | Why |
| --- | --- | --- |
| Retrieval | recall@k, MRR | Retrieval failure caps everything downstream |
| Answer | groundedness | Every claim traceable to cited context |
| Answer | citation accuracy | A citation that doesn't contain the claim is worse than none |
| Behaviour | refusal precision / recall | Measures the thing that keeps it trustworthy |
| Ops | p95 latency, cost per query | Production viability |

**Judging** — retrieval metrics are computed against labelled chunk ids, no model involved. Answer
metrics use an LLM judge with a different model than the one under test, spot-checked by hand on a
fixed sample each run. The judge's own agreement with my manual labels is reported, because an
unvalidated judge is just a second opinion with extra steps.

**Regression gate** — `make eval` in CI on every pull request; the run posts the metric table as a PR
comment and fails on a drop beyond a set threshold.

## 7. Milestones

| # | Deliverable | Target |
| --- | --- | --- |
| M1 | Ingestion, chunking, hybrid retrieval working; retrieval metrics computable | 6 Sep 2026 |
| M2 | Answering with citations and refusal; answer metrics computable | 13 Sep 2026 |
| M3 | Golden set complete, CI gate green, deployed to Cloud Run, README table filled | 20 Sep 2026 |

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| The golden set is the project; a lazy one makes every number meaningless | Hand-write it first, before any tuning, and include adversarial cases |
| Finnish compound words break lexical search | Test BM25 alone early; add lemmatisation if recall is poor |
| LLM judge disagrees with human judgement | Report judge–human agreement on a fixed sample every run |
| Scope creep into a chat product | Non-goals above are binding; the UI stays minimal |

## 9. Definition of done

- README opens with a filled metric table, not an architecture diagram.
- `make eval` reproduces that table from a clean clone.
- CI runs the evaluation and fails on regression.
- A public URL or a 90-second recording demonstrates it working.
- The "Known weaknesses" section names at least three real ones.

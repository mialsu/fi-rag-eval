# Product design document — fi-rag-eval

**Author:** Miska Sulander · **Written:** 26 Aug 2026 · **Status:** approved for build
**Revised:** 26 Aug 2026 after `/grill-with-docs` — the jurisdiction model, the metric set and one
golden-set category changed once the design was checked against the real sources. See ADR-0002,
ADR-0003, ADR-0004; vocabulary in `CONTEXT.md`.

---

## 1. Problem

Residents and municipal advisors need answers from waste regulations that are issued per *regional
waste authority* — each acting for many municipalities at once — and sit on top of national law. The documents are public but fragmented, written in dense administrative
Finnish, and published as PDFs of varying quality.

Two failure modes matter more than average accuracy:

1. **Confident wrong answers** — quoting one authority's rule for a resident it does not cover, or
   flattening a conditional obligation into a single number it never had.
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

- Ingestion and chunking of Finnish PDF/HTML regulations, with the **authority** as a first-class
  filter and the municipality as user-facing input resolved to it (ADR-0002).
- Hybrid retrieval: PostgreSQL full-text search plus pgvector similarity, then a reranker. Note the
  native lexical ranker (`ts_rank`) is **not** BM25 — it has no inverse document frequency — so a
  BM25 extension is an option if measurement shows the lexical arm is the bottleneck.
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
query ──► retrieve (lexical ∪ vector, authority filter) ──► rerank ─┘
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
- *Authority as a hard filter, not a soft signal* — cross-jurisdiction answers are the worst failure
  mode, so they are made structurally impossible rather than discouraged by prompt. The filter keys on
  the authority because that, not the municipality, is what publishes a document (ADR-0002).
- *Conditional answers with a citation per branch* — most obligations are conditioned on area,
  dwelling count, bin type or property type, and determining variables are sometimes outside the
  corpus by the document's own design. Flattening a conditional is a confident wrong answer (ADR-0003).
- *Chunks are addressed by the document's own numbering*, not by the chunker's output, so hand-written
  golden labels survive re-extraction and re-chunking (ADR-0004).
- *Refusal is a first-class output*, evaluated like any other answer.

## 5. Data

Public sources: national waste law (`jätelaki`) and the waste regulations of a handful of
municipalities, chosen for format variety. No personal data. Raw documents stay out of git
(`data/raw/` is ignored); ingestion is reproducible from a manifest of source URLs.

## 6. Evaluation plan

The core of the project.

**Golden set** — ~50 questions, hand-written and hand-answered from the sources, deliberately including:
- questions answerable only from one authority's rules,
- questions whose answer differs **between authorities** — within one authority the text is uniform,
  so same-authority municipalities differ in nothing,
- questions whose answer varies by sub-municipal zone (a taajama threshold) or by property type,
- questions the corpus genuinely cannot answer (the refusal cases),
- questions where the obvious keyword match is the wrong clause.

**Metrics**

| Layer | Metric | Why |
| --- | --- | --- |
| Retrieval | **complete-set recall@k** (headline) | An answer needs every clause it depends on; partial retrieval yields a confident wrong answer, not a partial one |
| Retrieval | per-chunk recall@k, MRR (diagnostics) | Shows *how far* off a miss was — one clause of three, or all three |
| Answer | groundedness | Every claim traceable to cited context, where a claim is one conditional branch |
| Answer | branch coverage | Share of the required branches the answer actually states; localises which one was dropped |
| Answer | over-claim rate | Catches flattening a conditional or resolving a variable the corpus cannot resolve |
| Answer | citation accuracy | A citation that doesn't contain the claim is worse than none |
| Behaviour | refusal precision / recall | Measures the thing that keeps it trustworthy |
| Judge | judge–human agreement | An unvalidated judge is a second opinion with extra steps |
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

> **M1 status, 27 Aug 2026: retrieval metrics are computable; hybrid retrieval will not be.**
> Ingestion, chunking and *lexical* retrieval are done and measured across 12 configurations.
> "Hybrid" means lexical ∪ vector, and the vector arm was deliberately deferred past slice 4 —
> the instrument cannot currently resolve what it would buy (N=21, ±0.18). Slice 4 fixes the
> instrument instead. So M1 lands **partial** on 6 Sep, and saying so is the point of the tracker.
| M2 | Answering with citations and refusal; answer metrics computable | 13 Sep 2026 |
| M3 | Golden set complete, CI gate green, deployed to Cloud Run, README table filled | 20 Sep 2026 |

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| The golden set is the project; a lazy one makes every number meaningless | Hand-write it first, before any tuning, and include adversarial cases |
| Finnish compound words break lexical search | Test the lexical arm alone early — and note `ts_rank` is not BM25. Add lemmatisation if recall is poor. **Corrected 27 Aug 2026:** this said `dict_voikko`, a Postgres text-search dictionary that does not exist in `postgres:17-alpine` and is not packaged for it. Slice 3 lemmatises with voikko in Python instead — ADR-0005 |
| LLM judge disagrees with human judgement | Report judge–human agreement on a fixed sample every run |
| Scope creep into a chat product | Non-goals above are binding; the UI stays minimal |

## 9. Definition of done

- README opens with a filled metric table, not an architecture diagram.
- `make eval` reproduces that table from a clean clone.
- CI runs the evaluation and fails on regression.
- A public URL or a 90-second recording demonstrates it working.
- The "Known weaknesses" section names at least three real ones.

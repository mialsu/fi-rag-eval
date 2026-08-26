# CONTEXT.md — fi-rag-eval

The project's canonical vocabulary: the words the code and the domain actually use, defined once
so every session (and every agent) speaks the same language. Glossary only — no implementation
detail, no file paths (those go stale). This is the single source of truth for names.

**Purpose (one sentence):** Answer Finnish waste-regulation questions with citations or an honest
refusal, and measure that answer quality well enough to catch a regression before it ships.

## Glossary

| Term | Means | Notes |
|---|---|---|
| Jätelaki | The Finnish national Waste Act. | The national floor every municipality builds on. |
| Jätehuoltomääräykset | A municipality's own waste-management regulations, sitting on top of `jätelaki`. | The per-municipality layer. This is what differs and what makes the municipality filter load-bearing. |
| Source | One original public document (a PDF or HTML page) as published by its authority. | The unit of ingestion, listed in the manifest. |
| Manifest | The checked-in list of source URLs that makes ingestion reproducible. | Raw documents stay out of git; the manifest is what is versioned. |
| Chunk | One clause-level passage of a source, the unit that is embedded, retrieved and cited. | Clause-level by decision, not fixed-window — a chunk straddling two clauses produces a citation that does not defend the claim. |
| Municipality | The jurisdiction whose regulations apply to a question. Applied as a hard pre-filter. | See **Flagged ambiguities** — whether this is the *kunta* or the regional waste authority is not yet settled. |
| Hybrid retrieval | Lexical (Postgres full-text, BM25-ish) union vector (pgvector) candidate generation. | Neither alone; the union is then reranked. |
| Rerank | The second-stage scoring that orders the union of candidates before they reach the model. | |
| Refusal | A first-class output: declining to answer because the retrieved context does not support one. | Evaluated like any other answer. A refusal is a correct answer to an unanswerable question. |
| Citation | A pointer from a claim in the answer to the chunk that supports it. | |
| Golden set | The hand-written, hand-answered question set the harness scores against. | ~50 questions. Written before any tuning, deliberately adversarial. |
| Groundedness | The share of claims in an answer that are supported by the cited context. | Judged by model, validated against hand labels. |
| Citation accuracy | Whether a cited chunk actually contains the claim it is attached to. | A citation that does not contain the claim is worse than no citation. |
| recall@k / MRR | Retrieval metrics computed against labelled chunk ids. | No model involved — these are arithmetic, and therefore the metrics to trust most. |
| Judge | The model that scores answer-layer metrics. Always a different model than the one under test. | Its own agreement with hand labels is reported every run. |
| Judge–human agreement | How often the judge matches the maintainer's manual label on a fixed sample. | Reported every run. An unvalidated judge is a second opinion with extra steps. |
| Regression gate | The CI check that fails a pull request when a metric drops beyond a threshold. | The point of the whole project. |
| Golden-set leakage | Tuning against the golden set until the numbers rise without real quality rising. | The failure mode that quietly turns the harness into decoration. |

## Avoid these words

| Don't say | Say instead | Why |
|---|---|---|
| Accuracy | The named metric (`recall@5`, `groundedness`, `citation accuracy`) | "Accuracy" hides which layer failed, and retrieval failure caps everything downstream. |
| Chatbot | Answering service / QA over sources | A chat product is an explicit non-goal; the word invites scope creep toward one. |
| Document | `source` (the original) or `chunk` (the retrieved passage) | The ambiguity between the two is exactly where citation bugs hide. |
| City | Municipality | The Finnish unit is the *kunta*, which is not always a city. |
| I don't know | Refusal | A refusal is a designed, evaluated output, not a failure to respond. |
| Passed / green | The metric value, with the N it was computed over | A green run over a silently reduced question set is the harness's worst lie. |

## Flagged ambiguities

Words we haven't fully pinned down yet — resolve before they cause a bug.

- **"Municipality" — the *kunta*, or the regional waste authority?** Many Finnish municipalities
  delegate waste management to a regional company or joint authority (a *jätehuoltoyhtiö* or
  *jätelautakunta*), which is often the body that actually publishes the regulations for several
  municipalities at once. A resident asks about their *kunta*; the applicable document may be
  regional. Since the municipality filter is a hard filter and cross-jurisdiction answers are the
  #1 failure mode, this needs deciding before ingestion, not after. Likely resolution: model both,
  with a *kunta* → authority mapping, and filter on the authority while accepting the *kunta* as
  the user-facing input.
- **What counts as one "claim"** for groundedness — a sentence, or a proposition? Two graders will
  disagree on the denominator, which makes the metric unstable run-to-run.
- **Whether a partially-supported answer is a refusal case.** If the corpus answers half the
  question, the correct behaviour (answer the half, or refuse) is not yet decided.

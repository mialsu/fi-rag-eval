# ADR-0004 — Clause-level chunking with two carve-outs, and stable chunk addressing

- **Date:** 2026-08-26
- **Status:** accepted

## Context

`DESIGN.md:65-67` decides clause-level chunking over fixed windows, on the grounds that a chunk
straddling two clauses produces a citation that does not defend the claim. Applying that to the real
Southwest Finland document surfaced three things, each measured rather than assumed.

- **72 clause headings**, median ~175 tokens, largest ~2,076. Thirteen exceed ~512 tokens.
- **2 § `Määritelmät`** is the largest at ~2,076 tokens and holds roughly 40 unrelated definitions.
  Answering "what counts as biojäte" by retrieving all forty is dilution, not precision.
- **3 § shreds under a naive parser.** It lists which clauses bind non-residential properties, *by
  sub-clause*: `17 § Kompostointi, momentit 1–3, 5, 7–9`, `23 § Jäteastiatyypit, momentit 1–3, 6`.
  A chunker splitting on `^\d+ §` reads those reference lines as ten-plus empty clauses. Our own
  first parse did exactly that — this is a demonstrated defect, not a hypothesis.

Separately, chunk **identity** turned out to be load-bearing. Golden labels are hand-written against
chunk ids, and hand-labelling is the scarcest resource in the project. An id that changes when the
extractor or the chunker changes means relabelling by hand, repeatedly.

## Decision

**Chunk = one clause (§), whole**, with tables and their footnotes kept inline, plus two carve-outs:

1. `2 § Määritelmät` splits into one chunk per defined term.
2. Structural cross-reference lists and tables are atomic, so 3 § is never shredded.

**Momentti-level applicability is deliberately not modelled.** It matters for business properties;
the users in `DESIGN.md:22-26` are the advisor and the resident. Business-property questions are
therefore a **known-fail class** in the golden set, confessed in `REVIEW-DEBT.md`.

**Chunk address** is the document's own addressing, not the chunker's:

```
authority @ effective_date # clause [. sub_key]

lounais-suomi@2024-08-01#15
lounais-suomi@2024-08-01#2.biojate
```

A **content hash is stored alongside, never as the key**, so that text changing behind a stable
address is detectable. An address that cannot be resolved is a **hard error**, never a silently
skipped question — the same rule as the N assertion in `CLAUDE.md`.

## Rejected alternatives

- **Momentti-level chunks** — the most faithful model, since the regulation cites itself at that
  granularity. Rejected for the MVP because it front-loads ingestion machinery before a single
  metric exists, risks over-fragmentation, and buys correctness mainly for property types that are
  not our users.
- **Strict § chunks with no carve-outs** — the purest reading of the existing decision and the
  fastest path to a first number, letting the harness justify any change. Rejected because it would
  ship two defects already demonstrated in the real document, so the first eval run would measure a
  chunker we already know to be broken.
- **Content-addressed ids (hash as the key)** — makes drift impossible by construction. Rejected
  because it couples the scarcest resource (hand labels) to the most incidental detail (the
  extraction pipeline): a poppler upgrade or a whitespace fix would invalidate every label at once.
- **Surrogate serial ids** — the obvious Postgres default. Rejected because it fails *silently*: a
  re-ingest can reorder rows, so a label that meant 26 § now means 31 §, and the harness computes a
  green recall figure against the wrong ground truth. That is the exact class of confidently-wrong
  measurement this project exists to prevent.

## Consequences

**Easy.** Labels survive re-extraction and chunker changes. Version pinning falls out of the address
for free, so an amendment cannot silently migrate labels.

**Hard.** A new document version requires labels to be re-pointed explicitly, by hand. That is the
intended cost — the alternative is labels that move without anyone deciding they should.

**Living with.** The exact `effective_date` of the ingested document must be read out of the
document at ingest, not guessed: the file retrieved during shaping is titled as an amendment dated
22.10.2025 while its metadata states 1.8.2024. Resolving that is an ingestion task in slice 1.

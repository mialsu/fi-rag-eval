# ADR-0004 — Clause-level chunking with two carve-outs, and stable chunk addressing

- **Date:** 2026-08-26
- **Status:** accepted, with two corrections recorded 26 Aug 2026 after
  slice 1 implemented it against the real document — see **Corrections** at the end. Neither
  changes the decision; both change a detail the decision was written on.

## Context

`DESIGN.md:65-67` decides clause-level chunking over fixed windows, on the grounds that a chunk
straddling two clauses produces a citation that does not defend the claim. Applying that to the real
Southwest Finland document surfaced three things, each measured rather than assumed.

- **72 clause headings**, median ~175 tokens, largest ~2,076. Thirteen exceed ~512 tokens.
- **2 § `Määritelmät`** is the largest at ~2,076 tokens and holds roughly 40 unrelated definitions.
  Answering "what counts as biojäte" by retrieving all forty is dilution, not precision.
- **A cross-reference list shreds under a naive parser.** One clause lists which clauses bind
  non-residential properties, *by sub-clause*: `17 § Kompostointi, momentit 1–3, 5, 7–9`,
  `23 § Jäteastiatyypit, momentit 1–3, 6`. A chunker splitting on `^\d+ §` reads those reference
  lines as twenty-one empty clauses. Our own first parse did exactly that — this is a demonstrated
  defect, not a hypothesis. (The list is in **1 § Soveltamisala**; see Corrections.)

Separately, chunk **identity** turned out to be load-bearing. Golden labels are hand-written against
chunk ids, and hand-labelling is the scarcest resource in the project. An id that changes when the
extractor or the chunker changes means relabelling by hand, repeatedly.

## Decision

**Chunk = one clause (§), whole**, with tables and their footnotes kept inline, plus two carve-outs:

1. `2 § Määritelmät` splits into one chunk per defined term.
2. Structural cross-reference lists and tables are atomic, so the clause that lists other
   clauses is never shredded.

**Momentti-level applicability is deliberately not modelled.** It matters for business properties;
the users in `DESIGN.md:22-26` are the advisor and the resident. Business-property questions are
therefore a **known-fail class** in the golden set, confessed in `REVIEW-DEBT.md`.

**Chunk address** is the document's own addressing, not the chunker's:

```
authority @ effective_date # clause [. sub_key]

lounais-suomi@2024-08-01#15
lounais-suomi@2024-08-01#2.biojatteella    (see Corrections: this ADR first wrote `#2.biojate`)
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

## Corrections (26 Aug 2026, from implementing this in slice 1)

Recorded rather than edited in place, because an ADR whose grounds change silently is worth
nothing.

**1. The cross-reference list is in 1 §, not 3 §.** This ADR named 3 § throughout. The
21-line list of clauses binding non-residential properties is the tail of **1 §
Soveltamisala**; 3 § is `Jätehuollon tavoitteet`, four short paragraphs with no list at all.
The hazard is exactly as described and the carve-out is exactly as needed — only the clause
number was wrong.

The carve-out also turned out not to need a special case. `src/fi_rag_eval/chunking.py`
defends it with an invariant instead: a heading candidate is a heading only if its number is
the one the document is due next, *and* the resulting inventory must equal the document's own
table of contents. A reference to 17 § while the parser is waiting for 2 § cannot be mistaken
for a heading, and a document whose two halves disagree is a hard error rather than a
silently different corpus. Tables and lists are then atomic by construction, since no clause
but 2 § is ever split.

**2. A definition's sub-key is a paragraph prefix, not the defined term.** This ADR's example
address is `lounais-suomi@2024-08-01#2.biojate` — the nominative lemma. Two problems, both
found by building it:

- The definiendum in the source is a **bolded phrase**, not a word: "Saostus- ja
  umpisäiliölietteellä", "Kiinteistön haltijan järjestämällä jätteenkuljetuksella". Bold is
  invisible to `pdftotext`, so the phrase boundary is not recoverable from the text.
- Deriving `biojäte` from `Biojätteellä` needs real morphology (the stem is `biojättee-`),
  which is precisely what slice 1 does not have. A guessed lemma makes an *unstable* address,
  and label stability is this ADR's whole point.

The rule is therefore: the sub-key is the shortest leading-word prefix that is unique within
the clause — `#2.biojatteella`, and `#2.kunnan-jarjestamalla` only because three definitions
open with "Kunnan". It depends on nothing but that paragraph's own opening words, so it
survives re-extraction and re-chunking, which is what this ADR actually asks of an address.
`pdftohtml -xml` does expose the bold runs and would make the term exact; the cost is a
second extractor, and it is not paid yet. Logged in `REVIEW-DEBT.md`.

**3. The effective-date question from "Living with" is resolved.** The date is read out of
49 § Voimaantulo (`tulevat voimaan 1.8.2024`) and cross-checked against the manifest, which
is a hard error on mismatch. The residual problem — that this file also carries the 25 §
amendment of 22.10.2025, so one address covers two editions of that clause — is logged in
`REVIEW-DEBT.md` rather than resolved.

**4. The shaping-session counts were rough; the ingested figures are these.** This ADR's
Context says "72 clause headings" and "roughly 40 unrelated definitions". Those were counts
of heading-*like* lines and an eyeball estimate, taken before a parser existed. The document
has **50 clauses** and 2 § holds **32 definitions**; the 72 figure was inflated by the very
cross-reference list correction 1 is about. Chunking yields **82 chunks** (49 whole clauses,
2 §'s preamble, 32 definitions), and `corpus/manifest.yaml` now asserts all three numbers at
ingest so a silent re-parse cannot invalidate a hand-written label unnoticed.

# ADR-0006 — the address keys on Voimaantulo; the edition is declared and cited

- **Date:** 2026-08-27
- **Status:** accepted

## Context

ADR-0004 makes a chunk's address `authority @ effective_date # clause`, and `effective_date` is
read **out of the document's own Voimaantulo clause** rather than taken from the manifest —
deliberately, because a guessed date would be part of every address.

Ingesting Pirkanmaa (slice 4) turns that into a problem the single-authority corpus never showed.
Read from the document, not assumed:

| Source | Says |
|---|---|
| `47 § VOIMAANTULO` | *"Nämä jätehuoltomääräykset tulevat voimaan **1.7.2021**"* |
| Front matter | approved 19.5.2021 § 27, **päivitetty 7.6.2023 § 25, 6.3.2024 § 13, 9.4.2025 § 18, 22.10.2025 § 49** |
| The authority publishes it as | **1.5.2026 alkaen** |

`ingest.read_effective_date` matches `tulevat voimaan (\d+)\.(\d+)\.(\d+)` and hard-fails unless
exactly one date is found, so the address is mechanically forced to `pirkanmaa@2021-07-01#15` — a
key naming 2021 for text amended five times since. Every chunk of this document shares that
address space with five superseded editions.

This escalates an open `REVIEW-DEBT.md` entry from **two** editions sharing an address to **six**.
That entry's trigger reads "before a second *version* of the same document is ingested"; Pirkanmaa
is a second *authority*, so the trigger does not technically fire. Saying so is more useful than
pretending it does.

Lounais-Suomi has the same shape more mildly: in force 1.8.2024, with 25 § amended 22.10.2025.

## Decision

**The address keys on Voimaantulo, unchanged. The edition is declared in the manifest, asserted
against the document, and carried into the citation.**

Three parts, and the third is what makes the second worth having:

1. `pirkanmaa@2021-07-01#15` stays the key. Stable, no code change, no relabelling.
2. The manifest gains a required `edition` per source: a human-facing `label` (`1.5.2026 alkaen`,
   verbatim from how the authority publishes it) and `front_matter_dates`, **every** date in the
   document's front matter. `ingest.assert_edition` reads the front matter and refuses to load a
   document whose approval or amendment history has moved.
3. The stored citation becomes `23 § KERÄYSVÄLINETYYPIT (Kunnalliset jätehuoltomääräykset,
   1.5.2026 alkaen)`. The honesty problem is fixed **where it is actually read** — by a human,
   in a citation — rather than in an identifier no reader sees.

`front_matter_dates` is deliberately shape-agnostic: it does not try to tell an approval date from
an amendment date, because the two documents in the corpus already write that three different
ways. It only has to detect change, and an edition label nobody can check is the same defect as a
metric nobody can reproduce, aimed at a human instead of at CI.

## Rejected alternatives

- **Re-key to the latest amendment date** (`pirkanmaa@2025-10-22`, `lounais-suomi@2025-10-22`) —
  rejected on cost, not on correctness. It is the *most honest* addressing available and would
  fully close the debt. It costs front-matter parsing, relabelling all 21 existing questions, and
  a re-baseline, spent in the same slice that already needs 29 new labels read by hand.
  Hand-labelling is the one resource this project cannot buy back.
- **Voimaantulo alone, unchanged, with no edition anywhere** — rejected because it is the cheapest
  option and leaves the 2021 date quietly misleading every human who reads a citation. A citation
  is the product's whole claim to trustworthiness.
- **An edition label with no assertion against the document** — rejected because a hand-written
  string with nothing tying it to the PDF goes stale silently on the next republication, and then
  the citation is confidently wrong rather than merely incomplete.
- **Storing the edition on the `source` table and leaving the citation alone** — rejected because
  nothing reads that column. Capability nobody exercises is not a fix.

## Consequences

**Easy.** A reader of any chunk now learns which published revision they are being shown, and the
label cannot rot: a sixth Pirkanmaa amendment fails the ingest with a message naming both date
lists. Adding a genuinely new *version* of a document later is unaffected — that still needs the
address work ADR-0004's debt entry describes.

**Hard.** The address still cannot distinguish six editions of Pirkanmaa's text. If the authority
republishes with the same Voimaantulo date and different clause text, the `content_sha256` beside
each chunk detects the drift and the front-matter assertion fails the ingest, but the *address*
is unchanged — so two editions cannot coexist in one corpus.

**Living with.** Two different dates now describe one document in two places, and a reader must
understand that the address's date is *when the text came into force* while the edition's is
*which revision this is*. `CONTEXT.md` carries both terms with that distinction spelled out,
because a word that means two things to two readers is the failure `CONTEXT.md` exists to prevent.

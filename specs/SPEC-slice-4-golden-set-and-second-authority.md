# SPEC — slice 4: the golden set and a second authority

**Status:** **BUILT 27 Aug 2026.** Shaped after `/grill-with-docs`; predictions scored in
**Measured result** at the end of this file, refutations first. Two of six predictions were
refuted, including the strongest one, and a slice-3 finding was retracted.
**Weight:** Standard.
**Decided by the Owner over a pre-registered rule.** Slice 3 pre-registered slice 4 as the vector
layer. The Owner overrode that on 27 Aug 2026; the override sits beside the rule it supersedes in
`specs/SPEC-slice-3-lemmatisation.md`, never silently. This slice is the golden set plus a second
authority, and the vector layer becomes slice 5.

## The statistic that override should have used

The override argued that at N=21 the vector layer's predicted 0.095 gain "sits inside the ±0.18
interval". That is the wrong test, and the correction makes the argument **stronger**, not weaker.

Two cells are scored on the *same* questions, so the comparison is paired. The exact McNemar
test on `d` discordant questions all flipping one way gives `p = 2 x 0.5^d`:

| d | 1 | 2 | 3 | 4 | 5 | **6** |
|---|---|---|---|---|---|---|
| p | 1.000 | 0.500 | 0.250 | 0.125 | 0.062 | **0.031** |

Six questions must flip for a paired win at p<0.05. The best cell (`lemma-reasm/1`, 0.857) has
**three** failures. So fixing *every remaining miss in the best cell* yields d=3, p=0.25:

> **At N=21 there is no result slice 5 could have produced that would register at all.**
> Not "the effect is small relative to noise" — the instrument has no power at any effect size.

That is why the golden set comes first, and it is a sharper claim than the interval made. What N
buys, from a failure rate `f`, closing a fraction `r` of the misses (needs `d >= 6`):

| measured from | close all | close 3/4 | **close 1/2** | close 1/3 |
|---|---|---|---|---|
| published `snowball/0` (f=0.238) | N>=26 | N>=34 | **N>=51** | N>=77 |
| best `lemma-reasm/1` (f=0.143) | N>=42 | N>=56 | **N>=84** | N>=128 |

`DESIGN.md`'s ~50 is well chosen **while the headline stays on the snowball cell**, and
underpowered by ~1.7x if it ever moves to `lemma-reasm/1`. That coupling was not previously
written down anywhere, and it is the real cost of moving the published cell.

The regression *gate* needs none of this — it is deterministic at any N. Power is only about
claiming an improvement is real.

## The reconnaissance that shaped this slice

Five real candidate authorities were run through **this project's own pipeline**, not judged by
eye. Verdicts, not opinions:

| Candidate | Kunnat | extract | parse_toc | split_clauses | chunk | Gap |
|---|---|---|---|---|---|---|
| Lounais-Suomi (control) | 18 | ok | 50 cl, 11 ch | ok | 82 chunks | — |
| **Pirkanmaa** | 17 | ok | 48 cl, **0 ch** | ok 48 | **fails** | 2 § is a bullet list |
| HSY / Helsinki | 5 | **fails** | — | — | — | TOC has no page numbers |
| Oulu | ~10 | **fails** | — | — | — | TOC aligns pages with spaces |
| Savo-Pielinen / Kuopio | 15 | **fails** | — | — | — | same, + 21pp of justifications |
| Uudenmaan (bilingual) | 12 | ok | **fails** | — | — | >=2 bugs, unmeasured tail |

Three findings worth more than the table:

1. **`extract.py`'s dot-leader requirement is a Lounais-Suomi assumption wearing an invariant's
   clothes.** HSY, Oulu and Savo-Pielinen all have clean, complete tables of contents — they
   simply do not use dot leaders. Any of those three forces that generalisation. Pirkanmaa is the
   only candidate that does not. Confessed, not fixed (D5).
2. **Uudenmaan's failure was our bug, not their document.** 32 § is present in both its TOC and
   its body. `parse_toc` treats "4+ dots" as the only entry terminator, and `pdftotext` compressed
   31 §'s leader to a single dot, so 31 swallowed 32. Relaxing that yields 46 clauses and then
   fails again on a wrapped heading. Also confessed.
3. **Pirkanmaa already proves one kind of variety absorbed.** It has **zero `LUKU` chapters**
   against Lounais-Suomi's 11, and `split_clauses` handled that with no change at all.

## What Pirkanmaa is

Read from the document and the authority's own pages, not assumed.

- **Authority:** *Alueellinen jätehuoltolautakunta*, a 17-municipality joint body with Tampere as
  vastuukunta. Its area is Pirkanmaan Jätehuolto Oy's service area.
- **Source:** `Kunnalliset-jatehuoltomaaraykset--1.5.2026-alkaen-_0.pdf`, 4.2 MB, 42 pages,
  sha256 `69b4663b01c8007df21bc9d29ba3fba50e150e24d90dc39423fe468472e95892`.
- **Parse:** 48 clauses (1..48), 0 chapters, 91,870 body chars (Lounais-Suomi: 67,285), and only
  **2 hyphen joins** against Lounais-Suomi's 258 — the text is not justified, so less extraction
  risk, not more.
- **Clause titles are UPPERCASE** (`MÄÄRITELMÄT`, `SIIRTYMÄSÄÄNNÖKSET`). `_normalise_title`
  casefolds, so the TOC-to-body cross-check survives; the citation string will read uppercase.
- **2 § MÄÄRITELMÄT holds 41 definitions as `• term …` bullets**, after the same
  `Näissä jätehuoltomääräyksissä tarkoitetaan:` intro line Lounais-Suomi uses. Same shape,
  different delimiter. This is the one thing that must change to ingest it.

### The date problem

| Source | Says |
|---|---|
| `47 § VOIMAANTULO` | *"tulevat voimaan **1.7.2021**"* |
| Front matter | approved 19.5.2021, **päivitetty 7.6.2023, 6.3.2024, 9.4.2025, 22.10.2025** |
| The authority publishes it as | **1.5.2026 alkaen** |

`ingest.read_effective_date` matches `tulevat voimaan (\d+)\.(\d+)\.(\d+)` and hard-fails on
disagreement, so the address is mechanically forced to `pirkanmaa@2021-07-01#15` — a key naming
2021 for text amended five times since. This escalates `REVIEW-DEBT.md`'s open entry from **two**
editions sharing an address to **six**. That entry's trigger reads "before a second *version* of
the same document is ingested"; Pirkanmaa is a second *authority*, so the trigger does not
technically fire, and saying so is more useful than pretending it does. See D3.

### The vocabulary fork — the finding that justifies this slice

The two authorities use **different words for the same things**:

| Concept | Lounais-Suomi | Pirkanmaa |
|---|---|---|
| the bin | `jäteastia` | **`keräysväline`** (20 § KERÄYSVÄLINETYYPIT) |
| shared bin | `yhteinen jäteastia` | **`kimppa`** (8 § KIMPPA ELI YHTEINEN KERÄYSPISTE) |
| composting | 17 § | 18 § |
| separate-collection duty | 15 § | 15 § |

This is a **synonym** gap, not a morphology gap. `keräysväline` and `jäteastia` share no stem, so
no analyser can bridge them: slice 3's compound splitting is irrelevant here. A question phrased
in one authority's vocabulary will systematically under-retrieve in the other's document, and the
miss diagnostic will report it as **zero-overlap** — the class slice 3 drove from 4 to 0. Slice 4
therefore reopens that class for a *different mechanism with a different fix*, and measuring that
is worth more to the instrument than another 29 questions on one corpus would be.

> **⚠️ MEASURED AND WRONG about the mechanism, right about the effect.** The fork is real and it
> does cost recall — but it surfaces as **ranked-out**, not zero-overlap. A question shares plenty
> of *other* lexemes with its target even when the key noun shares no stem, so "zero overlap" is a
> far stronger condition than "the synonym is bridged". Zero-overlap misses stayed at **0** in
> every `lemma-reasm` cell. See **Measured result → Prediction 3**; this paragraph is left as
> written because a prediction edited after the fact measures nothing.

### Sastamala is not covered whole — and that contradicts ADR-0002

`1 § SOVELTAMISALA`, read from the document, lists the area as:

> Hämeenkyrön, Ikaalisten, Juupajoen, Kangasalan, Lempäälän, Mänttä-Vilppulan, Nokian, Oriveden,
> Parkanon, Pirkkalan, Pälkäneen, Ruoveden, **Sastamalan (Mouhijärven ja Suodenniemen osalta)**,
> Tampereen, Vesilahden, Virtain ja Ylöjärven

Sastamala is claimed **only for its former Mouhijärvi and Suodenniemi areas**. That is a real
counterexample to a load-bearing decision:

- `CONTEXT.md` — *"Municipality … resolved to **exactly one** Authority through a checked-in map."*
- `manifest.resolve_municipality` raises `ManifestError` when two authorities claim one kunta,
  deliberately, because silently picking one is the cross-jurisdiction answer the filter prevents.

The map is therefore **not a function** for Sastamala, and no amount of care in the manifest makes
it one. Handled in D4, and raised as the top open question because it amends ADR-0002's model
rather than merely annotating it.

## Decisions

Each was put to the Owner with alternatives; the rejected ones are recorded because a decision
without its alternatives is unreviewable. **D3 is ADR-worthy** and lands as ADR-0006.

**D1 — the second authority is Pirkanmaa.** Chosen on measured intake cost, not geography: it
passes four of five pipeline stages today including the strictest invariant (every body heading
cross-checked against the document's own TOC), and needs exactly one contained fix. It also
delivers genuine format variety in the sense `DESIGN.md:86` intended — bulleted definitions, no
chapter structure — and Pirkanmaan Jätehuolto plus tampere.fi carry resident-facing pages to
harvest question wording from.
Rejected: **HSY** — highest product value (~1.2M residents, most harvestable content) but costs
the whole TOC-entry rule with every downstream stage still unmeasured behind it. Rejected:
**Savo-Pielinen** — the one REVIEW-DEBT already names as the hypothetical, but same TOC cost plus
a document that bundles regulations with ~21 pages of justifications. Rejected: **Uudenmaan** —
bilingual, which is interesting product-wise and useless here since voikko is Finnish-only, and
mechanically the worst of the five.

**D2 — the authority key is `pirkanmaa`.** The authority's own name, *Alueellinen
jätehuoltolautakunta*, carries no geography and would not be unique in principle, so it cannot be
the slug. The key names the area; the `name` field carries the official name verbatim.
Rejected: `alueellinen-jatehuoltolautakunta` (unwieldy, and a generic name is a bad key).
Rejected: `tampere` — Tampere is the vastuukunta but only 1 of 17 municipalities, and naming an
authority after one member municipality is precisely the mistake ADR-0002 exists to prevent.

**D3 — the address keys on Voimaantulo; the edition is declared in the manifest and surfaced in
the citation.** `pirkanmaa@2021-07-01#15` stays the key: stable, no code change, no relabelling.
The manifest gains an `edition` field, asserted against the front-matter amendment list, and the
citation string carries it so a human reads *"Kunnalliset jätehuoltomääräykset, 1.5.2026 alkaen"*.
The honesty problem is fixed where it is actually read.
Rejected: **re-key to the latest amendment date** (`pirkanmaa@2025-10-22`,
`lounais-suomi@2025-10-22`) — the most honest addressing, and it would fully close the debt, but
it costs front-matter parsing plus relabelling all 21 existing questions and a re-baseline, spent
in the same slice that already needs 29 new labels. Hand-labelling is the one resource this
project cannot buy back. Rejected: **Voimaantulo alone, unchanged** — cheapest, and leaves the
2021 date quietly misleading every human who reads a citation.
**Cost accepted:** the address still cannot distinguish six editions of Pirkanmaa's text. The
content hash beside each chunk still detects drift, and re-confessing the escalation is part of
this slice's definition of done.

**D4 — Sastamala is omitted from the municipality map, and the omission is loud.** The manifest
lists 16 of the 17 municipalities. Sastamala gets an explicit comment naming the partial
coverage, and `resolve_municipality("Sastamala")` therefore raises the existing "no authority
covers this municipality" error rather than answering from rules that bind only part of the kunta.
No golden question uses Sastamala.
Rejected: **listing Sastamala** — makes the harness confidently wrong for most of the kunta's
residents, which is failure mode #1 with a correct-looking citation. Rejected: **modelling
sub-municipal coverage** — a real fix, and far out of scope; it needs a fourth level between
authority and municipality that nothing else in the design has.
**Cost accepted:** a resident of Mouhijärvi or Suodenniemi is refused an answer the regulations do
in fact give them. An honest refusal beats a confident wrong answer, and this is exactly the
trade `CONTEXT.md` already makes for taajama boundaries.

**D5 — the definitions carve-out learns bulleted lists. Nothing else in the extractor changes.**
`_split_definitions` handles `• term …` items as definition units alongside blank-line-separated
paragraphs. The dot-leader TOC assumption and the Uudenmaan parser bugs are **confessed with
their evidence**, not fixed: the failure is a loud hard error with a good message, so it is
documented debt rather than a lurking bug, and building intake for authorities not chosen is
capability nobody can exercise (`ANTI-PATTERNS.md`, layer-only progress).
Rejected: generalising the TOC entry rule now (would make a third authority nearly free, and
today's reconnaissance is already paid for — but no golden question exercises it). Rejected:
hardening all five candidates (the wrapped-heading failure has an unmeasured tail; the honest
estimate is "unknown", not "small").

**D6 — ~50 questions total, 29 new.** Clears the N>=51 threshold for detecting a fix that closes
half the misses from the published cell. Rejected: **~85** — powered for the best cell too, so the
target would hold whichever cell becomes published, but it triples this slice's hand-labelling on
a guess about slice 5's effect size. Rejected: **~35** — clears only "closing *all* misses", and
leaves `DESIGN.md`'s target formally unmet.

**D7 — 8 paired questions (16 entries) + 13 Pirkanmaa-only.** Final: 29 Lounais-Suomi / 21
Pirkanmaa. A **paired question** is one question text labelled twice, once per authority, chosen
on topics where the rules genuinely differ *and* the vocabulary forks. Those 8 carry three jobs at
once: the filter verification, `DESIGN.md:96`'s missing "answer differs between authorities"
category (0 questions today), and the synonym measurement. All 29 deliberately avoid
biojäte/kompostointi, which is **11 of the current 21**, and deliberately target chunks outside
the **15 of 82** the set reaches today.
Rejected: 4 paired + 21 Pirkanmaa-only (even 25/25 split, better per-authority balance, thinner
base under the synonym finding). Rejected: 0 paired (fastest to label; leaves the category at
zero and the synonym gap unmeasured).

**D8 — no held-out slice yet.** Holding out 10 of 50 leaves a tuning set of 40 (d=5, p=0.062 —
just under the bar D6 was chosen to clear) and a held-out set of 10 that can **never** reach d=6
at any effect size. The trigger is recorded instead: carve one at **N≈85**. Meanwhile the
anti-fitting work is already done by two things that cost nothing — `harvested` phrasing, whose
wording is independent of the target chunk by construction, and the gated leakage metric.
Rejected: carve 10 now (honours `CLAUDE.md`'s held-out instruction literally, at the cost of the
power this slice exists to buy). Rejected: hold out Pirkanmaa entirely (sharpest generalisation
test, but forfeits the paired questions and with them the filter verification).

**D9 — the authority filter is asserted inside the eval, not only unit-tested.** Every question's
top-k is asserted to contain **zero** foreign-authority chunks, in `evaluate`, so it cannot be
skipped and cannot silently regress — the same pattern as `assert_lemma_vectors_populated`. Plus
an adversarial test that mislabels a question's municipality and proves the run goes red.
Note this verifies **retrieval-layer isolation**, not the refusal behaviour `CLAUDE.md` specifies
("ask with municipality B's filter set -> it must refuse"). Refusal needs an answering layer that
does not exist, so the hard-filter debt closes **PARTIAL**, never CLOSED (see D12).

**D10 — the harness reports its own power.** For each cell pair, `make eval` prints the discordant
count `d` and its exact McNemar p. The instrument states what it can and cannot resolve rather
than leaving a reader to assume a 0.048 delta means something.

**D11 — the published headline is pooled over both authorities, with a per-authority breakdown as
a diagnostic.** One headline over all 50 questions in the published cell — the only number
carrying the power D6 bought — with per-authority rows beneath it, exactly as per-chunk recall and
MRR already sit beneath complete-set recall. The README must state plainly that the number is
**not comparable** to the old 0.762 because the population changed, and name both N values.
Rejected: per-authority headlines only (most honest about heterogeneity; discards the pooled power
and neither row can register an improvement). Rejected: keep Lounais-Suomi as the headline
(preserves continuity with slices 1-3; permanently under-reports the corpus the harness covers).

**D12 — the published cell stays `snowball/0`.** Unchanged from slice 3. Moving it remains the
Owner's explicit decision with a deliberate re-baseline, and D6's table now attaches a concrete
cost to that move: the N target rises from ~51 to ~84.

## Pre-registered predictions

Fixed now, so the result cannot be reinterpreted afterwards. Scored honestly in a
**Measured result** section when this lands, refutations first.

1. **Pooled `snowball/0` complete-set recall falls to 0.60–0.72** (from 0.762 at N=21). Pirkanmaa's
   questions have had zero slices of implicit fitting; Lounais-Suomi's have had three.
2. **Pirkanmaa scores below Lounais-Suomi in every one of the 12 cells**, gap 0.05–0.20, for the
   same reason. If Pirkanmaa scores *higher*, the likeliest explanation is that its questions are
   easier than intended, and the leakage number per authority is where to look first.
3. **Zero-overlap misses return: 0 -> 3–8** in `lemma-reasm/1`, concentrated in the paired
   questions and attributable to the synonym fork. This is the strongest prediction here: if it is
   false, the vocabulary-fork argument for this slice was wrong and slice 5's rule below must not
   fire on it.
4. **The filter assertion passes on the first run.** The SQL is already correct
   (`db.py`, WHERE before ranking, no IDF). Its value is the *red* test, not the green one. A
   first-run failure would mean something worse than a filter bug — it would mean the address or
   the manifest resolution is wrong.
5. **Leakage moves in every cell for population reasons** and is re-baselined, never compared
   across populations. Direction is genuinely uncertain: harvested Pirkanmaa wording pushes it
   down, and 41 definitions rather than 32 push it up.
6. **The 82/32 Lounais-Suomi counts do not move** when the definitions carve-out learns bullets.
   If they do, the change is wrong, not the expectation.

## Decision rule for slice 5

Fixed now, before the numbers exist:

- **>= 4 synonym-caused zero-overlap misses -> slice 5 is the vector layer.** Embeddings address
  synonymy; no analyser can. This is a cleaner mandate than slice 3's override could give, because
  the failure mechanism would then be measured rather than inferred.
- **< 4 -> the vector layer's case has weakened twice and must be re-argued from evidence, not
  from the plan.** A slice whose success cannot be measured is not a slice this project runs.
- **If prediction 2 is refuted** (Pirkanmaa scores *higher*), the golden set is the suspect, not
  the retriever, and slice 5 is a golden-set audit rather than any retrieval work.

## Acceptance criteria

Each is falsifiable and names how it will be proven. `/verify-live` fills a verdict **per
criterion**; the slice's verdict is the worst among them.

| # | Criterion | Proven by |
|---|---|---|
| AC1 | Pirkanmaa ingests: 48 clauses, chunk and definition counts matching a hand-read `expected` block | `make ingest` from a clean clone, exit 0, counts asserted by `ingest.py` |
| AC2 | Lounais-Suomi still produces exactly **82 chunks, 32 definitions** | same run; the manifest's existing `expected` block is unchanged |
| AC3 | `make eval` scores **50** questions in **12** cells and exits 0 | terminal output pasted, N stated on the table |
| AC4 | No question is skipped or errored; N on the table equals the golden set's length | `evaluate` has no skip path; a missing chunk address is a hard error |
| AC5 | Every question's top-k contains **zero** foreign-authority chunks | asserted in `evaluate`, and the assertion **seen red** by mislabelling a municipality |
| AC6 | The 8 paired questions retrieve *different* required chunks per authority from identical question text | per-question pass matrix, both entries visible |
| AC7 | The citation for a Pirkanmaa chunk names the **1.5.2026** edition, not 2021 | printed citation inspected in the eval output |
| AC8 | `resolve_municipality("Sastamala")` raises, with a message naming the partial coverage | unit test |
| AC9 | Per cell pair, `d` and its exact McNemar p are printed | eval output |
| AC10 | The gate fails on **any** cell regressing, and has been **seen red** on a deliberate break | drop a chunk; confirm non-zero exit and the named cells |
| AC11 | The README headline is pooled, N=50, with a per-authority breakdown and an explicit note that it is not comparable to 0.762 | README diff |
| AC12 | Every new label carries a `label_source` naming the clause and sentence it was read from, and no label was adjusted after seeing retriever output | hand audit, recorded in the spec's measured result |

## Non-goals

No embeddings, no pgvector, no custom Postgres image, no reranking, no weighted hybrid score, no
synonym or thesaurus layer, no LLM, no judge, no answer generation, no citations in an answer, no
refusal entries, no third authority, no TOC-entry generalisation, no Uudenmaan parser fixes, no
momentti-level modelling, no sub-municipal coverage model, no held-out slice, no CI, no Dockerfile,
no Cloud Run. `make docker-build` still exits non-zero on purpose.

The refusal path stays out for the same structural reason as before: a refusal entry needs
legitimately empty `required_chunks`, which `golden.py` rejects because an empty required set
scores a vacuous 1.0. That is correct until there is an answer to refuse.

## Definition of done

- All 12 acceptance criteria above have a verdict, filled by `/verify-live`, with pasted evidence.
- `eval/baseline.json` re-recorded deliberately at N=50, and the re-baseline is a **separate
  commit** from the code that changed the numbers.
- ADR-0006 records D3 with its rejected alternatives.
- **ADR-0002 gains an amendment note** for Sastamala: a municipality does not always resolve to
  exactly one authority. `CONTEXT.md`'s `Municipality` entry corrected to match.
- `CONTEXT.md` gains **Edition**, **Paired question**, **Vocabulary fork**, **Discordant pair**;
  **Document version** corrected, since its current wording is the ambiguity D3 resolves.
- `REVIEW-DEBT.md` gains: the dot-leader assumption with its measured evidence; the Uudenmaan
  parser bug; the address now covering six editions; Sastamala's partial coverage; and the hard
  filter recorded **PARTIAL**, not CLOSED.
- `specs/SPEC-slice-3-lemmatisation.md` and `CLAUDE.md` corrected where they justify this slice
  with the ±0.18 absolute interval instead of the paired test.
- `SPEC-slice-2-golden-set-rewrite.md` corrected: it claims the headline "should be expected to
  fall when the corpus grows, and the second authority roughly doubles it". It will not — the
  filter is applied before ranking and `ts_rank` has no IDF, so a second authority adds **zero**
  distractors to an existing question. That claim would otherwise be available later to excuse a
  drop that came from somewhere else.
- Predictions scored honestly in a **Measured result** section, refutations first.
- Gates green; `make eval` run from a genuinely clean clone into a fresh environment.

## Open questions

- **Sastamala refutes "a municipality has exactly one authority" (ADR-0002).** D4 handles this
  slice safely by omission, but the *model* is now known to be wrong in a way that will recur:
  Finnish municipal mergers leave former municipalities under different waste authorities. Whether
  the design eventually needs a level between authority and municipality is a real product
  question and it is the Owner's, not this spec's.
- **The `expected` counts are the one input that cannot be pre-verified.** They must be read by
  hand from the document after the bulleted-definitions fix exists. If the chunker's count
  disagrees with the document's own definition list, that is a stop-and-look — not a number to
  update until it matches.
- **Whether the published cell should move, now that its cost is quantified.** D12 keeps
  `snowball/0`. D6's table shows moving to `lemma-reasm/1` raises the N target from ~51 to ~84,
  which is a real argument for keeping the snowball headline that did not exist before this spec.
- **Pirkanmaa's harvestable question wording is unverified in volume.** `pjhoy.fi` and
  tampere.fi carry resident-facing pages, but whether they yield enough real questions to keep the
  `harvested` share at or above today's 6-of-21 is unknown until the labelling starts. If they do
  not, the honest move is fewer harvested questions recorded as such — never an `authored`
  question relabelled `harvested`.

---

## Measured result (27 Aug 2026)

Scored honestly against the pre-registered predictions above. **Refutations first.**
`N=50, k=5, 12 cells, 53 required chunks, 171 chunks over two authorities.`

### Refuted

**Prediction 3 — REFUTED, and it was the strongest prediction here.**
*Predicted:* zero-overlap misses return, 0 → 3–8 in `lemma-reasm/1`, concentrated in the paired
questions and attributable to the synonym fork.
*Measured:* **0.** Not 3, not 1 — zero-overlap misses stay at 0 in every `lemma-reasm` cell, and at
0 for Pirkanmaa in every lemma cell. The control cell's count rose 4 → 6 with the population, and
the reassembling analyser still absorbs all of it.

The vocabulary fork is **real** — `naapuruston-yhteiskerays` passes for Pirkanmaa (11 § at rank 1)
and fails for Lounais-Suomi in 10 of 12 cells, from *identical* question text — but it surfaces as
**ranked-out**, not as unreachable. The reasoning error is now obvious in hindsight: a question
shares plenty of *other* lexemes with its target even when the key noun shares no stem, so
"zero overlap" is a much weaker condition than "the synonym is bridged". In the Lounais-Suomi half
the top-5 even contains `2 § Määritelmät — Korttelikeräyksellä`, the *definition* of the very
concept, while the operative 8 § ranks below it: the concept is reached and the wrong chunk wins.

**This fires the spec's decision rule for slice 5: `< 4` synonym-caused zero-overlap misses, so the
vector layer's case has weakened twice and must be re-argued from evidence, not from the plan.**

**Prediction 2 — REFUTED as stated.**
*Predicted:* Pirkanmaa scores below Lounais-Suomi in **every one** of the 12 cells, gap 0.05–0.20.
*Measured:* below in **7 of 12**. Pirkanmaa scores *higher* in 5, including the best cell
(`lemma-reasm/0`: **0.857 vs 0.793**). Gaps run −0.110 to +0.154, and only 4 of 12 fall inside the
predicted band. In the published cell the prediction does hold (0.724 vs 0.619, gap +0.105).

The spec said: *"If Pirkanmaa scores higher, the likeliest explanation is that its questions are
easier than intended, and the leakage number per authority is where to look first."* Looked:
in `snowball/0`, leakage is **0.341 for Lounais-Suomi and 0.323 for Pirkanmaa** — Pirkanmaa's
questions are marginally *less* leaky, so the "easier questions" explanation is **not supported by
the metric the spec nominated to test it.** What the per-authority split does show is that the two
authorities respond differently to the analyser axis, which is a finding rather than a defect.

The spec's slice-5 rule for this case reads *"the golden set is the suspect, not the retriever, and
slice 5 is a golden-set audit rather than any retrieval work."* Both refutations now point away
from the vector layer, from different directions. **That is the Owner's call, not this spec's.**

**A slice-3 finding did not survive N=50, and this is the clearest thing the bigger set bought.**
Slice 3 concluded that dividing by document length costs the control and unsplit cells recall and
*gains* it for the reassembled one, and called that sign flip "the interaction the grid existed to
find". At N=50 the clean interaction is gone:

| analyser | norm 0 → norm 1 | slice 3 said | now |
|---|---|---|---|
| snowball | 0.680 → 0.640 | costs | **costs** ✓ |
| lemma-baseform | 0.740 → **0.780** | costs | **helps** ✗ |
| lemma-safe | 0.760 → 0.760 | costs | **neutral** ✗ |
| lemma-reasm | 0.820 → 0.820 | gains | **neutral** ✗ |

The slice-3 claim rested on a **one-question** gain at N=21 — d=3, p=0.25 — which was never a
result that instrument could resolve. The honest statement now is the narrow one: *length
normalisation costs the control cell and does not clearly help any lemma cell.* Not a better score;
the **retraction of a conclusion that was noise**. Pinned by
`test_length_normalisation_costs_only_the_control_cell_now`.

### Confirmed

**Prediction 1 — CONFIRMED.** Pooled `snowball/0` complete-set recall **0.680**, inside the
predicted 0.60–0.72 (from 0.762 at N=21).

**Prediction 4 — CONFIRMED.** The filter assertion passed on the first run, across all 50 questions
× 12 cells. Its value is the red test, and it was seen red by deleting the jurisdiction WHERE
clause; a companion test proves foreign chunks genuinely do enter the top-5 without it.

**Prediction 5 — CONFIRMED, and the uncertain direction resolved: leakage FELL in every cell.**
snowball 0.372 → **0.332**, baseform 0.506 → **0.442**, safe 0.568 → **0.506**, reasm 0.619 →
**0.550**. The 29 new questions are *less* leaky than the 21 they joined, so the golden set got
**harder**, not easier — the one direction that needs no excuse. Re-baselined per cell as always.

**Prediction 6 — CONFIRMED.** Lounais-Suomi still parses to exactly **82 chunks, 32 definitions**
after the definitions carve-out learned bullets.

### The result the slice existed to produce

At N=21 **no** comparison in the grid could reach p<0.05 at any effect size. At N=50:

| vs published `snowball/0` | d | favours it | favours published | exact p |
|---|---|---|---|---|
| **`lemma-reasm/0`** (0.820) | 9 | 8 | 1 | **0.039** ✓ |
| `lemma-reasm/1` (0.820) | 11 | 9 | 2 | 0.065 |
| `lemma-safe/1` (0.760) | 12 | 8 | 4 | 0.388 |
| `lemma-baseform/1` (0.780) | 11 | 8 | 3 | 0.227 |

**The instrument can now resolve a retrieval improvement.** That is what D6 was chosen to buy, and
it is the only thing on this page that could not have been obtained any other way.

**And the continuity is exact, which is what makes the new headline honest.** Computed over the
original 21 questions alone, `snowball/0` still scores **16/21** and `lemma-reasm/1` still
**18/21** — identical to the slice-3 baseline, not merely close. The pooled headline moved because
the *population* moved, and provably not because anything in slices 1–3 was disturbed. A second
authority adds **zero** distractors to an existing question: the filter runs before ranking and
`ts_rank` has no IDF. Pinned by
`test_the_original_21_questions_still_score_exactly_what_they_scored`.

### Published headline

At the time this slice landed: **0.680 (N=50, k=5) in `snowball/0`, at leakage 0.332**;
Lounais-Suomi 0.724 (N=29), Pirkanmaa 0.619 (N=21).

> **SUPERSEDED THE SAME DAY. D12 held `snowball/0`; the Owner moved the published cell to
> `lemma-reasm/0` once this slice's power result existed.** The headline is now **0.820 (N=50, k=5)
> at leakage 0.550** — Lounais-Suomi 0.793, Pirkanmaa 0.857. The decision, its four rejected
> alternatives and its two accepted costs are in
> `docs/adr/0007-the-published-headline-moves-to-lemma-reasm-0.md`. D12 is left as written: it was
> the right call *before* this slice measured the paired p-value, and editing it afterwards would
> hide the fact that the evidence changed the answer.
>
> Note what this does to the power table above: the N target for detecting a fix that closes half
> the remaining misses rises from ~51 to ~84, exactly as that table predicted moving the cell would
> cost. The golden set is now **underpowered by ~1.7x for its own published cell**, which is the
> strongest argument on the table for the next question-set tranche.

### Acceptance criteria

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| AC1 | Pirkanmaa ingests: 48 clauses, counts matching a hand-read `expected` | **MET** | `make ingest`, exit 0: 48 clauses / 89 chunks / 41 definitions; 41 definienda hand-read in strict alphabetical order |
| AC2 | Lounais-Suomi still produces exactly 82 chunks, 32 definitions | **MET** | same run; the `expected` block is unchanged |
| AC3 | `make eval` scores 50 questions in 12 cells and exits 0 | **MET** (after re-baseline) | table prints `golden set: 50 questions, 53 required chunks`; exit 0 |
| AC4 | No question skipped or errored; N equals the golden set's length | **MET** | `evaluate` has no skip path; 50 rows in the pass matrix |
| AC5 | Every question's top-k contains zero foreign-authority chunks | **MET** | asserted in `evaluate` for 50×12; seen red by deleting the WHERE clause — **not** by mislabelling a municipality, see the spec delta below |
| AC6 | The 8 paired questions retrieve different required chunks per authority from identical text | **MET** | enforced at load; `naapuruston-yhteiskerays` passes for one authority and fails for the other in the published cell |
| AC7 | A Pirkanmaa citation names the 1.5.2026 edition, not 2021 | **MET** | `11 § LÄHIKERÄYSJÄRJESTELMÄ (Kunnalliset jätehuoltomääräykset, 1.5.2026 alkaen)` |
| AC8 | `resolve_municipality("Sastamala")` raises, naming the partial coverage | **MET** | unit test, three casings |
| AC9 | Per cell pair, `d` and its exact McNemar p are printed | **MET** | two 12×12 triangles in the eval output |
| AC10 | The gate fails on any cell regressing, seen red on a deliberate break | **MET** | see below |
| AC11 | README headline pooled, N=50, per-authority breakdown, explicit not-comparable note | **MET** | README diff |
| AC12 | Every new label carries a `label_source`; no label adjusted after seeing retriever output | **MET** | 29 new entries, each quoting the clause and sentence; question text fixed before the target clause was looked up |

**Slice verdict: the worst of the above — MET.**

### Spec deltas

- **AC5's proposed red-proof does not work, and the correction matters.** The spec said to see the
  filter assertion red "by mislabelling a municipality". That is impossible:
  `golden._parse_question` already rejects a question whose municipality resolves to one authority
  while its labels point at another, so such a question never reaches `evaluate`; and if it did,
  the search would run against the wrong authority and return *that* authority's own chunks —
  every hit native, the assertion silent, the question merely a miss. The assertion defends against
  a regression in the **search**, not against a labelling error. Seen red by deleting the
  jurisdiction WHERE clause instead, with a companion test proving the hazard is real.
- **D4's "explicit comment" was not sufficient for AC8.** A YAML comment cannot reach an error
  message. The manifest gained a structured `partial_municipalities` field so the refusal can name
  the partial coverage, which is what AC8 demands.
- **A latent defect was surfaced and fixed, not deferred:** definition sub-key uniqueness was
  decided on raw words while the address is slugified, so Lounais-Suomi's `Kunnan` and Pirkanmaa's
  `kunnan` would both keep a one-word prefix and collide into one address. Now decided on the slug.
- **Four new confessions the spec did not anticipate**, all found by ingesting a second document:
  `18 a § KOMPOSTOINTI-ILMOITUS` is a real clause absent from its own table of contents and
  absorbed into 18 §'s chunk; two hyphen joins corrupt real words; 37 bare page-number lines
  survive in Pirkanmaa's body and none in Lounais-Suomi's. See `REVIEW-DEBT.md`.
- **Harvested share fell, as the open question anticipated:** 4 of the 29 new questions are
  harvested (all from `pjhoy.fi/ukk/`, verbatim from raw HTML), giving 10 of 50 overall against
  6 of 21 before. Neither the Pirkanmaa authority nor either operator publishes a resident FAQ with
  question-form headings on the non-biojäte topics this slice needed. **No authored question was
  relabelled `harvested`.**

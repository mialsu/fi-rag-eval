# SPEC — Slice 2: make the golden set honest, and make its honesty a metric

Written 27 Aug 2026, after slice 1 measured its own instrument. Weight: **Standard**.
Vocabulary in `CONTEXT.md`; decisions in ADR-0002/0003/0004.

## Why this is slice 2, and not the second authority

`specs/SPEC-slice-1-measurement-spine.md` lists slice 2 as "second authority and the filter's
proof". That order is superseded by the Owner's own guard-rail, which turned out to bind:

> **Explicit non-goal: Corpus breadth.** No municipalities beyond the handful chosen for format
> variety **until the existing ones' metrics are trustworthy**… dilutes a hand-labelled golden
> set you then have to redo. — `CLAUDE.md`

Slice 1's metrics were not trustworthy: 60% lexical leakage on 8 questions. Adding an authority
first would have meant hand-labelling a leaky set twice. The filter proof is deferred, not
dropped, and remains the reason slice 3 exists.

## Problem

Slice 1's headline (`complete-set recall@5 = 0.875`) was honestly computed and nearly useless.
The questions were written with the source PDF open, so they inherited its vocabulary. The
harness was easier than the task and — worse — **blind to the vocabulary gap it exists to
measure**: a resident's words never entered it, so no retrieval change could be shown to help
with them.

Leakage was diagnosed once, in a throwaway script. That is the wrong place for it. A property
the headline cannot be read without has to be computed on every run, or it drifts back.

## Solution shape

Two halves, and the first exists to judge the second.

### 1. Leakage becomes a first-class metric, gated in the opposite direction

**Lexical leakage** = the share of a question's stemmed content words that already appear in its
own `required_chunks`. Pure arithmetic over the index, no model, no cost.

`make eval` reports it beside the headline and per question. The baseline records it, and the
gate **fails if it rises** — every other metric is a score defended from falling; leakage is a
handicap defended from rising. A question edited to resemble its target raises the headline
while weakening the harness, and that is the one "improvement" this project must never accept.

The target is **not zero**. A resident asking about bio-waste says "biojäte" because that is
what it is called. The floor is empirical, established below.

### 2. The questions are rewritten, with provenance recorded per entry

Each entry declares `phrasing`:

- **`harvested`** — wording copied *verbatim* from a public resident-facing page written by the
  authority for residents, independent of any reading of the regulations. `phrasing_source`
  names the page and is **required**; the loader rejects the claim without it. These questions
  cannot be circular.
- **`authored`** — written for this set, under one rule derived from the harvested sample:
  *name the thing with the document's noun, ask with a person's verb.*

Labels stay hand-written from the source with a `label_source` per entry. Question text is
frozen **before** the target clause is looked up, so phrasing cannot be fitted to it.

## The calibration that set the target

Six questions harvested verbatim from LSJH's own resident-facing pages, labelled by hand, then
measured against slice 1's authored set:

| Question set | Lexical leakage |
|---|---|
| Harvested (real, resident-facing) | **39%** |
| Slice 1, authored with the PDF open | **60%** (worst entries 78%, 80%) |

*Which* stems leak is the actionable half. Real questions leak the **topic noun** (`biojät`,
`kompostor`) and keep question words and everyday verbs clean (`mite`, `tule`, `paka`, `aloit`,
`val`). Slice 1's questions leaked the **statutory register** — `tyhjennettäv`, `ilmoitettav`,
`siirrettäv`, `enin`: passive participles lifted out of the text. Hence the authoring rule, and
hence ~40% as the floor rather than 0%.

## Measured result — 27 Aug 2026

21 questions (6 harvested, 15 authored), 24 required chunks, 3 spanning more than one chunk,
`k=5`, €0. Reproduce with `make eval`.

| Metric | Slice 1 (N=8) | Slice 2 (N=21) |
|---|---|---|
| complete-set recall@5 (headline) | 0.875 | **0.762** |
| per-chunk recall@5 | 0.900 | 0.750 |
| MRR | 0.812 | **0.517** |
| **lexical leakage** | **0.596** | **0.372** |
| misses: zero-overlap / ranked-out | 0 / 1 | **4 / 2** |

Leakage now sits *below* the harvested reference of 0.39. MRR fell furthest, which is the honest
signal: the right chunk is frequently retrieved but rarely first.

### The gate caught the exact failure it was built for

Reverting **one** question from `Kuinka usein biojäteastia tyhjennetään kesällä?` back to slice
1's `Kuinka usein biojäteastia on tyhjennettävä kesäaikana?`:

```
complete-set recall@5   0.762 -> 0.810     (looks like an improvement)
lexical leakage         0.372 -> 0.397
REGRESSION — lexical leakage rose from 0.372 to 0.397 — the golden set got
             easier, which inflates every score above it            exit 1
```

A change that raises the headline while weakening the instrument, refused automatically. This is
the project's thesis reduced to one command.

### Pre-registered claim 1 is now confirmed

Slice 1 predicted *"most misses will be zero-overlap, not ranked-out"* and could not test it —
one miss has no power. On the rewritten set: **4 of 6 misses are zero-overlap.** Claim confirmed,
and the decision rule fires: **slice 3 is lemmatisation, not a BM25 extension.**

The four zero-overlap misses decompose into four distinct, separately-fixable causes:

| Cause | Evidence | What fixes it |
|---|---|---|
| The stemmer disagrees with itself about one word | query `biojäteastia` → `biojäteast`; corpus `biojäteastiaan` → `biojäteastia` | lemmatisation |
| Compound first element unreachable | `kesällä` → `kesä` vs `kesäaikana` → `kesäaik`; `määräyksistä` vs `jätehuoltomääräyksistä` | compound splitting (written as `dict_voikko`; **corrected 27 Aug 2026** — voikko in Python, ADR-0005. Measured in slice 3: `kesä` needs the conservative split, `määräys` needs the reassembling one) |
| Verb forms stem apart | `tyhjennetään` → `tyhjen` vs `tyhjennettävä` → `tyhjennettäv` vs `tyhjennysväli` → `tyhjennysväl` | lemmatisation |
| Genuine vocabulary gap | `taloyhtiö`, `asunto`, `keskusta` appear nowhere in the corpus | **embeddings** — no stemmer reaches these |

The first three are one intervention. The fourth is the first *evidence-based* argument for the
vector layer in this project; until now it was an assumption in `DESIGN.md`. Both are pinned by
tests so they cannot regress silently.

The 2 ranked-out misses are both short chunks (25 §, a 2 § definition) losing to long ones —
slice 1's `ts_rank` normalisation finding, unchanged.

### Why the headline is still above the original 0.25–0.50 prediction

The corpus is 82 chunks, so top-5 covers 6% of it. That was the "Up" force in slice 1's
prediction table and it is now the dominant remaining explanation. **This number should be
expected to fall when the corpus grows**, and the second authority roughly doubles it. A
retrieval score over an 82-chunk corpus is not comparable to any published benchmark.

> **CORRECTED 27 Aug 2026 (slice 4). The second half of that claim is simply false, and leaving it
> standing would have been dangerous.** A second authority adds **exactly zero** distractors to an
> existing question: `db.search` applies the authority filter in the WHERE clause *before* ranking,
> and `ts_rank` has no inverse document frequency, so nothing about another authority's 89 chunks
> can reach or reweight a Lounais-Suomi query. **Measured:** with Pirkanmaa ingested and the
> question set untouched, all 12 cells scored **identically** to the recorded N=21 baseline, to
> every decimal, and the gate stayed green. Over the original 21 questions the numbers are still
> exactly 16/21 and 18/21 at N=50.
>
> The headline *did* fall, 0.762 → 0.680, and it fell **entirely because the population changed** —
> 29 harder, less leaky questions joined it. This corrected claim would otherwise have been
> available later to excuse a drop that came from somewhere else, which is precisely the kind of
> ready-made excuse this project cannot afford. The first sentence stands: a score over a small
> corpus is not comparable to a published benchmark.

## Non-goals

Unchanged from slice 1, plus: no second authority, no lemmatisation, no `ts_rank` normalisation
change, no refusal entries. Refusal entries need `required_chunks` to be legitimately empty,
which the harness currently rejects on purpose; the first real candidate is already in hand —
LSJH's own *"Miten kompostorin saa toimimaan?"*, which the regulations genuinely do not answer.

## Open questions

- **50 questions vs 21.** `DESIGN.md` asks for ~50. 21 is enough to move the diagnostic from
  "no power" to "confirmed", which was the point. The next tranche is better written against
  two authorities, so it rides with slice 3 or 4.
- **Leakage understates itself where the stemmer fails.** It is measured post-stemming, so a
  word the query and corpus share but stem apart (`biojäteastia`/`biojäteastiaan`) counts as
  *clean* when a human eye sees the same word. Leakage will therefore **rise** when
  lemmatisation lands — through no change to the questions. The gate will fire, correctly, and
  the baseline must be re-recorded deliberately with that reason stated.
- **Short questions make leakage unstable.** *"Mikä on taajama?"* stems to one content word,
  which is in its target, so it reads as 100% leakage. Per-question leakage below ~4 stems is
  not meaningful; the micro-average is.

# SPEC — slice 3: lemmatisation, measured as a grid

**Status:** **built 27 Aug 2026.** Shaped, then corrected against measurement — see
**Measured result** at the end, which scores the predictions below honestly, refutations first.
**Weight:** Standard.
**Decided by measurement, not judgement:** slice 2's miss diagnostic returned 4 of 6 misses
zero-overlap, and slice 1's pre-registered decision rule points that at lemmatisation rather
than a BM25 extension (`specs/SPEC-slice-1-measurement-spine.md:89-92`).

## The correction that shaped this slice

Every prior doc in this repo names the mechanism as **`dict_voikko`**. It does not exist here.
Verified against the running container, not from memory:

```
pg_available_extensions ~ voikko|dict|hunspell  ->  dict_int, dict_xsyn, pg_trgm, unaccent
pg_ts_template                                  ->  ispell, simple, snowball, synonym, thesaurus
/usr/local/lib/postgresql/                      ->  dict_snowball.so, dict_int.so, dict_xsyn.so
apk search voikko | libvoikko                   ->  (empty)
apk search hunspell | grep -- -fi               ->  no Finnish dictionary in Alpine
```

`postgres:17-alpine` cannot lemmatise Finnish, and no packaged Postgres voikko dictionary was
found to install. The slice is therefore architecturally different from what was written down.
`REVIEW-DEBT.md`, `CLAUDE.md` and both prior specs must be corrected when this lands — they
currently name an approach that is not available.

## What voikko actually gives us

`libvoikko` (PyPI, binding the host's `libvoikko.so.1` 4.3.2 + `voikko-fi` 2.5) returns per word
a `BASEFORM` and a `WORDBASES` morph decomposition, plus its own tokeniser. Measured on the exact
pairs behind the four zero-overlap misses:

| Failing pair | BASEFORM | match? | WORDBASES | match? |
| --- | --- | --- | --- | --- |
| `biojäteastia` / `biojäteastiaan` | `biojäteastia` / `biojäteastia` | **yes** | — | — |
| `kesällä` / `kesäaikana` | `kesä` / `kesäaika` | no | `kesä` / `kesä`+`aika` | **yes** |
| `määräyksistä` / `jätehuoltomääräyksistä` | `määräys` / `jätehuoltomääräys` | no | `määrä`+`ys` / `jäte`+`huolto`+`määrä`+`ys` | **only after affix reassembly** |
| `tyhjennetään` / `tyhjennettävä` | `tyhjentää` / `tyhjennettävä` | no | shared derivation base `(tyhjetä)` | out of scope |
| `taloyhtiö`, `asunto`, `keskusta` | lemmatise cleanly | — | — | **no — absent from the corpus** |

Three consequences, each of which changed a decision below:

1. **"Lemmatisation" is two features, not one.** BASEFORM fixes the stemmer-disagrees-with-itself
   cause. Causes 2 and 3 need compound decomposition.
2. **`WORDBASES` yields morphs, not words.** `+määrä(määrätä)+ys(+ys)` must have its derivational
   affix folded back on to produce `määräys`; taking surface segments raw yields `määrä` — which
   means *quantity*, not *regulation*, and would make "kuinka suuri määrä" match regulation
   clauses. A conservative rule that splits only when every segment carries a real base invents
   nothing but leaves `#48` unfixed.
3. **Cause 4 is confirmed dead, not suspected.** `keskusta` even lemmatises ambiguously to
   `keskus`, which *does* occur in this corpus in the wrong sense.

## The misses this slice is aimed at

From the live run at `b04bdbd` (16 of 21 pass, 0.762):

| Failing question | Missed | Kind | Cause | Fixed by |
| --- | --- | --- | --- | --- |
| `biojateastian-tyhjennys-kesalla` | `#26` | zero-overlap | `kesällä`/`kesäaikana` | BASEFORM + conservative split |
| `poikkeus-maarayksista` | `#48` | zero-overlap | `määräyksistä`/`jätehuoltomääräyksistä` | reassembled split only |
| `taloyhtio-kolme-asuntoa-biojate` | `#13`, `#15` | zero-overlap x2 | vocabulary absent | **nothing lexical** |
| `miksi-biojatteet-pakataan` | `#25` | ranked-out | short chunk vs long | `ts_rank` normalisation |
| `biojate-mita-tarkoittaa` | `#2.biojatteella` | ranked-out | short definition chunk | `ts_rank` normalisation |

## Decisions

Each was put to the Owner with alternatives; the rejected ones are recorded because a decision
without its alternatives is unreviewable. **D1 and D3 are ADR-worthy** and land as ADR-0005.

**D1 — lemmatisation runs in Python, Postgres stays stock.**
> **NARROWED DURING BUILD, in the safe direction.** The cost below says `tsv` can no longer be a
> generated column. It can: only the three *lemma* columns need the application to write them, so
> `tsv` was left `GENERATED ALWAYS AS` and the published cell keeps its database-enforced
> invariant. The three written columns get `NOT NULL DEFAULT ''::tsvector` plus a positive
> assertion that every chunk has a non-empty index in every column — checked at ingest **and**
> again at the start of every eval, because an empty lemma index would score as a retrieval miss
> and be blamed on the analyser.
Rejected: a custom Debian Postgres image with a voikko text-search dictionary built from source
(no packaged extension found; the image becomes ours to maintain and `docker compose up` gains a
build step, touching the clean-clone reproducibility the README claims). Rejected: `pg_trgm`
only (available today, zero deps, but morphology-blind and cannot split compounds — likely fixes
cause 1 and nothing else). **Cost accepted:** `tsv` can no longer be a generated column, so the
application writes the index and a row inserted outside the app has an empty one. That is a
database-enforced invariant given up, and it is the main thing D1 pays.

**D2 — the lemmatiser is voikko.** Not a preference: nothing else consulted produces a morph
decomposition at all, and it is already present on the host and installable from PyPI.

**D3 — the snowball index stays alongside, and the analyser is a selectable dimension.**
Four `tsvector` columns, each GIN-indexed (82 chunks — size is irrelevant here):
`tsv` (finnish snowball, existing), `lemma_base_tsv`, `lemma_safe_tsv`, `lemma_reasm_tsv`.
Rejected: replacing snowball outright (loses per-question comparison inside one run, and makes
leakage unmeasurable under the old analyser). Rejected: a weighted hybrid score — `w` would be
tuned on the same 21 questions it is scored on, with no held-out slice, which is the overfitting
surface `CLAUDE.md` explicitly warns about. **No blend weight means no knob to overfit.**

**D4 — build both splits and let the number choose.** `lemma_safe_tsv` splits only where every
`WORDBASES` segment carries a real base. `lemma_reasm_tsv` folds derivational affixes back onto
the preceding word part and merges bound prefixes forward. The reassembler is TDD'd as its own
seam with the corpus's own vocabulary as fixtures. **It must beat the conservative config on
measurement or it is deleted, not tuned.**

**D5 — `ts_rank` normalisation is the grid's second axis**, not a following slice.
> **CORRECTED DURING BUILD.** This decision named normalisation **32**. That was the wrong flag:
> Postgres documents it as "divides the rank by itself + 1" — `rank / (rank + 1)`, a strictly
> monotonic rescale that **cannot reorder a single result**. The first run of the grid scored all
> eight cells identically at 0 and at 32, to three decimals, with an identical pass matrix, which
> is what sent us back to the manual. The flags that divide by document length are **1** (by
> `1 + log(length)`) and **2** (by `length`). The axis is now `{0, 1, 2}` — **12 cells, not 8** —
> which follows D4's already-approved discipline of measuring both candidates rather than picking
> one. Pinned by `test_normalisation_32_cannot_reorder_anything` so the arithmetic reason is on
> the record and not just the empirical one.
Compound splitting inflates lexemes per chunk, and normalisation 0 rewards accumulated term
weight, so the two changes interact; sequential slices would confound exactly the interaction we
need to see. 4 analysers x {norm 0, norm 32} = 8 cells, one extra query argument, no model cost.
Rejected: excluding it (interaction never observed, and unrecoverable after the fact). Rejected:
applying norm=32 everywhere (discards the only number currently trusted, and every analyser
delta is then measured against a moving floor).

**D6 — the ceiling is accepted.** `#13`/`#15` stays red in all eight cells. pgvector is absent
from the stock image too, an embedding model is the project's first paid run, and **the Owner's
cost ceiling still has no number** — so `CLAUDE.md` binds: ask before any paid run. A second
retrieval mechanism would also confound this slice's measurement. Rejected: a harvested synonym
layer — defensible under the same provenance discipline as the golden set (synonyms from LSJH's
own pages, never from the failing questions), but still a second mechanism in one slice, and a
synonym list built while looking at your own misses is the leakage failure mode wearing a
different hat.

**D7 — the baseline records every cell, and any cell regressing fails the gate.**
Each cell is compared only against itself. **This closes the "leakage will rise and trip the
gate" debt by construction rather than waiving it** — comparing the lemma cell's leakage against
the lemma cell's own reference compares like with like. The harness is fully deterministic
(fixed corpus, fixed queries, no model, no sampling), so ~32 gated values carry no
false-alarm risk from variance. Rejected: gating one cell only (seven cells could regress
silently, and the gate would go green trivially this slice — decoration).

**D8 — an analyser fingerprint is gated.** `libvoikko` exposes the *library* version (4.3.2) but
**not the dictionary version** — `voikko-fi 2.5` is visible only through `dpkg`. A dictionary
upgrade would therefore move every published number with no code change, which is precisely what
this project must never allow. The harness hashes the lemmas it produces for a committed probe
word list and stores that in `baseline.json`; a mismatch is a hard error naming the fix. This is
the same discipline the corpus `sha256` already applies to the PDF. Rejected: pinning the library
version (pins the wrong component). Rejected: a Dockerfile for the whole harness (M3 scope, and
rewrites every make target).

**D9 — all readings, minus proper-noun readings of lowercase words.** 10.8% of the corpus's 2,389
unique word forms have more than one baseform, and the ambiguity is mostly proper-noun junk:
`aina`->`Aina`|`aina`, `akut`->`Aku`|`akku`, `asukas`->`Asukas`|`asukas`. Dropping a capitalised
baseform when the surface word was lowercase removes that class on a principled rule; genuine
ambiguity (`ajan`->`aika`|`ajaa`) keeps both readings, which is what a retrieval index normally
does. Rejected: first reading only — voikko's ordering is not documented as ranked, so this can
silently index `Aku` for `akut`, and the failure mode is invisible, exactly like the
double-stemming bug.

**D11 — the lemma analysers stop on exactly the words snowball stops on.** Decided during the
build, not in shaping, and it is the one decision that could have invalidated the whole grid.
Snowball discards `mitä`, `on`, `ja`, `olla`; a lemmatiser given no stop list keeps them. The lemma
cells would then have indexed and queried a word present in nearly every clause, and every
cell-to-cell delta would have been lemmatisation **plus** the absence of stopping — two variables,
one number. The decision is borrowed rather than invented: the harness asks *Postgres* which
surface tokens the `finnish` configuration throws away, so the stopping decision is literally the
same one, and the only thing differing between cells is how a kept word is normalised. Rejected: a
vendored word list (drifts from the configuration it is meant to mirror). Rejected: no stopping
(the confound above). Confessed in `REVIEW-DEBT.md` — a surface-form list is not obviously right
for a lemma index, and it silently sets the leakage metric's denominator.

**D10 — unanalysable words fall back to the raw lowercased token.** 2.1% (51 forms) get no
analysis: `bokashilla`, `fermentoidaan`, `esim`, `840-1`, URLs. Without a fallback they vanish
from the index entirely, and `bokashi` is a composting method a resident would genuinely ask
about. Decided without consultation as the only non-destructive option; confessed here.

## Pre-registered predictions

Written before the code exists. Complete-set recall@5, N=21, k=5.

| Cell | Predicted | Mechanism |
| --- | --- | --- |
| `snowball/0` | **0.762** exactly | Control. If this moves, the harness is broken, not improved. |
| `lemma-baseform/0` | **0.762** | Cause 1 alone flips no *whole* question. |
| `lemma-safe/0` | **0.810** | Flips `#26` via `kesä`. |
| `lemma-reasm/0` | **0.857** | Flips `#26` and `#48`. |
| `snowball/32` | **0.857** | Flips `#25` and `#2.biojatteella`. |
| `lemma-reasm/32` | **0.952** | Both mechanisms; the ceiling. |
| every cell | `#13`/`#15` red | No lexical method reaches `taloyhtiö`/`asunto`/`keskusta`. |

Two further claims, stated so they can fail:

- **Leakage rises in the lemma cells**, 0.372 -> predicted **0.42–0.48**, through no change to
  any question — words that stemmed apart now match. Per-cell baselines absorb this correctly.
- **The interaction is positive:** norm=32 buys *more* in the split cells than in the baseform
  cell, because splitting inflates lexeme counts and worsens the unnormalised long-chunk bias.
  This claim is the entire justification for D5's grid; if it is false, the grid was unnecessary
  and a note saying so is the honest outcome.

## Decision rule for slice 4

Fixed now, so the result cannot be reinterpreted after the fact:

- `reasm` beats `safe` by **>= 1 question** -> the reassembler earns its place. Otherwise
  **delete it**, do not tune it.
- Best cell **<= 0.857** with `#48` still red -> the compound diagnosis is wrong. Re-diagnose
  before spending anything on embeddings.
- norm=32 fails to flip `#25` and `#2.biojatteella` -> slice 1's normalisation finding was wrong,
  which is a larger result than this slice and is written up as such.
- Regardless of outcome, **slice 4 is the vector layer for `#13`/`#15`**, which is now the only
  remaining proven-unreachable class. It needs a cost-ceiling number from the Owner first.

## Non-goals

No embeddings, no pgvector, no custom Postgres image, no synonym or thesaurus layer, no weighted
hybrid score, no second authority, no new golden-set questions, no refusal entries, no LLM, no
judge, no answer generation, no CI, no Dockerfile. The authority hard filter remains unverified
for the same reason as before: one authority, nothing to leak from.

## Definition of done

- `make eval` prints all eight cells with all four metrics and the miss breakdown, exits 0.
- `eval/baseline.json` holds per-cell references plus the analyser fingerprint; **any** cell
  regressing fails the gate, and the gate has been **seen red** on a deliberate break.
- The fingerprint gate has been seen red by perturbing the probe output.
- Predictions above are scored honestly in a "Measured result" section, refutations included.
- New system deps (`libvoikko1`, `voikko-fi`) documented in the README beside `poppler-utils`,
  and a missing dictionary produces a helpful stderr message and a non-zero exit, not a silent
  collapse to raw tokens.
- `REVIEW-DEBT.md`, `CLAUDE.md`, and both prior specs corrected where they name `dict_voikko`.
- ADR-0005 records D1 and D3 with their rejected alternatives.
- Gates green; `make eval` run from a clean clone.

## Open questions

- **Which cell becomes the published headline.** The gate covers all eight; the README publishes
  one. Moving it off `snowball/0` is the Owner's explicit decision at the end of this slice, with
  a deliberate re-baseline — not something the winning number does automatically.
- **The derivation-base cause (`tyhjennetään`/`tyhjennettävä`) is left unfixed.** Linking them
  needs the parenthesised base `(tyhjetä)`, which also links `tyhjennysväli` — conflating
  "emptying interval" with "to become empty". Out of scope; revisit only if a question demands it.
- **The reassembler is a hand-rolled linguistic component.** Its bugs are silent: junk lexemes
  lower precision, which surfaces as *other* questions regressing, not the one it targeted. Its
  first draft produced `'tyhjentää)tävä'` and left bound prefixes standing alone. D4's
  measure-both rule is the mitigation; the fixture set is the other half.
- **N is still 21**, and one question flipping moves the headline by ~0.048. Every predicted
  delta in this spec is one or two questions wide, which is inside the +/-0.18 interval. The
  mechanisms are what is being tested; the aggregate is a summary, not the evidence.

---

## Measured result (27 Aug 2026)

One `make eval` run at 12 cells, N=21, k=5, on the corpus pinned by `corpus/manifest.yaml`.
Analyser: voikko library 4.3.2, fingerprint `9117b2f347e4c331` over 28 probe words. €0.

### The predictions, scored

Refutations first, because they are the part worth reading.

| Cell | Predicted | Measured | |
| --- | --- | --- | --- |
| `snowball/0` | 0.762 exactly | **0.762** | ✅ control held to every decimal |
| `lemma-baseform/0` | 0.762 | **0.762** | ✅ number right, **mechanism wrong** — see below |
| `lemma-safe/0` | 0.810 | **0.810** | ✅ flipped `#26` via `kesä`, exactly as claimed |
| `lemma-reasm/0` | 0.857 | **0.810** | ❌ `#48` became *reachable* but not retrieved |
| `snowball/32` | 0.857 | **0.762** | ❌ the flag cannot reorder anything (D5, corrected) |
| `lemma-reasm/32` | 0.952 | **0.810** | ❌ same cause |
| every cell | `#13`/`#15` red | red in all 12 | ✅ — but as a *ranking* failure, not a reach failure |
| leakage in lemma cells | 0.42–0.48 | **0.506 / 0.568 / 0.619** | ❌ rose far more than predicted |
| the interaction is positive | — | **confirmed, with a sign flip** | ✅ the grid's whole justification |

**"Cause 1 alone flips no whole question" was right about the number and wrong about the
mechanism.** `lemma-baseform/0` scores 0.762 because it *wins* `miksi-biojatteet-pakataan` and
*loses* `kerata-vai-kompostoida`. A no-op and a wash are different findings, and only the
per-question matrix distinguishes them. This is why the report prints one.

**`#48` refuted the prediction in an informative direction.** `määräyksistä` → `määräys` does now
match `jätehuoltomääräyksistä`, exactly as designed — the miss simply moved from `zero-overlap` to
`ranked-out`. The morphology worked and the ranking lost, which is a different fix. Paired with
length normalisation (`lemma-reasm/1`) it retrieves at position 2. So the compound diagnosis was
right and the prediction understated what it took to act on it.

**The interaction is the result.** Length normalisation costs `snowball` **0.143**, costs
`lemma-baseform` 0.048, costs `lemma-safe` 0.048 — and *gains* `lemma-reasm` **0.048**. The sign
flips. Splitting inflates the lexemes per chunk, which is exactly what unnormalised `ts_rank`
over-rewards. A sequential pair of slices would have measured "length normalisation is harmful",
banked that, and never reached the best cell. This is the one claim that justified building a grid
instead of two slices, and it held.

### The best cell

`lemma-reasm/1` — **0.857** complete-set recall, 0.833 per-chunk, 0.614 MRR, 0.619 leakage,
**0 zero-overlap misses**, 4 ranked-out. Every remaining miss is reachable and lost in the ranking.

### Against the pre-registered decision rule

- **`reasm` beats `safe` by ≥ 1 question → the reassembler earns its place.** Best reasm cell 0.857
  vs best safe cell 0.810 = exactly one question. **It stays**, and it is measured against the
  conservative split on every run so the rule can still fire in the other direction later.
- **Best cell ≤ 0.857 with `#48` red → the compound diagnosis is wrong.** Best cell is 0.857 and
  `#48` is **green** in it. The diagnosis holds; no re-diagnosis needed.
- **norm=32 fails to flip `#25` and `#2.biojatteella` → slice 1's normalisation finding was wrong.**
  **This inference does not apply**, and saying so is the honest reading. The rule assumed the flag
  tested the hypothesis. It does not. Slice 1's finding is *confirmed* by the flags that do — both
  1 and 2 put the missed definition chunk into the top 5 of the very query that missed it — and it
  is also more expensive than slice 1 implied, costing the control cell recall overall. A
  pre-registered rule protects against reinterpreting a *result*; it cannot protect against a
  mis-specified test, and pretending otherwise would be worse than admitting the flag was wrong.
- **Slice 4 is the vector layer for `#13`/`#15`.** **OVERRIDDEN BY THE OWNER, 27 Aug 2026.** The
  argument for the vector layer got *better* — those clauses are no longer lexically unreachable,
  they are lexically *weightless* — but the argument for doing it **next** got worse, and the rule
  did not anticipate that. Two facts this slice produced and the rule was written before:
  every remaining miss is now a ranking failure rather than a reach failure, and at N=21 the
  2-question gain the vector layer is predicted to buy (0.095) sits **inside** the ±0.18 interval.
  A slice whose success cannot be measured is not a slice this project should run. Slice 4 is
  therefore the golden set plus a second authority — which also closes the authority hard filter,
  the design's #1 failure mode and still 100% unverified — and the vector layer becomes slice 5.
  Recorded here rather than only in `CLAUDE.md` so the rule and its override sit together: a
  pre-registered rule that gets quietly ignored is worse than one that was never written.

### Also measured

- **Index size** (total lexemes, 82 chunks): snowball 3,799 · baseform 3,909 (1.03×) · safe 4,558
  (1.20×) · reasm 5,077 (1.34×). The inflation the interaction runs on, quantified.
- **Corpus vocabulary:** 6,441 word tokens (1,148 stopped), 2,513 distinct forms, **55 (2.2%)**
  with no analysis at all — indexed by their raw surface token (D10).
- **Reassembler junk:** 76 of 2,513 forms produce at least one part voikko cannot itself analyse
  as a word (`peräinen`, `pisteinen`, `kiinteis`). Mostly voikko's own `-inen` over-analysis,
  arriving as a second reading and kept under D9. Confessed.
- **Gates seen red**, each by a deliberate break: a crippled `lemma_reasm_tsv` on one chunk (named
  both affected cells and left the other ten green — which is the per-cell design working, since a
  single-cell gate would have missed it entirely); a perturbed analyser fingerprint; a pre-slice-3
  baseline; an unmeasured normalisation argument. The missing-dictionary path is proven by unit
  test rather than by uninstalling the Owner's system package.

### Still open

- **Which cell is the published headline.** Unchanged at `snowball/0`, and the README says why.
  This is the Owner's decision and it carries a deliberate re-baseline.
- N is still 21. Every delta in this slice is one or two questions wide, inside the ±0.18 interval.
  The mechanisms are the evidence; the aggregate is a summary.
- The derivation-base cause (`tyhjennetään`/`tyhjennettävä`) is still unfixed and no longer costs
  anything measurable — it was never the reason a question failed.

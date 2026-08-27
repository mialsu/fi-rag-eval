# ADR-0005 — Lemmatisation in Python, and the analyser as a measured dimension

- **Date:** 2026-08-27
- **Status:** accepted

## Context

Slice 2 measured **4 of 6 retrieval misses as zero-overlap** — a required chunk sharing no stemmed
token at all with the question it answers. That is not a ranking problem, and slice 1's
pre-registered decision rule (`specs/SPEC-slice-1-measurement-spine.md:89-92`) points it at
lemmatisation rather than at a BM25 extension.

Every document in this repo written before this date names the mechanism as **`dict_voikko`**, a
Postgres text-search dictionary. **It does not exist here.** Verified against the running
container rather than recalled:

```
pg_available_extensions ~ voikko|dict|hunspell  ->  dict_int, dict_xsyn, pg_trgm, unaccent
pg_ts_template                                  ->  ispell, simple, snowball, synonym, thesaurus
/usr/local/lib/postgresql/                      ->  dict_snowball.so, dict_int.so, dict_xsyn.so
apk search voikko | libvoikko                   ->  (empty)
apk search hunspell | grep -- -fi               ->  no Finnish dictionary in Alpine
```

`postgres:17-alpine` cannot lemmatise Finnish, and no packaged Postgres voikko dictionary was
found to install. So the mechanism had to be chosen again, from facts.

What voikko does offer, through the `libvoikko` PyPI binding to the host's `libvoikko.so.1` plus
the `voikko-fi` dictionary, is two things per word: a **`BASEFORM`** (the lemma) and a
**`WORDBASES`** morph decomposition. Measured on the exact failing pairs, those are two different
features fixing two different causes — `BASEFORM` joins `biojäteastia`/`biojäteastiaan`, and only
a decomposition joins `kesällä`/`kesäaikana` or `määräyksistä`/`jätehuoltomääräyksistä`.

One further fact shaped the whole design: **`libvoikko` exposes the library version but not the
dictionary version.** It is the dictionary that decides the numbers, so without a further
mechanism a `voikko-fi` upgrade would move every published metric with no code change — which is
the one thing this project must never allow.

## Decision

Three coupled decisions, recorded together because each only makes sense given the others.

1. **Lemmatisation runs in Python; Postgres stays stock.** `analyse.py` tokenises and analyses
   with voikko and produces `tsvector` literals; Postgres indexes and ranks them. The image in
   `compose.yaml` is unchanged.

2. **The analyser is a *dimension of the measurement*, not a replacement.** Four `tsvector`
   columns, each GIN-indexed: `tsv` (the existing snowball control), `lemma_base_tsv`,
   `lemma_safe_tsv`, `lemma_reasm_tsv`. They **nest** — each adds exactly one mechanism to the one
   above it — so a delta between adjacent cells attributes to that mechanism and nothing else.
   Crossed with `ts_rank` normalisation, that is the grid `make eval` reports. There is **no blend
   weight**: a weight would be tuned on the same 21 questions it is scored on, with no held-out
   slice, which is the overfitting surface `CLAUDE.md` explicitly warns about. No knob, nothing to
   overfit.

3. **The analyser's behaviour is fingerprinted and gated.** The harness hashes the lemmas it
   produces for a committed probe word list and records that in `eval/baseline.json`; a mismatch
   fails the gate and names the fix. This is the same discipline the corpus `sha256` already
   applies to the source PDF — pin the *behaviour*, because that is what the numbers depend on.

## Rejected alternatives

- **A custom Debian Postgres image with a voikko text-search dictionary built from source** —
  rejected because no packaged extension was found, so the build becomes ours to maintain,
  `docker compose up` gains a compile step, and the clean-clone reproducibility the README claims
  is the first thing that breaks. The morphology is a small pure function; the container is not.
- **`pg_trgm` alone** — available today, zero new dependencies, and genuinely likely to fix the
  stemmer-disagrees-with-itself cause. Rejected because it is morphology-blind: trigram similarity
  cannot decompose a compound, so it addresses one of the three measured causes and leaves the two
  that produced most of the zero-overlap misses.
- **Replacing snowball outright** — rejected on measurement grounds, not sentiment. It would
  destroy per-question comparison inside a single run, and make leakage unmeasurable under the
  analyser every previously published number was computed with.
- **A weighted hybrid of the two indexes** — rejected as above: one free parameter, 21 questions,
  no held-out slice.
- **Pinning the `libvoikko` library version instead of fingerprinting** — rejected because it pins
  the wrong component. The library is versioned and visible; the dictionary is neither.
- **A Dockerfile for the whole harness**, which would pin the dictionary by construction —
  rejected as M3 scope: it rewrites every make target and is a deploy decision, not an analyser one.
- **A harvested synonym layer** (`taloyhtiö` → `kiinteistö`, from the authority's own pages) —
  defensible under the same provenance discipline as the golden set, and deferred rather than
  refused. Rejected *for this slice* because it is a second retrieval mechanism landing in the
  same measurement, and because a synonym list assembled while looking at your own misses is the
  golden-set leakage failure mode wearing a different hat.

## Consequences

**Easy.** The analyser is a pure Python seam, so the risky part of it — the compound reassembly
rule — is unit-testable against recorded `WORDBASES` strings with no database and no dictionary,
and those tests run in every `make gate`. Adding or removing an analyser is one enum member and
one column. Nothing about the container, the manifest or the chunker changes.

**Hard, and paid for knowingly.** The three lemma columns **cannot be `GENERATED`**, so the
application writes the index and a row inserted outside this ingest would have an empty one — a
database-enforced invariant given up. Mitigated, not solved: the columns default to the empty
`tsvector`, every chunk is asserted non-empty at ingest *and* at the start of every eval, and
ingestion is a full reload rather than incremental. `tsv` deliberately stays generated instead of
being demoted for symmetry, so the published cell keeps its invariant.

**To live with.** Two system packages (`libvoikko1`, `voikko-fi`) that `uv sync` cannot supply, so
a clean clone needs them and CI will have to install them or inherit a silent skip. The harness
refuses to run rather than falling back to raw tokens when the dictionary is missing, because a
number computed by a silently degraded analyser is worse than no number. And voikko is
MPL/GPL/LGPL tri-licensed and dynamically linked, which is worth knowing for an MIT repo even
though nothing is vendored here.

**What it makes measurable that was not.** The grid found an interaction that a sequential pair of
slices would have hidden: dividing `ts_rank` by document length *costs* the control cell recall and
*gains* it only in the compound-splitting cell. Measure both changes at once or conclude the
opposite of the truth.

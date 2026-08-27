# fi-rag-eval

Finnish-language document question answering over municipal waste regulations — built so that
**answer quality is measured, not asserted**.

> **Status: the harness runs; the pipeline it measures is lexical only.** `make eval`
> ingests one authority's regulations, retrieves with Postgres full-text search, scores a
> hand-labelled golden set across **12 retrieval configurations at once**, prints the tables
> below, and fails on regression in **any** of them. No embeddings, no reranker, no language
> model, no judge yet — those are the next slices.
>
> **Read the caveat under the table before quoting any number.**

## Why this exists

Getting a language model to answer from a pile of PDFs is a weekend's work. Knowing *how well* it
answers, and whether last week's change made it better or worse, is the part that decides whether a
system can go to production. This project treats the evaluation harness as the product and the RAG
pipeline as the thing being measured.

## The problem it solves

Finnish waste regulations (`jätehuoltomääräykset`) are issued by regional waste authorities, each
acting for many municipalities at once, on top of national waste law — Turku is one of eighteen
municipalities under a single board. Answering a resident's question — *"how often must the bio-waste
bin be emptied at a property in Turku?"* — means finding the right authority's document and then
reporting what the regulation actually says, which is conditional: it depends on whether the property
lies in a built-up area of over 10,000 inhabitants, how many dwellings it has, whether the household
composts, and what kind of bin it is. One of those facts is not even in the regulations — the area
boundaries live in a separate map service.

So the honest answer has branches and a citation on each, and the system has to know which facts it
cannot resolve. Keyword search does not do this, and an unmeasured chatbot cannot be trusted with it.

## What it will do

- Ingest and chunk public Finnish waste regulations and national waste law.
- Retrieve with a hybrid of lexical full-text and vector search, then rerank.
- Answer with inline citations — conditionally, one citation per branch — and **refuse** when the
  retrieved context doesn't support an answer.
- Score itself against a golden set on every pull request, and fail CI on regression.

## Measured quality

Every number here was computed by `make eval`, never typed in. A dash means the slice that
would compute it does not exist yet.

Retrieval: **lexical only** — Postgres `ts_rank`. The published cell is the `snowball/0`
control: `to_tsvector('finnish', ...)` at default normalisation. That is deliberately the weakest
sensible baseline, and it is **not BM25**: `ts_rank` has no inverse document frequency and, at its
default normalisation, no document-length normalisation either.

A better configuration is measured — see [What lemmatisation bought](#what-lemmatisation-bought)
— and is **not** what this table reports. Which cell is the published headline is a recorded
decision, not whichever one scored best today.

The headline is **pooled over both authorities in the corpus** — one number over all 50
questions, which is the only number carrying enough statistical power to detect an improvement
(see [Can this instrument tell?](#can-this-instrument-tell)). The per-authority rows beneath it are
diagnostics, not headlines of their own.

> **This is not comparable to the 0.762 previously published.** That was **N=21**, one authority.
> This is **N=50**, two. The population changed, so the two numbers measure different things.
> What *is* comparable: over the original 21 questions alone, this cell still scores exactly
> 16/21 = 0.762 — identical, not merely close. A second authority adds **zero** distractors to an
> existing question, because the authority filter runs before ranking and `ts_rank` has no IDF.
> The headline moved because the questions changed, and provably not because anything else did.

| Metric | Value | N | Notes |
| --- | --- | --- | --- |
| **Complete-set recall@5** | **0.680** | 50 questions | headline: did retrieval find *every* clause the answer depends on |
| — Lounais-Suomi | 0.724 | 29 questions | diagnostic. Three slices of implicit fitting behind it |
| — Pirkanmaa | 0.619 | 21 questions | diagnostic. Zero slices of fitting; questions are *less* leaky (0.323) |
| Per-chunk recall@5 | 0.679 | 53 chunks | diagnostic — awards partial credit, so never the headline |
| MRR | 0.501 | 50 questions | diagnostic. The right chunk is often found but rarely first |
| **Lexical leakage of the questions** | **0.332** | 259 stems | how much of each question's vocabulary its own target chunk hands it. **Gated to never rise** |
| Misses: unreachable / out-ranked | 6 / 11 | 17 chunks | zero stem overlap vs. matched but below k |
| Answer groundedness | — | | needs the answering slice |
| Branch coverage | — | | needs the answering slice |
| Over-claim rate | — | | needs the answering slice |
| Citation accuracy | — | | needs the answering slice |
| Refusal precision / recall | — | | needs the answering slice |
| Judge–human agreement | — | | needs the judge |
| p95 latency / cost per query | — | | no model runs yet; this slice costs €0 |

**Read the headline together with the leakage row.** The first version of this harness scored
**0.875** — on 8 questions written with the source PDF open, which leaked **60%** of their
vocabulary into their own target chunks. Real questions harvested from the authority's
resident-facing pages leak 39%. The set was rewritten to 21 questions (6 copied verbatim from
those pages, 15 authored under the rule *name the thing with the document's noun, ask with a
person's verb*), leakage fell to 37%, and the headline fell with it. Slice 4 grew it to 50 across
two authorities and leakage fell again, to **33.2%** — the 29 new questions are *less* leaky than
the 21 they joined, so the set got harder, not easier.

That is the point of the leakage row, and the gate proves it. Reverting a single question to its
statute-flavoured wording:

```
complete-set recall@5   0.762 -> 0.810     (looks like an improvement)
lexical leakage         0.372 -> 0.397
REGRESSION — lexical leakage rose ... the golden set got easier, which
             inflates every score above it                          exit 1
```

Also worth knowing before comparing this to anything published: the corpus is 171 chunks over two
authorities, but a query only ever sees one authority's — 82 or 89 — so top-5 covers ~6% of the
searchable space. That share, not the total, is what makes the number generous.

## What lemmatisation bought

Slice 3 added a Finnish morphological analyser (voikko) **beside** the stemmer rather than instead
of it, and measured every combination. Four analysers × three `ts_rank` normalisations, one corpus,
the same 21 questions, no model, €0. Every number below came from one `make eval` run.

The four analysers **nest** — each adds exactly one mechanism to the one above it — so a
row-to-row delta attributes to that mechanism and nothing else.

| cell | recall@5 | per-chunk | MRR | leakage | unreachable | out-ranked |
| --- | --- | --- | --- | --- | --- | --- |
| **`snowball/0`** (published) | **0.762** | 0.750 | 0.517 | **0.372** | 4 | 2 |
| `snowball/1` | 0.619 | 0.625 | 0.462 | 0.372 | 4 | 5 |
| `snowball/2` | 0.429 | 0.458 | 0.335 | 0.372 | 4 | 9 |
| `lemma-baseform/0` | 0.762 | 0.750 | 0.593 | 0.506 | 2 | 4 |
| `lemma-baseform/1` | 0.714 | 0.708 | 0.547 | 0.506 | 2 | 5 |
| `lemma-baseform/2` | 0.476 | 0.458 | 0.359 | 0.506 | 2 | 11 |
| `lemma-safe/0` | 0.810 | 0.792 | 0.627 | 0.568 | 2 | 3 |
| `lemma-safe/1` | 0.762 | 0.750 | 0.589 | 0.568 | 2 | 4 |
| `lemma-safe/2` | 0.429 | 0.417 | 0.311 | 0.568 | 2 | 12 |
| `lemma-reasm/0` | 0.810 | 0.792 | 0.589 | 0.619 | **0** | 5 |
| **`lemma-reasm/1`** (best) | **0.857** | 0.833 | 0.614 | 0.619 | **0** | 4 |
| `lemma-reasm/2` | 0.429 | 0.417 | 0.286 | 0.619 | **0** | 14 |

> **The table above is the N=21 run, kept because the four findings below are written against it.
> The current grid is N=50 and one of those findings did not survive.** See
> [What the second authority bought](#what-the-second-authority-bought).

Four things worth reading off it, in order of how much they change what to do next.

**Unreachable misses went 4 → 0.** This is the result, not the headline. A required chunk that
shares no lexeme at all with its question cannot be retrieved by any ranking; one that is
out-ranked can. Compound splitting reaches all four, so every remaining miss is now a *ranking*
failure with a different fix. That includes the resident-vocabulary case (`taloyhtiö`, `asunto`,
`keskusta`), which sharpens the argument for embeddings rather than removing it: those words do
reach the clauses that answer them, and carry no weight in them.

**Dividing by document length is not the free win it looked like.** Normalisation 1 *costs* the
control cell 0.143 of its headline and normalisation 2 costs it 0.333 — most golden targets are
full clauses, not the short definitions that slice 1 measured losing. It gains recall in exactly
one place, the compound-splitting cell, because splitting inflates the lexemes in a chunk and
that is precisely what unnormalised `ts_rank` over-rewards. **The sign flips.** Measuring the two
changes in sequence, as the plan originally had it, would have concluded "length normalisation is
harmful" and stopped one cell short of the best configuration.

**Leakage rose from 0.372 to 0.619 without a single question being edited.** Words the stemmer
split apart are now the same lexeme, so the metric can finally see overlap a human eye always
could — the [debt entry](REVIEW-DEBT.md) predicted exactly this and it is now measured. Leakage is
gated to never *rise*, so this is recorded **per cell** and each cell is compared only against
itself. The rule is intact; it now has twelve guards instead of one.

**The published headline did not move.** `snowball/0` is still what the table above reports, on
purpose. Promoting `lemma-reasm/1` means picking one cell of twelve after seeing all twelve, on 21
questions, with no held-out slice. That is a decision with a re-baseline attached, and the gate
fails if the published cell moves without one.

One correction belongs here rather than in a footnote: the plan for this slice named `ts_rank`
normalisation **32** as the axis. It is documented as "divides the rank by itself + 1" — that is
`rank / (rank + 1)`, strictly monotonic, so it **cannot reorder anything**. The first run scored
all eight cells identically at 0 and 32, which is the only reason it was caught. Read the formula,
not the flag name.

## What the second authority bought

Slice 4 grew the golden set from 21 questions to **50** and ingested a second authority —
Pirkanmaa's *Alueellinen jätehuoltolautakunta*, 48 clauses → 89 chunks, 16 municipalities. Both
were done in one slice because the reason for each was the same reason.

| cell | recall@5 | Lounais-Suomi (29) | Pirkanmaa (21) | leakage | unreachable | out-ranked |
| --- | --- | --- | --- | --- | --- | --- |
| **`snowball/0`** (published) | **0.680** | 0.724 | 0.619 | **0.332** | 6 | 11 |
| `snowball/1` | 0.640 | 0.655 | 0.619 | 0.332 | 6 | 13 |
| `snowball/2` | 0.460 | 0.414 | 0.524 | 0.332 | 6 | 22 |
| `lemma-baseform/0` | 0.740 | 0.759 | 0.714 | 0.442 | 2 | 12 |
| `lemma-baseform/1` | 0.780 | 0.759 | 0.810 | 0.442 | 2 | 10 |
| `lemma-baseform/2` | 0.460 | 0.448 | 0.476 | 0.442 | 2 | 27 |
| `lemma-safe/0` | 0.760 | 0.793 | 0.714 | 0.506 | 2 | 11 |
| `lemma-safe/1` | 0.760 | 0.759 | 0.762 | 0.506 | 2 | 11 |
| `lemma-safe/2` | 0.280 | 0.345 | 0.190 | 0.506 | 2 | 36 |
| **`lemma-reasm/0`** (best) | **0.820** | 0.793 | 0.857 | 0.550 | **0** | 10 |
| `lemma-reasm/1` | 0.820 | 0.828 | 0.810 | 0.550 | **0** | 10 |
| `lemma-reasm/2` | 0.320 | 0.345 | 0.286 | 0.550 | **0** | 36 |

### Can this instrument tell?

This is the question the slice was really about, and the harness now answers it every run.

Two cells are scored on the **same** questions, so comparing them is a **paired** test. Only the
questions the two cells disagree about carry information; with `d` of them all flipping one way the
exact McNemar test gives `2 × 0.5^d`, so **six must flip for p<0.05 — at any N.**

At N=21 the best cell had three failures. Fixing *every remaining miss* would have given d=3,
p=0.25. Not "a small effect relative to noise": **there was no result any retrieval change could
have produced that would have registered.** The previously published "0.857 vs 0.762" was never a
claim the instrument could support.

At N=50 it can:

| vs published `snowball/0` | d | favours it | favours published | exact p |
| --- | --- | --- | --- | --- |
| **`lemma-reasm/0`** (0.820) | 9 | 8 | 1 | **0.039** |
| `lemma-reasm/1` (0.820) | 11 | 9 | 2 | 0.065 |
| `lemma-baseform/1` (0.780) | 11 | 8 | 3 | 0.227 |

`make eval` prints `d` and the exact p for **every** pair of cells, so nobody has to assume a
0.048 delta means something. The regression **gate** needs none of this — it is deterministic at
any N. Power is only about claiming an improvement is real.

### Two predictions were refuted, and one earlier finding was retracted

Predictions were written down before the run. Reporting the ones that failed is the point.

**The two authorities really do use different words for the same things** — `jäteastia` /
`keräysväline`, `korttelikeräys` / `lähikeräysjärjestelmä`, `aluekeräyspiste` / `aluejätepiste`.
These share no stem, so no analyser can bridge them, and eight **paired questions** (one text
labelled once per authority) were added to measure it. The fork is real: `"Asuinalueellamme jätteet
kerätään kaavan mukaan yhteiseen pisteeseen. Onko siihen pakko liittyä?"` retrieves Pirkanmaa's
11 § at rank 1 and **fails for Lounais-Suomi in 10 of 12 cells** — identical words, different
jurisdiction, different outcome.

**But the predicted mechanism was wrong.** Unreachable misses were predicted to return, 0 → 3–8.
They stayed at **0**. A question shares plenty of *other* lexemes with its target even when the key
noun does not match, so the fork costs recall through **ranking**, not reach. In the failing
Lounais-Suomi case the top-5 even contains the *definition* of `korttelikeräys` while the operative
clause ranks below it. Since the pre-registered rule for choosing the next slice keyed on that
count, **the case for the vector layer has to be re-argued from evidence rather than from the
plan.**

**Pirkanmaa was also predicted to score below Lounais-Suomi in every cell.** It scores *higher* in
5 of 12, including the best. The nominated explanation — "its questions are easier" — is not
supported by the metric nominated to test it: Pirkanmaa's questions leak **less** (0.323 vs 0.341).

**And a slice-3 finding did not survive the bigger set.** "Length normalisation helps only the
split analyser" is false at N=50: normalisation 1 now *helps* `lemma-baseform`, and is *neutral*
for both split analysers. That conclusion rested on a one-question gain at N=21 — d=3, p=0.25,
which by the corrected statistic was never resolvable. The surviving claim is the narrow one:
**length normalisation costs the control cell and does not clearly help any lemma cell.**

This is what growing a golden set actually buys. Not a better score — a retracted conclusion.

### The authority filter, verified for the first time

With one authority loaded there was nothing to leak from, so the product's #1 failure mode was
100% untested. Now every question's top-5 is asserted to contain **zero** foreign-authority chunks,
inside the eval rather than only in a unit test, for all 50 questions in all 12 cells — so it
cannot be skipped. It has been **seen red** by deleting the jurisdiction `WHERE` clause, and a
companion test proves foreign chunks genuinely do enter the top-5 without it, so the check is not
decoration.

**What that does not prove, stated plainly:** this is *retrieval-layer isolation*, not refusal.
Asking municipality A's question with municipality B's filter set must eventually be **refused**,
and refusing needs an answering layer that does not exist. The debt entry stays **PARTIAL**.

One thing the second authority did **not** do is add distractors. All 12 cells scored *identically*
to the recorded N=21 baseline with Pirkanmaa's 89 chunks loaded and the questions untouched,
because the filter runs before ranking and `ts_rank` has no IDF. An earlier spec predicted the
headline would fall when the corpus grew; that claim was wrong and is corrected where it was made,
so it cannot later excuse a drop that came from somewhere else.

### One municipality is refused an answer that exists

Pirkanmaa's `1 § SOVELTAMISALA` claims Sastamala **only** "(Mouhijärven ja Suodenniemen osalta)" —
two municipalities merged into Sastamala in 2009 whose waste authority did not follow the merger.
So the municipality→authority map is **not a function**, which contradicts a load-bearing decision
this project had already recorded.

Sastamala is therefore omitted, and asking about it raises an error naming the partial coverage
rather than answering from rules that bind part of the kunta. A Mouhijärvi resident is refused an
answer the regulations do give them. That is the trade: an honest refusal for a minority beats a
confident wrong answer, with a correct-looking citation, for the majority.

## Stack

Python · FastAPI · PostgreSQL + pgvector · LiteLLM · Docker · GitHub Actions · Google Cloud Run

## Running it

Needs Docker, [uv](https://docs.astral.sh/uv/), and two sets of system packages that `uv sync`
cannot supply:

```sh
sudo apt-get install poppler-utils libvoikko1 voikko-fi   # Debian/Ubuntu
sudo dnf install     poppler-utils libvoikko  voikko-fi   # Fedora
```

`poppler-utils` provides `pdftotext`; `libvoikko1` + `voikko-fi` are the Finnish morphological
analyser and its dictionary. Without the dictionary the harness **refuses to run** and says how to
install it, rather than falling back to raw tokens — a number computed by a silently degraded
analyser is worse than no number.

```sh
make dev     # create the environment
make eval    # start Postgres, fetch + chunk + load the corpus, score, print the table
```

`make eval` is reproducible from a clean clone: the source PDFs are not in git, but
[`corpus/manifest.yaml`](corpus/manifest.yaml) pins their URLs and SHA-256 digests, and
ingestion refuses to load a document that does not match — or one that parses to a different
number of clauses than the golden labels were written against.

It exits non-zero when a metric falls below [`eval/baseline.json`](eval/baseline.json) **in any
of the twelve cells**, when the analyser's own output changes, when a golden label points at a
chunk that does not exist, when the question set changes size, when the published cell moves
without a re-record, when a lemma index is empty, or when the corpus is empty. Every one of those
paths has been exercised by breaking it on purpose.

The analyser gets its own guard, because `libvoikko` reports the *library* version but not the
*dictionary* version — so a `voikko-fi` upgrade would move every published number with no code
change. `make eval` hashes the lemmas the analyser produces for a committed probe word list and
records that hash in the baseline; `fi-rag-eval eval --probe` prints the whole probe table so a
mismatch can be diagnosed rather than merely detected.

Other targets: `make gate` (lint, format, types, tests, build — the commit gate), `make ingest`,
`make db-up` / `make db-down`, `make eval-baseline` to re-record the baseline deliberately (run it
from a clean tree, so the recorded commit identifies the code that produced the numbers).

## Known weaknesses

Kept honestly, and at more length in [REVIEW-DEBT.md](REVIEW-DEBT.md).

- **N=50, and no held-out slice.** The design's ~50 target is met, and the harness now reports its
  own power instead of leaving it assumed. But holding out 10 of 50 would leave a tuning set that
  cannot reach the 6 discordant questions p<0.05 needs and a held-out set that never can, so the
  carve-out is deliberately deferred to N≈85. Meanwhile the anti-fitting work is done by two things
  that cost nothing: `harvested` phrasing, whose wording is independent of the target chunk by
  construction, and the gated leakage metric. Only 3 of 50 questions span multiple chunks, so
  complete-set and per-chunk recall have still not diverged the way ADR-0003 expects.
- **Only 10 of 50 questions are `harvested`.** Neither authority nor either operator publishes a
  resident FAQ with question-form headings on the topics slice 4 needed, so 4 of the 29 new
  questions are harvested and the share fell from 6-of-21 to 10-of-50. No authored question was
  relabelled to improve that number.
- **A real Pirkanmaa clause is missing from the corpus.** `18 a § KOMPOSTOINTI-ILMOITUS` exists in
  the document body but not in the document's own table of contents, so the body/TOC cross-check —
  the strongest invariant here — is silent, and its text is absorbed into 18 §'s chunk. Two clauses,
  one address. No golden question points at it.
- **Three of five candidate authorities cannot be ingested at all**, because the table of contents
  is located by looking for dot leaders and HSY, Oulu and Savo-Pielinen simply do not use them.
  Their tables of contents are clean and complete. "The extractor is general" is not a claim this
  project may make.
- **Leakage understates itself in the published cell.** It is measured after normalisation, so a
  word the question and the chunk share but which *stems apart* counts as clean. Quantified: the
  same 50 questions leak 0.332 under snowball and 0.550 under the lemmatising analyser, with
  nothing about them changed. 0.332 is a floor, not the truth.
- **The retriever still cannot answer from resident vocabulary — but the reason changed.**
  `taloyhtiö`, `asunto` and `keskusta` appear nowhere in the regulations. Under snowball they are
  literally unreachable; under compound splitting they *do* reach the right clauses (`taloyhtiö` →
  `talo` + `yhtiö`) and are still not retrieved, because they carry no weight there. That is a
  sharper case for embeddings than "no shared stem". **It is no longer a mandate for the next
  slice:** slice 4 predicted the cross-authority synonym fork would produce unreachable chunks and
  measured **zero**, so the pre-registered rule that would have triggered the vector layer did not
  fire, and its case has to be re-argued from evidence.
- **The compound reassembler is a rule I wrote, and its bugs are silent.** It folds voikko's morphs
  back into words, which is what buys `määräyksistä` → `jätehuoltomääräyksistä`. Of 2,513 distinct
  word forms, 76 produce at least one part voikko itself cannot analyse as a word. A junk lexeme
  lowers precision on questions *other* than the one it was built for. It is kept because it
  out-scored the conservative split by a whole question; it is measured against that split on every
  run so it can be deleted rather than tuned.
- **Lemmatisation costs precision as well as buying recall.** One question passes under snowball
  and fails under every lemma cell. The net is +2 questions; it is a net, not a gain.
- **Three of the four indexes are written by the application, not generated by Postgres.** The
  morphology is in Python, so `GENERATED ALWAYS AS` is not available for the lemma columns. They
  are asserted non-empty at ingest and again at every eval, but nothing proves they *agree with the
  body* the way the generated `tsv` column does.
- **The ranker's defaults are wrong for this corpus, and correcting them is not free.** `ts_rank`
  at normalisation 0 does not divide by document length, so short chunks lose: definition chunks
  are 39% of the corpus and 0% of every top-5 in the published cell. Measured in slice 3: dividing
  by length fixes that specific miss and costs more elsewhere, except in the split cell.
- **The authority hard filter is untested.** Only one authority is ingested, so the worst
  failure mode in the design — answering from the wrong jurisdiction — has nothing to leak
  from yet.
- **No CI.** The regression gate has been proven red by hand on this machine — on a crippled
  index, a changed analyser fingerprint and a stale baseline — which is not the same as proven in
  CI. CI will also have to install `libvoikko1` and `voikko-fi`, or the analyser tests skip there
  the same way they skip on a machine without them.

## Licence

MIT — see [LICENSE](LICENSE).

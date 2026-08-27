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

| Metric | Value | N | Notes |
| --- | --- | --- | --- |
| **Complete-set recall@5** | **0.762** | 21 questions | headline: did retrieval find *every* clause the answer depends on |
| Per-chunk recall@5 | 0.750 | 24 chunks | diagnostic — awards partial credit, so never the headline |
| MRR | 0.517 | 21 questions | diagnostic. The right chunk is often found but rarely first |
| **Lexical leakage of the questions** | **0.372** | 78 stems | how much of each question's vocabulary its own target chunk hands it. **Gated to never rise** |
| Misses: unreachable / out-ranked | 4 / 2 | 6 chunks | zero stem overlap vs. matched but below k |
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
person's verb*), leakage fell to 37%, and the headline fell with it.

That is the point of the leakage row, and the gate proves it. Reverting a single question to its
statute-flavoured wording:

```
complete-set recall@5   0.762 -> 0.810     (looks like an improvement)
lexical leakage         0.372 -> 0.397
REGRESSION — lexical leakage rose ... the golden set got easier, which
             inflates every score above it                          exit 1
```

Also worth knowing before comparing this to anything published: the corpus is 82 chunks, so
top-5 covers 6% of it. The number will fall as the corpus grows.

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

- **N=21 against the ~50 the design asks for.** The 95% interval on 0.762 is about ±0.18.
  Only 3 of 21 questions span multiple chunks, so complete-set and per-chunk recall have not yet
  diverged the way ADR-0003 expects them to.
- **Leakage understates itself in the published cell.** It is measured after normalisation, so a
  word the question and the chunk share but which *stems apart* counts as clean. Now quantified:
  the same 21 questions leak 0.372 under snowball and 0.619 under the lemmatising analyser, with
  nothing about them changed. 0.372 is a floor, not the truth.
- **The retriever still cannot answer from resident vocabulary — but the reason changed.**
  `taloyhtiö`, `asunto` and `keskusta` appear nowhere in the regulations. Under snowball they are
  literally unreachable; under compound splitting they *do* reach the right clauses (`taloyhtiö` →
  `talo` + `yhtiö`) and are still not retrieved, because they carry no weight there. That is a
  sharper case for embeddings than "no shared stem", and it is the mandate for the next slice.
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

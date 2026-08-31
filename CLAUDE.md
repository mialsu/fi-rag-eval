# CLAUDE.md — fi-rag-eval

Guard-rails for every session on this project. Adopt every section verbatim except **Domain
guard-rails**, which you fill during `/new-project`. Precedence when docs disagree: the Owner's
live instructions > this file > any summary of it.

This project follows the **devkit method** (see the devkit repo: METHOD.md, PRINCIPLES.md).
Domain profile: **cli-tools**, with a `/ship`-only deploy check grafted from `web` and a
project-specific eval-integrity layer. The choice and its rejected alternatives are recorded in
`docs/adr/0001-domain-profile-cli-tools-hybrid.md` — read it before assuming a stock profile.

## Where this stands (31 Aug 2026)

**Slices 1–4 are built, and slice 5 is four tracers in: the measurement spine, an honest golden
set, a lemmatising analyser measured as a grid, a second authority, an answering boundary with a
scored refusal population, and now a judge that passes an 8/8 known-bad control and publishes
nothing.** Two authorities are ingested into Postgres and
retrieved lexically — Lounais-Suomi (50 clauses → 82 chunks) and Pirkanmaa (48 clauses → 89
chunks), 171 chunks total. `make eval` scores **50** hand-labelled questions in **12 cells**
— 4 analysers × 3 `ts_rank` normalisations — prints a table, a per-authority breakdown, a
per-question × cell pass matrix and a paired-power matrix, and exits non-zero if **any** cell
regresses. Nothing else exists.

- **Published headline: complete-set recall@5 = 0.820 (N=50, k=5) in the `lemma-reasm/0` cell.
  Lexical leakage = 0.550.** Never quote the first without the second. Per authority, as a
  diagnostic: Lounais-Suomi 0.793, Pirkanmaa 0.857. **Three numbers now exist for this corpus —
  0.762 (N=21, `snowball/0`), 0.680 (N=50, `snowball/0`) and 0.820 (N=50, `lemma-reasm/0`) — and no
  document may present them as a trend**: the population changed once and the cell changed once.
  The control cell is still scored every run and reads 0.680 at leakage 0.332; **0.550 against
  0.332 is two analysers reading the same 50 unedited questions, not the golden set getting
  easier** (ADR-0007).
- **The instrument has statistical power for the first time.** Two cells are scored on the same
  questions, so comparing them is a **paired** test: six discordant questions must flip one way for
  p<0.05, at any N. At N=21 no comparison in the grid could reach that at any effect size. At N=50
  `lemma-reasm/0` (0.820) beats the published cell at **d=9, p=0.039**. `make eval` prints d and
  the exact McNemar p for every pair of cells, so nobody has to assume a 0.048 delta means
  something. **The ±0.18 absolute interval that slice 3 and this file used was the wrong
  statistic** — corrected in both specs; the correction made the argument for slice 4 *stronger*.
- **The published cell MOVED to `lemma-reasm/0` on 27 Aug 2026, on the Owner's decision, once the
  paired p-value existed** (ADR-0007, commits `d30e3ee` / `bbe8b1a`). `evaluate.PUBLISHED`
  (`evaluate.py:63`) is the single place that decides, and the gate fails if it moves again without
  a re-record. The move's price was quantified before it was taken and is now being paid: the
  published cell fails 9 of 50, so the N target for detecting a half-of-misses fix rose from ~51 to
  ~84. **The golden set is underpowered by ~1.7x for its own published cell**, and only a fix that
  closes >=6 of the 9 remaining misses while breaking none of them can register at all.
- **Slice 4's strongest prediction was REFUTED, and it changes slice 5.** The two authorities do
  use different words for the same things (`jäteastia`/`keräysväline`,
  `korttelikeräys`/`lähikeräysjärjestelmä`, `aluekeräyspiste`/`aluejätepiste`) and it *does* cost
  recall — a paired question passes for Pirkanmaa and fails for Lounais-Suomi from identical text.
  But zero-overlap misses stayed at **0**: the fork surfaces as a **ranking** failure, not an
  unreachable one, because a question shares plenty of other lexemes with its target. Per the
  spec's pre-registered decision rule (`< 4` synonym-caused zero-overlap misses), **the vector
  layer's case has weakened twice and must be re-argued from evidence, not from the plan.**
  Prediction 2 was also refuted: Pirkanmaa scores *higher* than Lounais-Suomi in 5 of 12 cells,
  and its questions are *less* leaky, so "its questions are easier" is not supported by the metric
  nominated to test it. **Slice 5 is the Owner's call and is not pre-registered.**
- **A slice-3 finding was retracted by the bigger set.** "Length normalisation helps only the split
  analyser" is false at N=50: normalisation 1 now *helps* `lemma-baseform` and is *neutral* for both
  split analysers. It rested on a one-question gain at N=21 (d=3, p=0.25) — never resolvable. The
  surviving claim is narrow: length normalisation costs the control cell and does not clearly help
  any lemma cell.
- **Lemmatisation is voikko, in Python — not `dict_voikko`.** `postgres:17-alpine` ships only
  `dict_snowball`/`dict_int`/`dict_xsyn`, and neither libvoikko nor a Finnish hunspell dictionary is
  in the Alpine repositories. See `docs/adr/0005-lemmatisation-in-python-as-a-measured-grid.md`.
  Requires the **system packages** `libvoikko1` and `voikko-fi`; `uv sync` cannot supply them.
- **A second authority adds ZERO distractors to an existing question.** The filter is applied
  before ranking and `ts_rank` has no IDF. Measured: with Pirkanmaa ingested and the questions
  untouched, all 12 cells scored *identically* to the N=21 baseline. `SPEC-slice-2`'s claim that
  the headline "should be expected to fall when the corpus grows, and the second authority roughly
  doubles it" is **corrected there** — that claim would otherwise excuse a drop from elsewhere.
- **The authority hard filter now REFUSES, and that is measured rather than assumed (28 Aug 2026,
  slice 5 tracer 3). The oldest PARTIAL debt is CLOSED.** Two layers, both real. (1) Retrieval-layer
  isolation: every question's top-k holds zero foreign-authority chunks, asserted inside `evaluate`
  for 50×12, seen red by deleting the WHERE clause. (2) **Refusal**: six out-of-jurisdiction
  questions, each asked with the wrong authority's filter and each reaching the answerer holding
  five plausible same-topic chunks from the authority it *was* asked about — **5 of 6 refused**,
  [0.44, 0.97] at n=6. Read it as "the mechanism is verified and measured at 0.833 with a wide
  interval", never as "the filter cannot fail". The one miss has a contestable label
  (`REVIEW-DEBT.md`).
- **ADR-0002 is amended: a municipality does NOT always resolve to exactly one authority.**
  Pirkanmaa's 1 § claims Sastamala only "(Mouhijärven ja Suodenniemen osalta)", so Sastamala is
  omitted from the map and refuses with a message naming the partial coverage. A Mouhijärvi
  resident is refused an answer that exists — accepted, and the *model* question (a level between
  authority and municipality) is the Owner's.
- **`18 a § KOMPOSTOINTI-ILMOITUS` is a real Pirkanmaa clause missing from the corpus.** It is
  absent from the document's own table of contents, so the body/TOC cross-check is silent and its
  text is absorbed into 18 §'s chunk. Two clauses, one address. No golden question points at
  Pirkanmaa 18 § — do not add one before this is fixed.
- **The judge exists, passes 8/8 on a known-bad control, and PUBLISHES NOTHING (tracer 4, ADR-0010).**
  `fi-rag-eval judge <run.json>` scores every claim and forbidden item of a **frozen** answer run —
  **199 units in 50 calls**, exactly as D3 counted. It never generates the answers it scores: a
  judge prompt is developed by iteration and iteration needs an input that cannot move. Measured
  28 Aug 2026, three runs over the identical file: **groundedness 1.000/0.983, branch coverage
  0.472/0.480, over-claim 0.020, citation address validity 1.000 (58 citations, 0 foreign),
  $0.0699 per run** ($0.3084 for the whole tracer). Every judged figure prints marked `DIAGNOSTIC` with the published value
  **WITHHELD**, because judge–human agreement does not exist until tracer 5 and D11 forbids
  groundedness without it. **A green judge run publishes no number.**
- **The judge DISAGREES WITH ITSELF: self-consistency 0.964 [0.93, 1.00]** over 274 field-verdicts
  in 43 questions (0.970 counting a branch as one unit), via
  `fi-rag-eval agreement A.json --against B.json`. `temperature=0` becomes `1e-8` at Groq for the
  judge exactly as for the answerer; found because a re-run twenty minutes later moved a verdict. It
  is a **ceiling** on judge–human agreement — two judge runs that differ cannot both match a human —
  so tracer 5 reports its agreement figure against 0.964, not against 1.0. Clear of D11's 0.85
  floor, so it changes the *reading*, not the plan. **Tracer 4 first published 0.975 and that figure
  is superseded**: it pooled in the 31 forced units (below), which is the inflation ADR-0011 exists
  to exclude.
- **THE PUBLISHED ANSWER-LAYER HEADLINE IS BRANCH COVERAGE (31 Aug 2026, ADR-0012).** D11's pair
  is INVERTED on the Owner's decision: branch coverage leads, groundedness is printed beside it, and
  the pairing rule, the 0.85 agreement floor and the withholding below it are all unchanged — the
  withheld block now names both figures, since both are judge-dependent. The *order* is the
  decision, and a test asserts it: the first number under `PUBLISHED` is the one copied into a
  README. Another test asserts the two names appear an equal number of times on every rendering
  path, so no branch can emit a lone figure. **Still nothing is published** — the floor gates both
  and agreement does not exist yet.
- **GROUNDEDNESS SATURATES AT 1.000 AND CARRIES NO INFORMATION.** It is identical (1.000) whether
  retrieval was complete or not, because the denominator is branches *stated* and `qwen/qwen3.6-27b`
  never states a branch it cannot cite — it drops the branch instead. All the signal is in **branch
  coverage 0.472**. D11's "never publish groundedness without branch coverage beside it" is
  necessary and, on this evidence, **not sufficient** — which is why the headline moved (above).
- **Prediction 5 — the prediction that decides slice 6 — is VOID as written, and its substance
  holds.** It was registered over groundedness, which has zero variance here. Branch coverage
  answers it decisively: **0.574 with complete retrieval against 0.042 without** (0.598 vs 0.111
  excluding refusals). Answer failures track retrieval. This is the **third** pre-registered
  statistic in this project to be the wrong one while its question was answerable. The slice-6
  decision rule **FIRES for the reranker on substituted evidence, accepted by the Owner on
  31 Aug 2026** (ADR-0012 decision 5). Slice 6 must pre-register its fix size against **branch
  coverage**; the 6-discordant-question bar is unchanged. Recorded as a substitution, never as
  prediction 5 having been scored. **The pattern is now nameable: this project keeps registering a
  statistic before knowing whether it has variance on the population it will be measured over.**
  Slice 6 registers its statistic *and* the evidence that it varies.
- **The known-bad control is real and was seen red.** 8 authored bad answers
  (`corpus/control/known-bad.yaml`), 4 shapes x 2 authorities, each naming the unit verdict that
  must catch it. `judge --control` = **8/8, exit 0**; `--weak-prompt` = **4/8, exit 1** — and it
  failed on **all four citation-support cases and none of the four over-claim cases**. Over-claim
  detection survives a credulous prompt; `supported` does not. Three cases require `stated: true`
  *with* `supported: false`, so a judge that disapproved of everything would fail them.
- **The judge must quote the answer, and the first version of that count overstated the problem.**
  `stated` with no quote is a hard error; a quote absent from the text is recorded. The first run
  flagged 9 of 50 — and the first one inspected was a **splice** (fragments joined, every word
  present, claim genuinely stated), not an invention. `quote_words_present` now separates the two;
  run B reports **2 splices, 0 fabrications**. Never read a splice count as judge fabrication.
- **A citation on a refusal is no longer "any citation is a defect" (ADR-0010).** Citing an address
  **outside** the retrieved set is a defect; citing a chunk it **did** retrieve is a counted
  diagnostic. The old rule labelled the more auditable refusal as the worse one. **No published
  number moved** — refusal recall and precision come from the `refused` field alone.
- **The judge phase is not in `make eval` either**, for the same reason the answer phase is not.
  `judge` needs `make services-up`, a filled `.env`, and a run file under `eval/runs/`, which is
  **gitignored** — so the judged numbers are not reproducible from a clean clone. The **control**
  is, deliberately: it needs no run file. The run this project has is stamped `4b75dfd-dirty`, and
  every judged table prints a `!!` line saying so.
- **THERE IS A PRODUCT SURFACE NOW: `fi-rag-eval ask "<kysymys>" --municipality <kunta>` (31 Aug
  2026).** Until this, nothing in the package could answer a question nobody had labelled — `answer`
  takes a golden question **id**. `ask.py` **reuses** the harness's retrieval (published cell,
  `evaluate.cell_query_lexemes`, `db.search`, stopwords asked of Postgres per word) rather than
  re-implementing it, because a second retrieval behind a demo would drift from every published
  number and both would still look fine. **Exercised live, 3 real calls, $0.0350 total:**
  - Turku *"Kuinka usein sekajäteastia on tyhjennettävä?"* → all **four** conditional branches
    stated, cited to `#26`, nothing flattened. $0.0177.
  - **Tampere, identical question → a genuinely different correct answer** (4/8 weeks against
    Lounais-Suomi's 4/8/16), different clauses, forked vocabulary (`keräysväline`/`jäteastia`).
    $0.0089. This is the jurisdiction fork visible in a product for the first time.
  - Turku *"Paljonko … tyhjennys maksaa?"* → **REFUSED** while holding 5 plausible retrieved
    chunks, naming what the excerpts *do* cover. $0.0084.
- **Every refusal on the `ask` path is FREE, and that is asserted, not intended.** Empty question,
  unknown municipality, partially-covered municipality (Sastamala, reaching a person for the first
  time), a question that normalises to no lexemes, a search that returns nothing — all refuse before
  any model call. The answerer is an injected `Protocol` and the tests pass one that **raises** if
  called, so "costs nothing" is a test failure rather than a comment. Seen red.
- **THE AUTHORITY FILTER WAS NEVER PROVEN ON ITS OWN, and now is.** `db.search` filters on
  `authority_key` **and** `effective_date`, and this corpus's authorities have different dates
  (2024-08-01, 2021-07-01) — so the **date alone** separated them and deleting the `authority_key`
  term left the entire suite green. The isolation check recorded above as *"seen red by deleting the
  WHERE clause"* removes **both** terms, so it never told them apart. A test now plants one
  authority's chunk under the *other's* date, making the dates useless as a separator; seen red with
  only the authority term deleted. **`evaluate`'s 50×12 check and tracer 3's refusal measurement are
  correct but not independently attributed for the same reason** — audit them **before** ingesting a
  second edition (ADR-0006 anticipates one), not after. `REVIEW-DEBT.md`.

- **A GOLDEN LABEL WAS WRONG FOR TWO SLICES, AND THE DETECTOR GUARDING IT COULD NOT HAVE CAUGHT IT
  (31 Aug 2026).** `ooc-autonrenkaiden-vastaanotto` claimed `rengas` appears in neither authority
  *"missään muodossa"*. Both `2 §` definitions **enumerate `renkaat`**, and `12 §` says where
  producer-responsibility waste goes — so the corpus answered the question outright, from two chunks
  the retriever returned, and the answerer's correct answer was scored as a **missed refusal**. The
  entry is REMOVED (14 → 13) with a tombstone forbidding its return as a refusal. Why it survived:
  `ILIKE '%rengas%'` cannot see `renkaat` — consonant gradation against a check on the nominative
  singular. **A lemma-aware check now runs beside the substring one, both must pass, and it was seen
  red on this exact case with the substring check returning `[]` next to it.** Multi-word needles
  require *adjacency*, and the detector uses `lemma-baseform`, never the published cell —
  `lemma-reasm` decomposes `lisäjäte` into `jäte`. **The detector also moved into `make eval`**; it
  had been reachable only through a ~$0.76, ~50-minute networked command.
- **`ooc-romuajoneuvon-toimituspaikka` has the SAME defect from the SAME sentence and the label was
  KEPT.** `romuautot` is in that enumeration, so "where do I deliver it" is answerable; the
  deregistration half is not. The Owner kept it and the false `label_source: "Ei lähdepykälää"` was
  corrected in place. **`romuauto` vs `romuajoneuvo` is a different compound, so neither check can
  ever see it** — the `sakokaivo` case, recorded rather than papered over. Read `REVIEW-DEBT.md`:
  the prior of "one wrong label in this population" is no longer zero.
- **Refusal metrics now RECOMPUTE OFFLINE from a committed file (`make refusals`).** No database, no
  gateway, no spend. Measured 31 Aug 2026 over the frozen sample: **recall 0.923 [0.67, 0.99] n=13,
  precision 0.632 [0.41, 0.81] n=19, precision\* 0.857 [0.60, 0.96] n=14, out-of-corpus 1.000 n=7,
  out-of-jurisdiction 0.833 n=6.** Recall moved because the *set* changed, not because the answerer
  improved — **anyone quoting the rise as progress is quoting a re-labelling**, and at n=13 a 95%
  interval is still roughly ±0.26. Precision did **not** move, because its denominator is every
  refusal *emitted* and the tyre question was answered rather than refused. **The published
  0.857 n=14 stands as what the tracer-3 configuration produced over the set as it then was.**
- **Refusal precision has a second reading, `precision*` (Owner, 31 Aug 2026).** Same numerator,
  denominator excluding refusals of answerable questions whose retrieval was incomplete — the
  answerer refused 5 of 9 with incomplete retrieval and 2 of 41 with complete (Fisher p=0.0011), so
  `precision` charges it for retrieval's failures. **Printed beside `precision`, never instead**, with
  every excused question named, and NOT COMPUTED at all when completeness is unknown for any
  answerable question.
- **The answering boundary and the refusal population exist (tracers 2–3).** `fi-rag-eval answer <id>` answers one question; `fi-rag-eval answer --all`
  answers **all 63** — 50 answerable + 13 refusal — through `qwen/qwen3.6-27b` on a LiteLLM gateway,
  and prints refusal precision/recall as arithmetic with Wilson intervals. Measured 28 Aug 2026 over
  the then-14 refusal set:
  **refusal recall 0.857 [0.60, 0.96] n=14; precision 0.632 [0.41, 0.81] n=19; out-of-corpus 0.875,
  out-of-jurisdiction 0.833. $0.7553 for 64 calls, 478,438 tokens, ~50 minutes.** Still absent:
  groundedness, branch coverage, over-claim, citation support, judge–human agreement — all of which
  need the judge. Requires `make services-up`, not `make db-up`. See ADR-0009.
- **The answer phase is NOT in `make eval`, deliberately, until tracer 6 derives its floor gate.**
  `make eval` stays offline, deterministic and zero-tolerance; wiring an ungated networked phase
  into it would make the deterministic half of the harness depend on a provider. So **a green
  `make eval` still proves nothing about answering.**
- **The two populations are separated structurally, not by documentation.** `Question` and
  `RefusalQuestion` are different types; `compute` refuses a refusal outcome at runtime and
  `refusal_metrics` refuses a retrieval one. The retrieval headline is still over **exactly 50**,
  and `eval/baseline.json` was re-recorded byte-identical to prove the 14 changed nothing.
- **The answerer over-refuses, and it does so almost entirely when retrieval failed it.** 7 of 50
  answerable questions were refused: **5 of the 9 with incomplete retrieval, but only 2 of the 41
  with complete retrieval** (Fisher exact p=0.0011). Most of the "wrong" refusals are the answerer
  being honest about a context that genuinely lacked the answer — so refusal precision as defined
  charges it for a *retrieval* failure. This is **not** prediction 5 scored: that is about
  groundedness and needs the judge. It points the same way.
- **Prediction 3 was REFUTED and prediction 6 was REFUTED.** The hard refusal kind was predicted to
  fail (≤4/6) and did not (5/6); the two kinds are statistically indistinguishable at n=8 and n=6.
  Cost per run was predicted within 2x of $0.067 and the answer phase alone is **$0.7553**, 11x —
  the $25/month ceiling is not at risk (~33 runs) but ADR-0008's CI arithmetic must be redone once
  the judge's cost is known.
- **`json_validate_failed` has two causes, and tracer 2 only found one.** Groq's JSON mode rejects a
  generation server-side, and `temperature=0` becomes `1e-8`, so it happens *stochastically*.
  LiteLLM does not retry a 400. One such failure destroyed a 45-minute, $0.58 run at its 29th
  answer. It is now retried (bounded) and **counted**, because how often the answerer cannot emit
  its envelope is a fact about the model under test. Do not read this error code as "the token cap
  was too small".
- **Reasoning is not a performance knob here, it is a correctness one.** Measured on one question:
  with reasoning off, the answerer produced the *same inversion of `17 §`* that disqualified
  `gpt-oss-20b` in tracer 1; with it on, it stated all three required branches and named the
  determining variables it could not resolve. It costs ~5.3x the dollars ($0.0210 vs $0.0040 per
  answer). Pre-registered as prediction 7; do not turn reasoning off to save money without
  scoring it.
- **Tracer 5's Foreman half is BUILT; its Owner half is 168 hand labels that do not exist
  (ADR-0011).** The sample is frozen and **committed** at `eval/frozen/sample-tracer5.json` — not
  gitignored, stating its own provenance inside (`answered_at_commit: 4b75dfd-dirty`). Re-answering
  from a clean commit was considered and **rejected**: the answerer is non-deterministic, so it
  would produce different answers and move refusal recall 0.857 and precision 0.632 — re-publishing
  two measured numbers to improve a provenance string.
  - `fi-rag-eval label` drives **168 units** blind and resumable, writing after every unit.
  - `fi-rag-eval agreement <verdicts>` computes judge–human agreement and applies D11's floor. It
    **refuses to run** while any unit is unlabelled: the labelled subset is not a random subset.
  - **Labelling is BLIND, and that is enforced by a signature.** `labelling.format_context` takes
    `(one, bodies, citations)` — there is no parameter through which a judge verdict, suggestion or
    stability flag could reach the labeller, and a test asserts the signature. Showing the judge's
    verdict would measure the human's willingness to disagree, not the judge's accuracy.
- **31 of the 199 units are FORCED-AGREEMENT and are excluded from the measurement.** A refused
  answer states nothing, so both the judge and any honest human are forced to *not stated* on all of
  its units. Pooling the 31 hands the judge **0.156 of agreement before a word is read**, and
  `(x·168+31)/199 = 0.85` gives **x = 0.827** — a judge agreeing on only 0.827 of the real units
  would clear D11's floor. Excluded, printed on every table, and it cuts the labelling from 199 to
  168 units.
- **The lemma detector cannot see a synonym under a different compound, and one is still in the
  set.** Neither check will ever catch `romuauto` for `romuajoneuvo`. Every entry ultimately rests on
  a hand-made claim in `absence_source`; the lexeme only keeps it from rotting. Re-derive the whole
  population from the clause lists at the N≈85 tranche.
- **Not built:** embeddings, pgvector, reranking, **the 168 hand labels and therefore judge–human
  agreement**, the answer-metric floor gate, a third authority, CI, Docker, Cloud Run.
  `make docker-build` still exits non-zero on purpose — do not "fix" it.
- **No held-out slice yet.** Deferred deliberately to N≈85: holding out 10 of 50 leaves a tuning set
  that cannot reach d=6 and a held-out set that never can.
- Read `REVIEW-DEBT.md` before assuming any capability exists, and `/verify-claim` anything a
  doc, an old note, or a past session says already works.

## Hard limits (immutable)
- Never push, open a PR, deploy, publish, or release without the Owner's explicit go. Local
  commits are fine; anything that leaves this machine is an explicit keystroke.
- Never spend money, add API keys, or send anything to a real external recipient without asking.
- Never run a destructive command on shared or irreplaceable state.
- **Never sign a commit, PR, or issue as Claude.** No `Co-Authored-By: Claude ...` trailer, no
  "Generated with Claude Code", no 🤖 line, no Claude/Anthropic attribution of any kind in a commit
  message, PR body, issue, or changelog. The Owner is the sole author of record. This overrides the
  agent harness's default git behaviour, which adds those trailers unless told otherwise.
- When a permission layer refuses an action, **stop and stage it** — do not work around it.

## Build gates (green before every commit)

Run them all with `make gate`. Every one below has been run, and has been proven able to fail.

- Typecheck: `uv run mypy` (strict, over `src` and `tests`)
- Lint: `uv run ruff check .`
- Format: `uv run ruff format --check .`
- Tests: `uv run pytest`
- Build: `uv sync --locked && uv run python -c "import fi_rag_eval"` — proves a clean clone
  reproduces this environment. This is the per-commit build gate; the container image
  (`make docker-build`) is a `/ship`-time gate, not a per-commit one.
- Live exercise: `make eval` (which runs `make db-up` then `make ingest` first). See
  **Verify like a user** below. `make gate` does *not* run it, and the end-to-end tests inside
  `make test` **skip** when Postgres is down — so a green `make gate` with the database
  stopped proves the pure functions and nothing else. The analyser tests skip on the same terms
  when `voikko-fi` is absent; the reassembly rule itself is pinned by pure tests that always run.
  The boundary tests skip on the same terms when the LiteLLM gateway is down, and **no test in
  `make gate` makes a live model call** — a green gate is compatible with an answering path that
  401s on its first real request (confessed in `REVIEW-DEBT.md`).
  Requires Docker, `poppler-utils`, `libvoikko1` and `voikko-fi`. Anything that answers additionally
  needs `make services-up` and a filled `.env`. **Neither `fi-rag-eval answer --all` nor `fi-rag-eval judge` is
  part of any gate**: the answer phase takes ~50 minutes and ~$0.76, the judge ~7 minutes and
  ~$0.07, and both are run deliberately by a human. No test in `make gate` calls the judge either.

A gate you haven't run is not a gate. Green tests gate; they do not prove.

## Definition of DONE
Built + gates green + **exercised the way a user hits it, with evidence** (`/verify-live`) +
copy is in the user's language + every cut corner confessed to REVIEW-DEBT.md + tracked.
Never ship: dead screens, fake zeros, raw IDs on a surface, "coming soon"/"unsupported".

For this project specifically, done is `DESIGN.md:149-151`: the README opens with a filled metric
table, `make eval` reproduces it from a clean clone, and CI fails on regression.

## Verify like a user

Three layers. The first is the `cli-tools` recipe; the second is this project's own and is the one
that matters most; the third applies only at `/ship`.

### 1. Run the harness for real
- Run `make eval` from a **clean clone into a fresh environment**, not your dev checkout, on the
  real corpus. A harness that only works in your working tree isn't done.
- Happy path: the metric table prints, exit code `0`.
- Bad-input path: missing corpus, unknown municipality, absent golden set → a helpful message on
  **stderr** and a **non-zero exit**. CI depends on this exit code, so it is a feature.
- **Report the N.** Never accept a table from a run where questions errored and were skipped. If
  the golden set has 50 questions, the run answered 50 or the table is void.
- Paste the actual terminal output as evidence. Not a summary of it.

### 2. Verify the measurement, not just the code
The instrument is the product. A green number from a broken harness is this project's worst
possible output, because everything else is trusted against it.
- **No circularity.** Golden-set chunk labels were hand-written from the sources. If any label was
  derived from what the retriever returned, `recall@k` is measuring the retriever against itself.
- **The judge fails a known-bad control.** Feed it answers with deliberately wrong citations and
  fabricated claims. If they pass as grounded, the judge is broken — fix the judge, not the answer.
- **Report judge–human agreement as a number** on the fixed sample, every run (`DESIGN.md:97-100`).
  "Spot-checked" is not a measurement.
- **Prove the regression gate goes red.** Break something on purpose — drop a chunk, downgrade the
  reranker, swap the model — and confirm CI actually fails. A gate never seen red is decoration.
- **Keep a held-out slice** the tuning never touches, or the numbers stop predicting real quality.
- **Never re-label a golden entry because the answer improved.** Still the rule, and it survived its
  first real test on 31 Aug 2026 — `ooc-autonrenkaiden-vastaanotto` was removed not because the
  answerer "got it right" but because the corpus was **read** and the entry's own `absence_source`
  was **false**. Check the corpus, not the score. The tell that it was done honestly: the same sweep
  found `ooc-romuajoneuvon-toimituspaikka` has the same defect, and re-labelling *that* one would
  have **lowered** recall — a re-label pass that only ever moves the number up is chasing the number.
  A re-label remains a change to the **set**, followed by a **re-measurement**, reported as such;
  it is never a correction applied to a published result. `make refusals` now makes that
  re-measurement free, which removes the last practical excuse for not doing it.
- Trust the arithmetic over the model: `recall@k` and MRR involve no judge, so when the two layers
  disagree, retrieval metrics win the argument.

### 3. The municipality hard filter (the #1 product failure mode)
`DESIGN.md:15,67` make cross-municipality answers structurally impossible rather than discouraged.
Verify that structurally:
- Ask a question answerable only from municipality A's rules, with municipality B's filter set →
  it must **refuse**, not answer from B's rules.
- Ask with no municipality set → it must not silently pick one.

### 4. At `/ship` only (grafted from the `web` profile)
- Hit the deployed Cloud Run URL and confirm the **served version matches the commit you merged**.
- Run one real query and one refusal case against the deployed URL, not localhost.
- Not adopted from `web`: browser-persona walks, restricted-user login, empty/error-state
  screenshots — there is no UI or auth in scope.

## What green tests can't prove here (watch for these)
- A metric that is green because the harness is circular (labels derived from retriever output).
- A judge that agrees by default, making groundedness look perfect.
- A metric averaged over a silently reduced N after questions errored out.
- Golden-set leakage: scores climb while real answer quality doesn't. **Measured every run and
  gated to never rise, per cell.** In the SNOWBALL CONTROL cell it was 60% in slice 1, 37% at N=21,
  and is **33.2% at N=50** — the 29 questions slice 4 added are *less* leaky than the 21 they
  joined, so the set got harder, not easier. The **published** cell now reads **55.0%**, which is a
  different analyser reading the same unedited questions and is **not** comparable to 33.2%. The
  reference for real harvested questions is 39%. A rising headline with rising leakage is not an improvement.
  Note that a *better analyser* raises leakage on its own, with no question edited (0.372 → 0.619
  in slice 3) — which is why each cell is gated against its own recorded value and never against
  another cell's. Comparing across cells would fail the gate for a reason that has nothing to do
  with the golden set getting easier.
- The authority filter applied *after* rerank, or skipped when the field is absent.
- Finnish compound words and inflection sinking lexical recall — it will look like a model problem
  and it isn't (`DESIGN.md:118`).
- Latency and cost per query measured on a warm cache.
- A ranker whose defaults are wrong for the corpus: `ts_rank`'s default normalisation (0) does
  not divide by document length, so short chunks lose systematically. Measured: definition
  chunks are 39% of the corpus and were 0% of every top-5.
- **A knob that looks like a fix and is a no-op.** `ts_rank(..., 32)` is `rank / (rank + 1)`:
  monotonic, so it reorders nothing. It scored identically to the default in all eight cells of
  the first slice-3 run, which is the only reason it was caught. Read the flag's *formula*, not
  its name — and be suspicious of an axis whose cells agree to three decimals.
- **A junk lexeme from a hand-rolled morphological rule.** Its damage is displaced: it lowers
  precision on questions *other* than the one it was built for, so it surfaces as an unrelated
  cell regressing rather than as a bug in the rule.
- **A lemma index that is silently empty.** Three of the four `tsvector` columns are written by
  the application, not generated by Postgres, so an empty one makes a chunk unretrievable in that
  cell and the miss is attributed to the analyser. Asserted at ingest and again at every eval.
- A query stemmed a different number of times than the index. `to_tsquery` re-stems lexemes
  that came out of `to_tsvector`; that bug shipped in the first run of this harness and made
  the number look *worse*, not better, which is why nothing looked wrong.
- A regression gate that cannot actually go red.

## Process rules
- Shape before build: `/grill-with-docs` → agree a spec → wait for an explicit "go".
- One question at a time, each with a recommendation. Verify claims against the code, never
  memory. Ambiguity goes to CUSTOMER-QUESTIONS / the spec's open-questions, never a silent guess.
- Slice end-to-end; gate every commit; confess at every landing; fold review fixes into commits.
- Reuse before building. Write load-bearing decisions down as ADRs at the moment of decision.
- Build the golden set **before** tuning anything. `DESIGN.md:117` makes this the top risk; the
  milestone order in `DESIGN.md:107-111` does not enforce it, so the discipline lives here.

## Domain guard-rails  (authored by the Owner, 26 Aug 2026)

- **Scope (one sentence):** An evaluation harness for Finnish waste-regulation QA — it answers
  with citations or refuses, and it measures that behaviour well enough to fail CI on a
  regression. *The harness is the product; the RAG pipeline is the thing being measured.* When
  answer quality and measurement quality compete for a session, **measurement wins** — "retrieval
  got better but the harness can't prove it" is a failure, not progress.

- **Explicit non-goal:** **Corpus breadth.** No municipalities beyond the handful chosen for
  format variety until the existing ones' metrics are trustworthy. Adding a municipality feels
  like progress, costs a day, raises the document count, improves the instrument by nothing, and
  dilutes a hand-labelled golden set you then have to redo. (`DESIGN.md:40-44` additionally binds:
  no chat product, no auth/accounts/memory, no fine-tuning, no real-time ingestion.)

- **Must never do:** **Never publish a metric it did not compute.** No hand-written values in the
  README table. No table from a run that skipped or errored questions. Every published number is
  traceable to a run, with its N and its commit. Every other failure here degrades the project;
  this one destroys it, because the numbers are the only reason to trust anything else.

- **Project-specific hard limits:**
  1. **Cost ceiling on eval runs.** Cheapest adequate model by default; no unattended eval loops.
     **Resolved 27 Aug 2026 as "free tier, no monetary ceiling, no paid run planned" — and REVERSED
     the same day on measured evidence. A paid Groq Developer plan IS approved for this project**
     (ADR-0008). The reversal was arithmetic, not preference: one full answer-layer run is ~420K
     tokens against a free-tier allowance of 8K TPM and **200K TPD**, i.e. **~2.1x the entire daily
     budget**. That also makes `DESIGN.md:121-122`'s CI-on-every-PR impossible on the free tier, and
     makes a 52-minute saturated run exactly the unattended loop this limit forbids.
     **Groq alone is approved. Still ask before introducing any other paid provider.**
     **The ceiling is $25/month, set by the Owner at Groq on 27 Aug 2026**, against a measured
     ~$0.067 per run (~370 runs). It has three enforcers and the one that matters is ours:
     a **per-run token budget in code that hard-fails at ~600K tokens (~$0.15)**, the LiteLLM
     Proxy's per-key budget, and the provider cap. A ceiling that lives only in a dashboard is a
     standard with no enforcer — the harness would never notice a runaway, it would just collect
     429s.
     **Rate limits remain real even on the paid plan, and the requirement they created stands.**
     This harness must never publish a table over a silently reduced N, so the answering slice needs
     retry-with-backoff and a **hard failure** when a question cannot be scored — never a skip.
     Two smaller consequences: Groq serves open models rather than Claude, which is *fine* and even
     helpful for `CONTEXT.md:59`'s rule that the judge must be a different model **family** than the
     one under test; and the data-usage terms want reading once, though the corpus is public
     documents and the queries are golden-set questions, so the no-personal-data limit is not at
     risk today.
  2. **No personal data, ever.** The corpus is public documents reached through the manifest only.
     Never log raw end-user queries or anything identifying. Note the unresolved tension:
     `DESIGN.md:74` says no personal data, while `DESIGN.md:35` specifies structured per-query
     logging — and a resident's real question can itself be personal data. Logging is where this
     bites; resolve it before any query log leaves this machine.

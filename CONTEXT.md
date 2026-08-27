# CONTEXT.md — fi-rag-eval

The project's canonical vocabulary: the words the code and the domain actually use, defined once
so every session (and every agent) speaks the same language. Glossary only — no implementation
detail, no file paths (those go stale). This is the single source of truth for names.

**Purpose (one sentence):** Answer Finnish waste-regulation questions with citations or an honest
refusal, and measure that answer quality well enough to catch a regression before it ships.

## Glossary

| Term | Means | Notes |
|---|---|---|
| Jätelaki | The Finnish national Waste Act. | The national floor every municipality builds on. |
| Jätehuoltomääräykset | An Authority's waste-management regulations, sitting on top of `jätelaki` and binding every municipality in its area. | The per-authority layer. This is what differs between jurisdictions and what makes the authority filter load-bearing. |
| Source | One original public document (a PDF or HTML page) as published by its authority. | The unit of ingestion, listed in the manifest. |
| Manifest | The checked-in list of source URLs that makes ingestion reproducible. | Raw documents stay out of git; the manifest is what is versioned. |
| Property type | Whether a property is residential or non-residential (business, parish, wellbeing services county, state). Selects which clauses and momentit bind it. | A determining variable. The MVP models residential only. |
| Clause (§) | One numbered section of a regulation. The unit the document cites itself by, and the default chunk boundary. | **50** in the Southwest Finland regulations (the 72 counted during shaping included a cross-reference list); chunking yields 82 chunks, median ~43 words, largest ~375. |
| Chunk address | A chunk's stable identifier, in the document's own terms rather than the chunker's: authority, effective date, clause, optional sub-key — `lounais-suomi@2024-08-01#15`, `…#2.biojatteella`. | What golden labels reference. Survives re-extraction and chunker changes. A content hash is stored alongside (never as the key) to catch text drift; an unresolvable address is a **hard error**, never a skipped question. |
| Document version | **The text as published at one point in time.** The thing a golden label points into: if the text changes, the labels are at risk whether or not the effective date moved. | **Corrected 27 Aug 2026:** the old wording said "identified by its effective date", which is precisely the ambiguity ADR-0006 resolves — six editions of Pirkanmaa's text share the effective date 1.7.2021. A version is identified by its **content hash**; its *address* is keyed on the effective date and its *edition* is what a human reads. A new version requires labels to be re-pointed **explicitly** — they never migrate silently. |
| Edition | **Which published revision of a Source this is**, in the authority's own words — `1.5.2026 alkaen`. Declared in the manifest, asserted against every date in the document's front matter, and carried into the citation. | Distinct from the address's effective date, and the distinction is the whole of ADR-0006: Pirkanmaa's text says it comes into force **1.7.2021** and is published as the **1.5.2026** edition after five amendments. The address names when the text took force; the edition names which revision you are reading. Never write one where the other is meant. |
| Partial coverage | **A Municipality an Authority covers only part of.** Pirkanmaa's `1 § SOVELTAMISALA` claims Sastamala only "(Mouhijärven ja Suodenniemen osalta)" — two municipalities merged into Sastamala in 2009 whose waste authority did not follow the merger. | Recorded in the manifest and **deliberately not resolvable**: such a kunta raises rather than answering, because these rules bind part of it and not the rest. An honest refusal beats a confident wrong answer for the majority of its residents. The counterexample that amended ADR-0002. |
| Paired question | **One question text labelled twice, once per Authority**, on a topic where the two authorities' rules genuinely differ *and* their vocabulary forks. | Eight in the set. They carry three jobs at once: verifying the hard filter, filling `DESIGN.md`'s "answer differs between authorities" category (zero questions before slice 4), and measuring the Vocabulary fork. The loader enforces exactly two halves, identical text, different authorities — so "the same question retrieves different rules" is checked, not eyeballed. |
| Vocabulary fork | **Two Authorities using different words for the same thing** — `jäteastia`/`keräysväline`, `korttelikeräys`/`lähikeräysjärjestelmä`, `aluekeräyspiste`/`aluejätepiste`. | A **synonym** gap, not a morphology gap: the words share no stem, so no analyser can bridge them and compound splitting is irrelevant. Measured, and the measurement was a surprise — it surfaces as a **Ranked-out miss**, not a Zero-overlap miss, because a question shares plenty of *other* lexemes with its target even when the key noun does not match. |
| Discordant pair | **A question two Cells disagree about** — one retrieves its whole required set, the other does not. The only questions that carry information when comparing two cells. | Cells are scored on the same questions, so comparing them is a **paired** test and an absolute-difference interval is the wrong instrument. With every discordant question flipping one way the exact McNemar test gives `2 x 0.5^d`, so **six must flip for p<0.05, at any N**. Printed every run for every pair of cells. |
| Statistical power | **Whether this instrument could detect an improvement of a given size at all** — as opposed to whether one happened. | Reported, because it is otherwise assumed. At N=21 the best cell had three failures, so fixing *every remaining miss* gave d=3, p=0.25: there was no result any retrieval change could have produced that would have registered. That is why the golden set was grown before the vector layer. The regression **gate** needs none of this — it is deterministic at any N. |
| Momentti | A numbered paragraph within a clause. The granularity at which the regulations scope applicability ("17 §, momentit 1–3, 5, 7–9"). | **Not modelled in the MVP.** Business-property questions are therefore a known-fail class, not a silent defect. |
| Sub-key | The part of a chunk address after the clause, naming a piece *within* a clause. Only `2 § Määritelmät` has them. The shortest leading-word prefix of the definition paragraph that is unique in the clause — `biojatteella`, `kunnan-jarjestamalla`. | **Not the lemma of the defined term.** The definiendum is a bolded phrase the text extractor cannot see, and guessing a lemma needs morphology the project does not have. |
| Chunk | One clause-level passage of a source, the unit that is embedded, retrieved and cited. | Clause-level by decision, not fixed-window — a chunk straddling two clauses produces a citation that does not defend the claim. |
| Authority | The municipal waste-management authority (*jätehuoltoviranomainen*), often a joint regional board (*jätelautakunta*), that approves and publishes one uniform set of regulations for every municipality in its area. | **The unit of publication, and the hard filter's key.** Turku is one of 18 municipalities under Lounais-Suomen jätehuoltolautakunta. Carries its own identity, effective dates and supersession. |
| Municipality | A Finnish *kunta*. The resident's user-facing input, resolved through a checked-in map to the Authority that publishes its regulations — **usually exactly one, but not always.** | **Never appears on a chunk.** Two municipalities under one Authority have identical regulations, and answering them identically is correct, not a bug. **Corrected 27 Aug 2026:** a kunta can be covered only *in part* (see Partial coverage), so the map is not a function. ADR-0002 carries the amendment. |
| Hybrid retrieval | Lexical (Postgres full-text) union vector (pgvector) candidate generation. | Neither alone; the union is then reranked. Postgres `ts_rank` is **not** BM25 — no inverse document frequency — so say `ts_rank` when that is what is meant. |
| Rerank | The second-stage scoring that orders the union of candidates before they reach the model. | |
| Refusal | A first-class output: declining to answer because the retrieved context does not support one. | Evaluated like any other answer. A refusal is a correct answer to an unanswerable question. |
| Conditional answer | The product's normal output shape: the regulation's own branch structure, one citation per branch, with unresolved conditions surfaced rather than silently picked. | Most obligations are conditioned on area, dwelling count or bin type, so a single-value answer is usually a wrong answer. |
| Determining variable | A fact that selects which branch of a conditional answer applies — dwelling count, taajama membership, bin type, composting, **property type**. | May be outside the corpus (taajama boundaries) or personal to the asker (composting). Never guessed. |
| Taajama | A Finnish built-up area. The geographic scope many obligations key on, including the ">10,000 inhabitants" threshold for the bio-waste duty. | **Its boundaries are not in the corpus** — they live in the authority's external map service, and the authority deviates from the national delineation per property. Structurally unanswerable from documents alone. |
| Huoneisto | A dwelling unit on a property. The unit obligations are counted in ("1 or more", "5 or more"). | Not a household and not a person count. Confusing the two silently changes which rule applies. |
| Citation | A pointer from a claim in the answer to the chunk that supports it. | |
| Golden set | The hand-written, hand-answered question set the harness scores against. | ~50 questions. Written before any tuning, deliberately adversarial. |
| Required chunk set | The set of chunk ids a question cannot be answered correctly without. Recall is computed over the whole set. | Set-valued, not a single id — the bio-waste question needs the obligation clause, the interval table and the composting exemption. |
| Required branch | One conditional branch a correct answer must state, paired with the chunk that supports it. **This is the unit a "claim" means here.** | Hand-enumerated per question. Makes the groundedness denominator explicit instead of inferred, and turns judging into narrow yes/no calls. |
| Branch coverage | The share of a question's required branches that the answer actually states. | Localises failure: you learn *which* branch was dropped, not merely that a metric fell. |
| Forbidden claim | A branch or assertion a correct answer must NOT make — flattening a conditional into one value, or resolving a determining variable the corpus cannot resolve. | |
| Over-claim rate | The share of answers that assert a forbidden claim. | The metric that catches confident wrongness, this project's failure mode #1. |
| Groundedness | The share of claims in an answer that are supported by the cited context. | Judged by model, validated against hand labels. |
| Citation accuracy | Whether a cited chunk actually contains the claim it is attached to. | A citation that does not contain the claim is worse than no citation. |
| Analyser | The thing that turns text into the terms an index and a query are matched on. Four are in play: `snowball` (Postgres stemming, the original) and three voikko lemma variants that add compound splitting. | The corpus and the question must always go through the **same** analyser. They did not once, and it produced a flatteringly wrong number. |
| Cell | **One complete measurement of the whole golden set, under one analyser and one ranking setting.** 4 analysers x 3 `ts_rank` normalisations = 12 cells, all scored in a single run, all honest. | Named `analyser/normalisation`, e.g. `snowball/0`, `lemma-reasm/1`. Cells exist so a change can be attributed: everything is held still except the one thing being varied. |
| Grid | All the cells, scored in one run. What `make eval` prints. | Measuring two changes at once rather than in sequence, because they can interact — and in slice 3 they did, with the sign flipping. |
| Published cell | The single cell whose numbers the README quotes. **A recorded decision, not whichever cell scored highest.** | **Currently `lemma-reasm/0`** — moved from `snowball/0` on 27 Aug 2026 (ADR-0007) on a paired test at p=0.039, the first time the project had evidence rather than a preference. Moving it requires re-recording the baseline, and the gate fails if it moves without that. It must never migrate to whichever cell scored best: that would have published 0.857 at N=21 on p=0.25 evidence. |
| Analyser fingerprint | A hash of the lemmas the analyser produces for a fixed, committed list of probe words. Recorded in the baseline and gated. | The Finnish dictionary is a system package with no version the code can read, so a dictionary upgrade would move every published number with nothing in git changing. This is the only signal that it moved. |
| recall@k / MRR | Retrieval metrics computed against labelled chunk ids. | No model involved — these are arithmetic, and therefore the metrics to trust most. |
| Zero-overlap miss | A required chunk that was not retrieved and shares **no** normalised token with the question. It was unreachable, not out-competed. | A morphology failure. Measured, not theorised: compound splitting takes this to **0** in every `lemma-reasm` cell, at N=21 and again at N=50 across two authorities — including the Vocabulary fork, which slice 4 predicted it could not absorb and was wrong about. Every remaining miss is a ranking failure. |
| Ranked-out miss | A required chunk that matched the question but ranked below k. | A ranking failure: what IDF or length normalisation would fix. Distinguishing these two is the whole point of the miss diagnostic — without it a low score cannot say what to build next. |
| Lexical leakage | The share of a question's stemmed content words that appear verbatim in its own target chunk. | The measurable form of golden-set leakage. Reported every run and **gated to never rise** — every other metric is a score defended from falling; this is a handicap defended from rising. The floor is empirical, not zero: real harvested questions measure 39%, because a resident asking about bio-waste says "biojäte". Understates itself where the query and corpus stem the same word apart. |
| Phrasing (`harvested` / `authored`) | Where a golden question's *wording* came from. `harvested` = copied verbatim from a public resident-facing page, so it cannot have been fitted to the target chunk; `authored` = written for the set. | Only the wording, never the label — every label is hand-written from the source either way. A `harvested` claim must name its page or the loader rejects it: an unsourced claim of independence is worth nothing. |
| Judge | The model that scores answer-layer metrics. Always a different model than the one under test. | Its own agreement with hand labels is reported every run. |
| Judge–human agreement | How often the judge matches the maintainer's manual label on a fixed sample. | Reported every run. An unvalidated judge is a second opinion with extra steps. |
| Regression gate | The CI check that fails a pull request when a metric drops beyond a threshold. | The point of the whole project. |
| Golden-set leakage | Tuning against the golden set until the numbers rise without real quality rising. | The failure mode that quietly turns the harness into decoration. |

## Avoid these words

| Don't say | Say instead | Why |
|---|---|---|
| Accuracy | The named metric (`recall@5`, `groundedness`, `citation accuracy`) | "Accuracy" hides which layer failed, and retrieval failure caps everything downstream. |
| Chatbot | Answering service / QA over sources | A chat product is an explicit non-goal; the word invites scope creep toward one. |
| Document | `source` (the original) or `chunk` (the retrieved passage) | The ambiguity between the two is exactly where citation bugs hide. |
| City | Municipality | The Finnish unit is the *kunta*, which is not always a city. |
| "Turku's regulations" / "the municipality's regulations" | "the Authority's regulations" | No municipality publishes its own. Attributing a document to a municipality is the mistake the whole filter design exists to prevent. |
| I don't know | Refusal | A refusal is a designed, evaluated output, not a failure to respond. |
| Passed / green | The metric value, with the N it was computed over | A green run over a silently reduced question set is the harness's worst lie. |
| "recall@5 is 0.820" | "recall@5 is 0.820 **in `lemma-reasm/0`**" | Twelve cells produce twelve honest numbers between 0.280 and 0.820. A metric without its cell is not a claim, it is a choice of flattering number. |
| "recall@5 rose by 0.048, so X is better" | The discordant count and its exact p | Two cells are scored on the same questions: the comparison is **paired**, and an absolute interval is the wrong test. Six discordant questions are needed for p<0.05. Slice 3's override used the wrong statistic and slice 4 corrected it — the correction made the argument stronger, not weaker. |
| Keräysväline (when Lounais-Suomi is meant) / jäteastia (when Pirkanmaa is meant) | The word **that authority's own document uses**, or the resident's word ("astia", "roskis") when speaking generally | The two authorities genuinely disagree, so there is no single right word — which is why this is a **Vocabulary fork** and not a synonym to be normalised away. Using one authority's word for the other's document is how a citation ends up defending nothing. |
| Household / "two-person household" | Huoneisto count | Obligations key on dwelling units, never on the number of residents. The README's own example question uses the wrong variable. |
| "The answer" (a single value) | Conditional answer | Implies obligations are unconditional. Most are not, and flattening a branch is how a confident wrong answer gets produced. |

## Flagged ambiguities

Words we haven't fully pinned down yet — resolve before they cause a bug.

- ~~**"Municipality" — the *kunta*, or the regional waste authority?**~~ **RESOLVED 26 Aug 2026.**
  The Authority. Verified against sources rather than assumed: regulations are uniform across every
  municipality in an authority's area (*"Määräykset ovat yhtenäiset kaikissa jätelautakunnan
  toimialueen kunnissa"*), and Turku is 1 of 18 municipalities under one board. The filter keys on
  the Authority; the *kunta* is input only. Note this contradicts `README.md:18-19`, which claims
  municipalities each publish their own — that line needs correcting.
- ~~**What counts as one "claim"** for groundedness?~~ **RESOLVED 26 Aug 2026.** A claim is one
  **required branch**, hand-enumerated in the golden-set entry. The denominator is therefore set by
  hand per question rather than inferred from the answer text, which is what makes it stable
  run-to-run and what lets the judge answer narrow yes/no questions instead of grading prose.
- ~~**Whether a partially-supported answer is a refusal case.**~~ **PARTLY RESOLVED 26 Aug 2026.**
  A missing *determining variable* is **not** a refusal — it is a conditional answer with the
  condition surfaced. Still open: whether a question whose *subject matter* is genuinely absent
  from the corpus, as opposed to merely under-determined, is the only true refusal case.

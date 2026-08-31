# SPEC — a shareable, OTP-gated demo of the `ask` surface

**Written:** 31 Aug 2026 · **Weight:** Standard · **Status:** tracer 1 landed, tracer 2 in build

Tracer 1 (`fi-rag-eval ask`) landed at `4b0b744` **without a spec** — the direction was agreed
mid-session and built the same day. It is recorded here retroactively, with its acceptance criteria
stated as they were actually met, because a tracer with no spec is a tracer whose verdict nobody can
check. That is a spec delta on this document's own first line, and it is the honest place for it.

## Problem

Every number this project publishes describes a pipeline nobody outside this machine can touch. The
retrieval headline (recall@5 = 0.820 at leakage 0.550 in `lemma-reasm/0`) and the answer-layer
figures (branch coverage 0.472, withheld pending judge–human agreement) are defensible and
unwatchable. `DESIGN.md:151` names the gap in the definition of done: *"A public URL or a 90-second
recording demonstrates it working."*

The thing worth demonstrating is not that a model answers in Finnish. It is that **the same question
gets two different, both-correct answers in two jurisdictions, and a question the corpus cannot
answer gets refused while five plausible excerpts sit on screen.** Tracer 1 proved that pair exists
(Turku 4/8/16 weeks, Tampere 4/8 weeks, forked vocabulary, $0.0350 for three real calls). Nobody can
see it without a checkout, Docker, `poppler-utils`, `libvoikko1`, `voikko-fi`, a Groq key and a
gateway.

**For whom:** a reader of this repository — a hiring manager, a reviewer, the Owner demonstrating it
live — who has a browser and no intention of installing voikko.

## Solution shape

One server-rendered page over the retrieval the harness already measures, reachable through a link
that carries a capability token. No build step, no `node_modules`, no client framework.

- **Data.** The corpus Postgres, unchanged. The demo's own state — tokens, per-token counters, the
  global daily counter — is *new* and has the **opposite persistence requirement** from the corpus
  (`compose.yaml:38-41` puts the corpus data directory on `tmpfs` because every ingest is a full
  reload). That collision is ADR-0013's subject, and it is the same argument ADR-0009 already made
  for the gateway's spend ledger, now for the third time.
- **Logic.** `ask.ask`, called and not re-implemented. This is the load-bearing constraint of the
  whole MVP: *a second retrieval behind the demo would drift from every published number and both
  would still look fine.* Enforced, not documented — see AD6.
- **Surface.** `GET /` renders the form; `POST /ask` re-renders the page with the result. Starlette
  + uvicorn. **POST, never GET**, so a resident's question never enters an access log, a browser
  history or a proxy log. `ask.ASK_ID` already refuses to derive an id from the question text
  (`ask.py:60-68`); this is the same rule applied to the transport.
- **Words.** Finnish, and `CONTEXT.md`'s *Avoid these words* table binds the copy: the page never
  attributes regulations to a *kunta* ("Turun jätehuoltomääräykset" is the mistake the entire filter
  design exists to prevent), never says *chatbot*, and never renders a refusal as *"en tiedä"* — a
  refusal is a designed output, so it is labelled as one and shown **with** the excerpts it declined
  to answer from.

## Tracer slices

1. **`fi-rag-eval ask` — an unlabelled question, answered.** **LANDED `4b0b744`, 31 Aug 2026.**
2. **The endpoint and the page.** Localhost only, no gate. After this it is watchable.
   *(blocked by 1)*
3. **The OTP gate and the caps.** 10 queries per token, 24h lifetime, 200 queries/day globally.
   Token in the link (`/d/AB12-CD34`). Every rule seen red on purpose. *(blocked by 2)*
4. **One container image.** `make docker-build` currently exits 1 on purpose. *(blocked by 3)*

Each is demoable alone: 2 is a working local demo; 3 is a link that can be handed to someone; 4 is
the artifact a deploy would take.

## Non-goals

- **Deploying anything.** Every tracer here runs under `docker compose up` on this machine. Where
  Postgres lives in cloud is the one expensive decision and it is a `/ship` decision needing the
  Owner's keystroke. **Additionally blocked** — see Open questions.
- **Auth, accounts, sessions, or multi-tenancy.** `DESIGN.md:52` puts these out of scope and they
  stay out. The OTP token is a **spend control with a link for a handle**, not a login: it
  identifies no person, stores no identity, and grants no privilege beyond N answers. ADR-0013
  states this explicitly so the tracer cannot be read as scope creep against a binding non-goal.
- **A chat product.** No conversation memory, no follow-up turns, no history. One question, one
  answer, one page. `DESIGN.md:51` and `CONTEXT.md`'s *chatbot* entry.
- **Streaming the answer.** An answer takes ~20–50s and a token stream would be nicer. It is a
  second rendering path for the same content, and the honest minimum — a visible waiting state — is
  six lines of inline JS.
- **Making the demo a measurement.** Nothing typed into this page enters the golden set, moves a
  published number, or is scored. It is a **surface over** the instrument, never an input to it.
- **Changing any published number.** No retrieval change, no prompt change, no cell change.

## Non-negotiables carried in from the project

- **Reasoning stays on.** Measured as a *correctness* knob, not a performance one: with reasoning
  off the answerer reproduced the same `17 §` inversion that disqualified `gpt-oss-20b` in tracer 1.
  ~5.3x the dollars. Never turned off to save money without scoring it.
- **The published cell is the demo's cell.** `evaluate.PUBLISHED` (`lemma-reasm/0`), reached through
  `ask.ask`. A demo on a different cell would be a demo of a pipeline nobody measured.
- **Every refusal is free.** Tracer 1's discipline — an injected answerer that **raises** if called —
  is carried onto every new surface. On a paid public endpoint this is a spend control.

## Acceptance criteria

Each names how it is proven: `test:` an automated test, `live:` a real exercise with pasted
evidence, `review-only:` neither, and labelled as such. A tracer's verdict is the **worst** among
its criteria.

### Tracer 1 — `fi-rag-eval ask` (landed, recorded retroactively)

| # | Criterion | Proven by |
|---|---|---|
| AD-1.1 | An arbitrary question, in one municipality's jurisdiction, is answered from the published cell's top-k | `test:` `test_ask.py::TestItRetrievesTheWayTheHarnessMeasures` · `live:` 3 real calls, $0.0350 |
| AD-1.2 | Retrieval is the harness's, not a second implementation | `test:` cell asserted `lemma-reasm/0`, k=5, positions 1–5 |
| AD-1.3 | Every refusal path costs zero | `test:` 5 paths, answerer raises `_Spent`, **seen red** |
| AD-1.4 | The question text never becomes an id | `test:` `test_the_question_id_carries_no_part_of_the_question` |
| AD-1.5 | The authority term is load-bearing **on its own** | `test:` `TestTheAUTHORITYTermIsLoadBearingOnItsOwn`, **seen red** with the date term intact |

### Tracer 2 — the endpoint and the page

| # | Criterion | Proven by |
|---|---|---|
| AD1 | `GET /` is 200 and its `<select>` holds exactly `municipalities(manifest)` — Turku and Tampere in, **Sastamala out** | `test:` TestClient |
| AD2 | `POST /ask` renders the resolved authority and cell, the retrieved top-5 **addresses with citations**, the answer, the citations, and the **measured** cost | `test:` TestClient + canned answerer · `live:` one real query |
| AD3 | All five `AskError` paths render a refusal page and **spend nothing** | `test:` parametrised, answerer that **raises**, **seen red** |
| AD4 | No municipality selected → never reaches the answerer, and the page says why | `test:` raising answerer |
| AD5 | The same question in Turku and Tampere returns **disjoint** retrieved addresses *through HTTP* | `test:` TestClient |
| AD6 | `serve.py` contains **no second retrieval** | `test:` the default asker **is** `ask.ask` by identity, **and** an AST check that `serve.py` never names `db.search`, `cell_query_lexemes`, `or_tsquery` or `snowball_stopwords` |
| AD7 | The question never reaches a URL or a log line | `test:` `GET /ask` is 405; the route reads the body, never the query string |
| AD8 | A question containing markup is **escaped** on the page | `test:` `<script>` round-trip; enforced by types — the renderer accepts only pre-escaped `Html` |
| AD9 | It is watchable: `docker compose up`, `make serve`, one real question in a browser | `live:` pasted terminal output and the rendered answer |
| AD10 | A question over `MAX_QUESTION_CHARS` (500) is refused **before** the connection and the answerer | `test:` both stubs raise, **seen red** |
| AD11 | A request body over `MAX_BODY_BYTES` (8 KiB) is refused **while still streaming** | `test:` 413, **seen red** |

### Tracer 3 — the OTP gate and the caps

Every one of these is a **cap on real money** and none counts as met until it has been **seen red on
purpose**. A cap never watched failing is decoration (`PRINCIPLES.md` #2).

| # | Criterion | Proven by |
|---|---|---|
| AD12 | A request with **no valid token** never reaches the answerer — i.e. never **spends** | `test:` raising answerer, **seen red** |
| AD13 | An **expired** token (>24h after issue) never answers | `test:` injected clock, **seen red** |
| AD14 | An **over-cap** token (>10 queries) never answers | `test:` **seen red** |
| AD15 | A **revoked** token never answers | `test:` **seen red** |
| AD16 | The **global daily ceiling** (200) stops every token | `test:` **seen red** |
| AD17 | The municipality hard filter still refuses **on the gated surface** | `test:` out-of-jurisdiction question through HTTP with a valid token |
| AD18 | A cap is charged **once per answered query**, and a refused query that spent nothing is **not** charged | `test:` counter asserted across a refusal and an answer |
| AD19 | Token state survives a container restart | `live:` `docker compose restart`, same link still works with its counter intact |

### Tracer 4 — the image

| # | Criterion | Proven by |
|---|---|---|
| AD20 | `make docker-build` produces an image and **exits 0** | `live:` build output |
| AD21 | `docker compose up` serves the gated demo with **no host Python, no host voikko** | `live:` a real query answered from inside the container |
| AD22 | The image's `fi-rag-eval eval` reproduces the published table | `live:` the table, from the container |

## Open questions (for the Owner)

1. **BLOCKS DEPLOY, NOT BUILDING — the logging tension is unresolved.** `DESIGN.md:35` specifies
   structured per-query logging of latency, tokens, cost and retrieved ids. `DESIGN.md:74` and
   `CLAUDE.md` say *"No personal data, ever… Never log raw end-user queries."* A resident's real
   question can itself be personal data (*"Naapurini Matti polttaa risuja"* is in `test_ask.py` for
   exactly this reason). A public demo endpoint is precisely the case `CLAUDE.md` says to resolve
   *"before any query log leaves this machine."* **Not decided.** Tracers 2–4 log no question text
   at all, which sidesteps rather than resolves it — and sidestepping also means the demo produces
   **no** per-query ops record, so `DESIGN.md:35` stays unmet.
2. **The cap arithmetic does not close at the current ceiling.** Measured cost per answer on the
   `ask` path is **$0.0084–$0.0177** (3 calls, `4b0b744`); the answer phase averaged ~$0.021. At
   **200 queries/day** that is **$1.70–$4.20/day**, so the **$25/month** ceiling (ADR-0008) is
   exhausted in **6–15 days of a saturated daily cap** and the gateway's virtual key starts
   returning 429 mid-demo. Raised before building the caps; the numbers are the Owner's.
3. **What happens when a token is exhausted or the day is capped?** A labelled honest empty state,
   never *"coming soon"* — but whether it names the cap, offers a mailto, or simply says the demo is
   closed for the day is a product call.

## Decisions

- **Starlette + uvicorn, one server-rendered page, no build step** (Owner, 31 Aug 2026). Rejected
  alternatives and the reasoning go in ADR-0013 alongside the access model, because the two are one
  decision: a page that must survive being linked to a stranger is what rules out a client-side
  framework fetching a JSON API with a token in it.
- **POST, never GET, for the question** (this spec, above). A GET puts the asker's words in three
  logs nobody controls.
- **The access model — capability token in the link, 10/token, 24h, 200/day, Postgres-backed** →
  **ADR-0013**, written at tracer 3 when the store's location is decided, with rejected alternatives.
- **Tracer 1 is recorded retroactively** rather than left unspecified. See this document's opening.

## Spec deltas

*(dated, as they happen — `ANTI-PATTERNS.md`: diverging is normal, diverging unrecorded is the
defect)*

1. **31 Aug 2026 — this spec was written after tracer 1, not before it.** Tracer 1's criteria are
   transcribed from tests that already pass, so they are a *record*, not a prediction. No verdict in
   the tracer-1 table may be read as having been pre-registered.

---

## Tracer slice 2 — measured result (31 Aug 2026)

`fi-rag-eval serve` on `127.0.0.1:8080`, cell `lemma-reasm/0`, k=5, model `qwen/qwen3.6-27b`,
reasoning on. **One** real call was spent, deliberately.

A verdict per criterion; the tracer's is the **worst** among them.

| AC | Verdict | Evidence |
|---|---|---|
| AD1 | **MET, seen red** | `GET /` 200, 7101 bytes. 34 options, Turku and Tampere present, **Sastamala absent**, and `<option value="" selected>` first. Red when the empty option loses `selected`. |
| AD2 | **MET** | `test:` full page asserted. `live:` HTTP 200 in **14s**, jurisdiction line `Turku → Lounais-Suomen jätehuoltolautakunta (lounais-suomi), haku lemma-reasm/0`, five addresses with citations, **$0.0161** / 8420 tokens / 4307 reasoning, read from the gateway. |
| AD3 | **MET, seen red** | All five paths 400 with no model call. Red when `run` calls the answerer first. |
| AD4 | **MET** | Empty *kunta* → `resolve_municipality` refuses; the answerer that raises was never reached. |
| AD5 | **MET, seen red** | Turku and Tampere return **disjoint** address sets through HTTP; neither page contains the other's authority key. Red when `serve` hard-codes the *kunta*. |
| AD6 | **MET, seen red** | Default asker **is** `ask.ask` by identity; AST check finds zero forbidden names in `serve.py` and **all five** in `ask.py`, so the list is not stale. Red on adding `db.search`. |
| AD7 | **MET, seen red** | `GET /ask` → **405**. Red on adding `GET` to the route. |
| AD8 | **MET, seen red** | `</textarea><script>` escaped in the shell and through HTTP. Enforced by type: `render` takes only `Html`. Red on `Html(question)`. |
| AD9 | **MET** | The live run above, plus all six refusal paths exercised through the running server. |
| AD10 | **MET, seen red** | 501 characters → 400, **before** the connection and the answerer (both stubs raise). 500 characters proceeds, so the boundary is pinned from both sides. |
| AD11 | **MET, seen red** | 8 KiB + 1 → **413**, counted while streaming. Red when the counter is bypassed. |

**Tracer verdict: MET.** Every criterion this tracer claimed, met, and nine of them watched failing.
Nothing about tracer 3 is claimed: **this surface has no access gate** (`REVIEW-DEBT.md`).

### What the live run found that 470 green tests did not

Two Finnish copy defects, caught by **reading the page**, not by any assertion:

1. **`"jätehuoltolautakuntan"`** — a hand-rolled genitive. `lautakunta` → `lautakunnan`; the naive
   `f"{name}n"` ignores consonant gradation, which is the precise hazard this project runs voikko
   for. The name is no longer inflected at all.
2. **English prose inside a Finnish sentence** — Sastamala's coverage detail, with a doubled
   "only … only" inherited from the manifest. `corpus/manifest.yaml` now carries the authority's
   **own Finnish** from `1 §`, quoted verbatim by both messages.

And one disclosure defect, caught by asking what `str(exc)` actually contains:

3. **`db.connect`'s message embeds the database URL, credentials included**, and it was being
   rendered on the page. `db.DatabaseError` and `AnswerError` messages now never reach the page —
   they go to stderr and the reader gets a Finnish "temporarily unavailable". A test plants
   `s3cr3t-p4ss` in the message and asserts it is absent from the response.

`AskError` now carries **both** texts, required at every raise site so mypy names an omission: the
English for the CLI and the suite, `finnish` for the page.

### Spec deltas from this tracer

2. **31 Aug 2026 — two criteria were added mid-tracer, not pre-registered.** AD10 (question length)
   and AD11 (body bytes) are spend controls discovered while writing the route; they are recorded as
   additions rather than presented as having been planned.
3. **31 Aug 2026 — `python-multipart` was rejected and the form parser is stdlib.** Starlette 1.6's
   `request.form()` asserts on it for *any* content type. A file-upload parser has no business behind
   this surface, so the body is streamed against a byte cap and parsed with `urllib.parse.parse_qsl`.
   A multipart body therefore yields none of the named fields and lands on the empty-question
   refusal — asserted, because `parse_qsl` does not reject such a body, it produces a junk key.
4. **31 Aug 2026 — a corpus data file was edited during a surface tracer.** See `REVIEW-DEBT.md`.
   No published number can move, and it is recorded rather than left silent.

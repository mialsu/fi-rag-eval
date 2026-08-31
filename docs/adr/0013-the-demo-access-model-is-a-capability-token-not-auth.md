# ADR-0013 — the demo's access model is a capability token in a link, and the money cap is denominated in money

- **Date:** 2026-08-31
- **Status:** accepted
- **Amends:** ADR-0009's *"No published port"* for `litellm-postgres`, partially — see Decision 2.
- **Relates to:** ADR-0008 (the $25/month provider ceiling this sits under).

## Context

MVP tracer 2 landed a demo page that answers real questions at a real price (**$0.0161** for the
one call it was exercised with, measured at the gateway) and has **no access control at all**. It is
bound to loopback and `REVIEW-DEBT.md` forbids exposing it. Tracer 3 exists to make it shareable,
which means deciding who may spend and how much — and every one of those rules is a cap on the
Owner's money, so each needs the enforcer that fails when it is broken.

Four facts were established against the code, not assumed:

1. **The corpus database cannot hold this state.** `compose.yaml` puts `postgres`'s data directory on
   **tmpfs**, deliberately, because every ingest is a full reload (`db.SCHEMA` drops `chunk`,
   `source` and `authority`). A token issued into it dies on the next container restart, so a link
   handed to someone would stop working with no explanation. Note the *ingest* is not the problem —
   `SCHEMA` drops three named tables and would leave a token table alone. The **tmpfs** is.
2. **`litellm-postgres` publishes no port.** Verified: `docker compose ps` shows `5432/tcp` with no
   host mapping. ADR-0009 chose that on the ground that *"Nothing outside this compose project has
   any business reading the spend ledger."*
3. **Its volume is already initialised.** `fi-rag-eval_litellm-spend` exists, and a Postgres image
   runs `/docker-entrypoint-initdb.d/*.sql` **only on first init** — so an init script for a second
   database would be dead code that reads like setup. Postgres has no `CREATE DATABASE IF NOT
   EXISTS` and cannot run `CREATE DATABASE` inside a transaction.
4. **The query caps the Owner decided do not fit the budget.** 10 queries per token, 24-hour
   lifetime and 200 queries/day globally were decided before the cost per answer was measured on
   this path. At **$0.0084–$0.0177** per answer, 200/day is **$1.70–$4.20/day** — ADR-0008's
   **$25/month** is gone in **6–15 days** of a saturated cap, at which point the gateway's virtual
   key starts returning 429 mid-answer.

`DESIGN.md:52` additionally puts *"Multi-tenant auth, user accounts, conversation memory"* out of
scope, and that non-goal is binding. Whatever this is, it must not be a login.

## Decision

**1. Access is a capability token carried in the link (`/d/AB23-CD45`), and it is a spend control,
not authentication.** It identifies no person, stores no identity, has no password, no session and
no recovery, and grants exactly one privilege: N answers before it stops. That is why it does not
contradict `DESIGN.md:52` — the thing that non-goal forbids is a system that knows *who* you are, and
this one deliberately cannot. Anyone holding the link is the bearer; that is the whole model, and it
is the correct amount of machinery for handing a page to a reviewer.

Eight characters from a 32-symbol alphabet with `O`, `0`, `I` and `1` removed, from `secrets`,
formatted `AB23-CD45`. 40 bits: not a secret worth attacking when the *global* daily ceiling is 200
queries, and readable aloud.

Note that `AB12-CD34`, the shape sketched while shaping this tracer, is **not a producible token** —
it contains `1`. The *shape* is what was decided; the alphabet then excluded the four glyphs that
survive being read aloud worst. A test pins this so nobody later widens the alphabet to make an
illustration valid.

**2. The state lives in a `demo` database inside the `litellm-postgres` container, and that container
now publishes `127.0.0.1:5435:5432`.** The demo's state and the gateway's spend ledger have the
**same** persistence requirement — both must survive `make db-down` or the cap they enforce resets —
and `compose.yaml`'s own rule is that one container can only have one persistence policy. So they
share the container and the existing volume, in **separate databases**, so that nothing of ours ever
touches LiteLLM's migrations.

Publishing the port **partially reverses ADR-0009's "No published port"**, and the reversal is stated
rather than quietly made. Its reasoning was that nothing outside the compose project should read the
spend ledger; with the demo's state in that container, *our own application* is such a client and
runs on the host until tracer 4 moves it into compose. The port is bound to **`127.0.0.1`
explicitly** — unlike the corpus database's `5434:5432`, which binds every interface — so the
exposure is one machine, not one network.

**3. The `demo` database and its tables are created by the application, idempotently.** Fact 3 makes
an init script dead code. `ensure_database` connects to the server's `postgres` database with
autocommit, checks `pg_database`, and issues `CREATE DATABASE` only if absent; the tables are
`CREATE TABLE IF NOT EXISTS`. **This schema is never dropped** — the exact opposite of `db.SCHEMA`,
and the difference is load-bearing: a corpus that survives an ingest is a corpus that has drifted
from the manifest, while a token store that does *not* survive is a link that broke.

**4. A query is reserved before the answer and refunded if nothing was spent.** Not
check-then-charge: two requests could both pass a check at 9 of 10. Not charge-inside-the-answer's
transaction either, because that holds a row lock across a 14–50 second model call. Reserve-then-
refund is race-free without either, and it fails in the safe direction — a crash between the answer
and the refund over-counts by one and can never under-count. A cap on money must round against the
spender.

**5. There are four enforcers, and the fourth is denominated in dollars.** The Owner's query caps
stand unchanged as *fairness* controls, and a monthly **$10.00** measured-spend ceiling is added as
the *money* control:

| Enforcer | Limit | What it is for |
|---|---|---|
| per token | 10 queries | one visitor cannot drain the demo |
| per token | 24 hours from issue | a shared link stops mattering |
| global | 200 queries/day | one day cannot drain the month |
| **global** | **$10.00/month, measured** | **the money** |

$10 leaves ~$15/month of ADR-0008's $25 for the harness's own paid runs — an answer-phase run is
$0.76 and a judge run $0.07, so ~19 full runs survive a **saturated** demo. The demo therefore stops
**before** the provider does, which is the point: a saturated demo must never be able to starve
`answer --all`, because that command is how every published answer-layer number exists.

The dollar figure is read back from the gateway's own `response_cost` and accumulated, never
estimated — the same rule as every other cost in this project.

## Rejected alternatives

- **A fourth Postgres container, `demo-postgres`, with its own volume** — rejected by the Owner on
  31 Aug 2026. It follows ADR-0009's precedent most literally and needs no port reversal, but it puts
  a fourth Postgres container on a machine already running several projects' databases, for state
  whose persistence requirement is identical to the ledger already sitting in one.
- **The corpus database, accepting tmpfs** — rejected. It is the smallest change and it makes AD19
  ("token state survives a restart") unprovable *and untestable*, because the property is false. A
  link that silently stops working after `make db-down` is worse than no link.
- **Renaming `litellm-postgres` to something that describes both databases** — rejected. The name no
  longer describes everything the container holds, which is a real cost. But renaming the service
  changes the gateway's `DATABASE_URL` host, and that container holds the **spend ledger the $25
  ceiling is enforced from**. Better naming is not worth any risk to the enforcer; the mismatch is
  documented in `compose.yaml` instead.
- **A shared password or a single `?key=` query parameter** — rejected. A query parameter puts the
  credential in the access log, the browser history and every proxy — the exact reason tracer 2 made
  the question travel in a POST body. And one shared secret has no per-visitor cap, so the first
  enforcer in the table above could not exist.
- **Real authentication: accounts, email, a session** — rejected, and forbidden. `DESIGN.md:52`.
  It would also make the demo hold personal data, which `CLAUDE.md` forbids outright and which the
  unresolved `DESIGN.md:35`/`:74` logging tension already blocks.
- **A hashed token in the database rather than the token itself** — rejected for now, and this one is
  a genuine weakening recorded as such. Hashing would mean a database read could not recover a live
  link. But the token is a bearer capability worth at most 10 answers (~$0.18), the store is loopback
  only, and hashing costs the `--list` command its ability to reprint a link the Owner issued and
  mislaid. Revisit if the demo is ever exposed to more than a handful of reviewers.
- **Lowering the daily cap to ~50 so the month is implied** — rejected by the Owner. One kind of unit
  is simpler, but the month would be implied *at today's price*: a dearer model, or reasoning left on
  where it had been off, moves the real ceiling with nothing in git changing. A cap that guards money
  is denominated in money.
- **Relying on the gateway's `$25/30d` virtual-key budget alone** — rejected as the *primary* stop,
  kept as the backstop it already is. It is a real, measured enforcer (ADR-0009 watched it return
  429), but it fails by breaking the demo mid-answer with a 502 for whoever happens to be holding the
  link, rather than by declining politely beforehand with a page that says why.

## Consequences

**Easy.** Handing someone a link and knowing the worst case in dollars. Revoking one. Restarting the
stack without breaking a link that is already out. Testing expiry without sleeping, because the clock
is injected.

**Hard, and we live with it.** The bearer model means a forwarded link is a valid link — there is no
way to tell one reviewer from another, by design. `--list` can reprint any live token, because they
are stored in the clear. The `litellm-postgres` name no longer describes its contents. And the
monthly ceiling is enforced on **measured** spend, so it can only stop the query *after* the one that
crossed it: the honest guarantee is "one answer of overshoot, then nothing", exactly as
`answer.TokenBudget` already words it for the token ceiling.

**What this does not do.** It is not a rate limit — ten queries can arrive in ten seconds. It does
not resolve the `DESIGN.md:35`/`:74` logging tension, which still blocks any deploy, and it adds no
logging of its own beyond counters that contain no question text. And it says nothing about who may
reach the port: tracer 3 leaves `--host` warning rather than refusing, because the token is now the
gate and the bind address is the Owner's deliberate keystroke.

"""Who may spend, and how much. Four enforcers, all denominated on purpose.

`SPEC-mvp-demo` tracer 3, ADR-0013. Every rule here is a cap on real money, so
none of them counts as built until it has been **watched failing** -- a cap never
seen red is decoration, and this one guards a bill.

The access model is a **capability token in a link**, not authentication. It
identifies no person, stores no identity, has no password and no session, and
grants exactly one privilege: N answers before it stops. That is why it does not
contradict `DESIGN.md:52`'s "no multi-tenant auth" -- the thing that non-goal
forbids is a system that knows who you are, and this one deliberately cannot.

Four enforcers, and the fourth is the only one denominated in money:

| per token | 10 queries          | one visitor cannot drain the demo |
| per token | 24 hours from issue | a shared link stops mattering     |
| global    | 200 queries/day     | one day cannot drain the month    |
| global    | $10.00/month        | THE MONEY                         |

The query caps are *fairness* controls and were the Owner's. The dollar ceiling
exists because they do not fit the budget on their own: at the measured
$0.0084-$0.0177 per answer, 200/day is $1.70-$4.20/day and ADR-0008's $25/month
is gone in 6-15 days. A cap that guards money is denominated in money, or a
dearer model moves the real ceiling with nothing in git changing.

**This schema is never dropped**, which is the exact opposite of `db.SCHEMA` and
the difference is load-bearing. A corpus that survives an ingest has drifted from
the manifest; a token store that does *not* survive is a link that broke. It also
lives in a different database from the corpus, because `compose.yaml` puts the
corpus on **tmpfs** -- see ADR-0013 for why that rules the corpus database out.

**A query is reserved before the answer and refunded if nothing was spent.** Not
check-then-charge, which lets two requests both pass at 9 of 10; not a row lock
held across a 14-50 second model call either. Reserve-then-refund is race-free
without either and fails in the safe direction: a crash between the answer and
the refund over-counts by one and can never under-count.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg import sql

DEMO_URL_ENV = "FI_RAG_EVAL_DEMO_DATABASE_URL"
DEFAULT_DEMO_URL = "postgresql://litellm:litellm@localhost:5435/demo"
"""The `demo` database inside the `litellm-postgres` container (ADR-0013).

Not the corpus database: that one is on tmpfs, so a token issued into it dies on
the next container restart and a link handed to someone stops working with no
explanation.
"""

QUERIES_PER_TOKEN = 10
TOKEN_LIFETIME = timedelta(hours=24)
QUERIES_PER_DAY = 200
DOLLARS_PER_MONTH = 10.00
"""The money enforcer, set by the Owner on 31 Aug 2026.

$10 of ADR-0008's $25/month, leaving ~$15 for the harness's own paid runs: an
answer-phase run is $0.76 and a judge run $0.07, so ~19 full runs survive a
**saturated** demo. The demo therefore stops *before* the provider does, and a
saturated demo can never starve `answer --all` -- which is how every published
answer-layer number exists.
"""

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
"""32 symbols, with `O`, `0`, `I` and `1` removed so a link can be read aloud."""

TOKEN_CHARS = 8
"""40 bits. Not a secret worth attacking when the GLOBAL daily ceiling is 200."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_token (
    token        text PRIMARY KEY,
    issued_at    timestamptz NOT NULL,
    expires_at   timestamptz NOT NULL,
    query_limit  integer NOT NULL,
    queries_used integer NOT NULL DEFAULT 0,
    cost_usd     double precision NOT NULL DEFAULT 0,
    revoked_at   timestamptz,
    note         text NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS demo_day (
    day      date PRIMARY KEY,
    queries  integer NOT NULL DEFAULT 0,
    cost_usd double precision NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS demo_month (
    month    text PRIMARY KEY,
    queries  integer NOT NULL DEFAULT 0,
    cost_usd double precision NOT NULL DEFAULT 0
);
"""
"""No DROP. See the module docstring: the opposite of `db.SCHEMA`, on purpose."""


class AccessError(RuntimeError):
    """The demo's own state is unreachable or unusable."""


class Denied(RuntimeError):
    """The request may not spend. Carries the resident's own Finnish.

    Two texts for the same reason `AskError` carries two: the English names the
    enforcer for a maintainer reading stderr, the Finnish is what the person
    holding the link reads. Required, so a new enforcer cannot ship without the
    half a stranger sees.
    """

    def __init__(self, message: str, *, finnish: str) -> None:
        super().__init__(message)
        self.finnish = finnish


Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Token:
    """One issued capability, as stored."""

    token: str
    issued_at: datetime
    expires_at: datetime
    query_limit: int
    queries_used: int
    cost_usd: float
    revoked_at: datetime | None
    note: str

    @property
    def remaining(self) -> int:
        return max(0, self.query_limit - self.queries_used)

    def link(self, base: str) -> str:
        return f"{base.rstrip('/')}/d/{self.token}"


def demo_url() -> str:
    return os.environ.get(DEMO_URL_ENV, DEFAULT_DEMO_URL)


def new_token() -> str:
    """`AB12-CD34`. Two groups of four, from `secrets`."""
    raw = "".join(secrets.choice(ALPHABET) for _ in range(TOKEN_CHARS))
    return f"{raw[:4]}-{raw[4:]}"


def normalise(token: str) -> str:
    """Accept a link's token however it was typed, without accepting a wrong one.

    Case and a missing dash are transcription noise, not a different capability --
    the alphabet has no lowercase and exactly one dash position. Anything else is
    left alone so it simply fails to match.
    """
    stripped = token.strip().upper().replace("-", "")
    if len(stripped) != TOKEN_CHARS or any(c not in ALPHABET for c in stripped):
        return token.strip()
    return f"{stripped[:4]}-{stripped[4:]}"


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


def ensure_database(url: str | None = None) -> str:
    """Create the `demo` database if it is absent, and return its URL.

    Done here rather than in `docker-entrypoint-initdb.d`: that runs **only on
    first init** and the `litellm-spend` volume is already initialised, so an init
    script would be dead code that reads like setup. Postgres has no
    `CREATE DATABASE IF NOT EXISTS` and cannot run `CREATE DATABASE` inside a
    transaction, hence the explicit check and `autocommit`.
    """
    target = url or demo_url()
    head, _, name = target.rpartition("/")
    if not name:
        raise AccessError(f"{DEMO_URL_ENV} names no database: {target!r}")
    try:
        with psycopg.connect(f"{head}/postgres", autocommit=True) as admin, admin.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except psycopg.Error as exc:
        raise AccessError(
            f"cannot reach the demo's state database: {exc}\n"
            f"Start it with `make services-up`, or point {DEMO_URL_ENV} somewhere else."
        ) from exc
    return target


def connect(url: str | None = None) -> psycopg.Connection[tuple[object, ...]]:
    target = url or demo_url()
    try:
        return psycopg.connect(target, autocommit=False)
    except psycopg.Error as exc:
        raise AccessError(
            f"cannot reach the demo's state database at {target}: {exc}\n"
            f"Start it with `make services-up`, or point {DEMO_URL_ENV} somewhere else."
        ) from exc


def create_schema(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    """Idempotent, and it never drops anything. Commits: there is nothing to roll
    back to, and a half-created store would deny every request."""
    with conn.cursor() as cur:
        cur.execute(sql.SQL(SCHEMA))
    conn.commit()


def open_store(url: str | None = None) -> psycopg.Connection[tuple[object, ...]]:
    """The one call a caller needs: database created, schema present, connected."""
    target = ensure_database(url)
    conn = connect(target)
    create_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Issuing, listing, revoking
# ---------------------------------------------------------------------------


def issue(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    note: str = "",
    queries: int = QUERIES_PER_TOKEN,
    lifetime: timedelta = TOKEN_LIFETIME,
    now: Clock = utc_now,
) -> Token:
    if queries < 1:
        raise AccessError(f"a token is worth at least one query, not {queries}")
    if lifetime <= timedelta(0):
        raise AccessError(f"a token must outlive its issue, not {lifetime}")
    issued = now()
    token = Token(
        token=new_token(),
        issued_at=issued,
        expires_at=issued + lifetime,
        query_limit=queries,
        queries_used=0,
        cost_usd=0.0,
        revoked_at=None,
        note=note,
    )
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO demo_token (token, issued_at, expires_at, query_limit, note) "
            "VALUES (%s, %s, %s, %s, %s)",
            (token.token, token.issued_at, token.expires_at, token.query_limit, token.note),
        )
    conn.commit()
    return token


def _row_to_token(row: tuple[object, ...]) -> Token:
    return Token(
        token=str(row[0]),
        issued_at=_as_datetime(row[1]),
        expires_at=_as_datetime(row[2]),
        query_limit=int(str(row[3])),
        queries_used=int(str(row[4])),
        cost_usd=float(str(row[5])),
        revoked_at=None if row[6] is None else _as_datetime(row[6]),
        note=str(row[7]),
    )


def _as_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise AccessError(f"expected a timestamp from the store, got {value!r}")
    return value


_COLUMNS = "token, issued_at, expires_at, query_limit, queries_used, cost_usd, revoked_at, note"


def tokens(conn: psycopg.Connection[tuple[object, ...]]) -> tuple[Token, ...]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM demo_token ORDER BY issued_at DESC")
        return tuple(_row_to_token(row) for row in cur.fetchall())


def revoke(
    conn: psycopg.Connection[tuple[object, ...]], token: str, *, now: Clock = utc_now
) -> Token:
    key = normalise(token)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE demo_token SET revoked_at = COALESCE(revoked_at, %s) "
            f"WHERE token = %s RETURNING {_COLUMNS}",
            (now(), key),
        )
        row = cur.fetchone()
    if row is None:
        raise AccessError(f"no such token: {token!r}")
    conn.commit()
    return _row_to_token(row)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reservation:
    """One query, already counted. Refund it if nothing was spent."""

    token: str
    day: str
    month: str
    remaining_after: int


def reserve(
    conn: psycopg.Connection[tuple[object, ...]],
    token: str,
    *,
    now: Clock = utc_now,
    queries_per_day: int = QUERIES_PER_DAY,
    dollars_per_month: float = DOLLARS_PER_MONTH,
) -> Reservation:
    """Charge one query up front, or raise `Denied` having charged nothing.

    Every check and the increment happen in ONE transaction with the token row
    locked, so two simultaneous requests cannot both pass at 9 of 10. The lock is
    released before the model is called -- the answer happens outside this
    function entirely, which is the whole reason it is reserve-then-refund.

    The order of the checks is the order of blame: the token's own state first, so
    a visitor with a dead link is told that rather than being told the demo is
    busy.
    """
    key = normalise(token)
    moment = now()
    day = moment.date().isoformat()
    month = moment.strftime("%Y-%m")
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM demo_token WHERE token = %s FOR UPDATE", (key,))
            row = cur.fetchone()
            if row is None:
                raise Denied(
                    f"no such token: {key!r}",
                    finnish=(
                        "Tämä linkki ei kelpaa. Demoon pääsee vain henkilökohtaisella "
                        "linkillä, ja tämä ei ole voimassa."
                    ),
                )
            found = _row_to_token(row)
            if found.revoked_at is not None:
                raise Denied(
                    f"token {key!r} was revoked at {found.revoked_at.isoformat()}",
                    finnish="Tämä linkki on peruutettu, eikä sillä voi enää kysyä.",
                )
            if moment >= found.expires_at:
                raise Denied(
                    f"token {key!r} expired at {found.expires_at.isoformat()}",
                    finnish=(
                        "Tämän linkin voimassaolo on päättynyt. Linkki on voimassa "
                        "vuorokauden siitä, kun se luotiin."
                    ),
                )
            if found.queries_used >= found.query_limit:
                raise Denied(
                    f"token {key!r} used {found.queries_used} of {found.query_limit} queries",
                    finnish=(
                        f"Tämän linkin {found.query_limit} kysymystä on käytetty. "
                        "Linkki on kertaluonteinen näyte, ei jatkuva palvelu."
                    ),
                )

            # The global counters, upserted so the first request of a day or a
            # month creates its own row rather than finding none.
            cur.execute(
                "INSERT INTO demo_day (day) VALUES (%s) ON CONFLICT (day) DO NOTHING", (day,)
            )
            cur.execute(
                "INSERT INTO demo_month (month) VALUES (%s) ON CONFLICT (month) DO NOTHING",
                (month,),
            )
            cur.execute("SELECT queries FROM demo_day WHERE day = %s FOR UPDATE", (day,))
            today = int(str(_one(cur.fetchone())[0]))
            cur.execute("SELECT cost_usd FROM demo_month WHERE month = %s FOR UPDATE", (month,))
            spent = float(str(_one(cur.fetchone())[0]))

            if today >= queries_per_day:
                raise Denied(
                    f"the global daily ceiling is reached: {today} of {queries_per_day}",
                    finnish=(
                        "Demon päivittäinen kysymysmäärä on täynnä. Kokeile huomenna "
                        "uudelleen -- linkkisi on edelleen voimassa."
                    ),
                )
            if spent >= dollars_per_month:
                raise Denied(
                    f"the monthly spend ceiling is reached: ${spent:.4f} of "
                    f"${dollars_per_month:.2f}",
                    finnish=(
                        "Demon tämän kuukauden budjetti on käytetty, joten uusia "
                        "vastauksia ei muodosteta. Demo on suljettu kuukauden loppuun."
                    ),
                )

            cur.execute(
                "UPDATE demo_token SET queries_used = queries_used + 1 WHERE token = %s",
                (key,),
            )
            cur.execute("UPDATE demo_day SET queries = queries + 1 WHERE day = %s", (day,))
            cur.execute("UPDATE demo_month SET queries = queries + 1 WHERE month = %s", (month,))
        conn.commit()
    except Denied:
        # Nothing was charged: the increments are the last statements in the
        # block, so any denial rolls back a transaction that only read.
        conn.rollback()
        raise
    except psycopg.Error as exc:
        conn.rollback()
        raise AccessError(f"the demo's state store failed: {exc}") from exc
    return Reservation(
        token=key,
        day=day,
        month=month,
        remaining_after=found.query_limit - found.queries_used - 1,
    )


def _one(row: tuple[object, ...] | None) -> tuple[object, ...]:
    if row is None:
        raise AccessError("a counter row vanished between its upsert and its read")
    return row


def record_spend(
    conn: psycopg.Connection[tuple[object, ...]], reservation: Reservation, cost_usd: float
) -> None:
    """Attach what the query actually cost to the query already reserved.

    Measured at the gateway, never estimated -- the same rule as every other cost
    figure in this project. The monthly ceiling is enforced on this number, so it
    can only stop the query *after* the one that crossed it: the honest guarantee
    is "one answer of overshoot, then nothing", exactly as `answer.TokenBudget`
    already words it.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE demo_token SET cost_usd = cost_usd + %s WHERE token = %s",
            (cost_usd, reservation.token),
        )
        cur.execute(
            "UPDATE demo_day SET cost_usd = cost_usd + %s WHERE day = %s",
            (cost_usd, reservation.day),
        )
        cur.execute(
            "UPDATE demo_month SET cost_usd = cost_usd + %s WHERE month = %s",
            (cost_usd, reservation.month),
        )
    conn.commit()


def refund(conn: psycopg.Connection[tuple[object, ...]], reservation: Reservation) -> None:
    """Give back a query that spent nothing.

    Every `AskError` path costs no model call (tracer 2, asserted by an answerer
    that raises), so charging one against a visitor's ten would be charging them
    for the harness declining. `GREATEST(..., 0)` so a double refund cannot mint
    queries.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE demo_token SET queries_used = GREATEST(queries_used - 1, 0) WHERE token = %s",
            (reservation.token,),
        )
        cur.execute(
            "UPDATE demo_day SET queries = GREATEST(queries - 1, 0) WHERE day = %s",
            (reservation.day,),
        )
        cur.execute(
            "UPDATE demo_month SET queries = GREATEST(queries - 1, 0) WHERE month = %s",
            (reservation.month,),
        )
    conn.commit()


def find(conn: psycopg.Connection[tuple[object, ...]], token: str) -> Token | None:
    """Read a token without charging anything. For rendering, never for gating."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM demo_token WHERE token = %s", (normalise(token),))
        row = cur.fetchone()
    return None if row is None else _row_to_token(row)

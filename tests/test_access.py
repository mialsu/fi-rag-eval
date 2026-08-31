"""Four caps on real money. None counts as built until it is watched failing.

`SPEC-mvp-demo` tracer 3, ADR-0013. These tests are the enforcers for rules that
otherwise live in prose, and every one of them was broken on purpose and seen red
(evidence in the spec's tracer-3 table).

The clock is injected everywhere, so token expiry is proven without sleeping for a
day, and the two global ceilings are parameters, so the daily cap is proven
without issuing two hundred queries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from fi_rag_eval import access
from fi_rag_eval.access import (
    ALPHABET,
    DOLLARS_PER_MONTH,
    QUERIES_PER_DAY,
    QUERIES_PER_TOKEN,
    TOKEN_CHARS,
    AccessError,
    Denied,
    Token,
    issue,
    new_token,
    normalise,
    refund,
    reserve,
    revoke,
    tokens,
)

T0 = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def at(moment: datetime) -> access.Clock:
    return lambda: moment


Conn = psycopg.Connection[tuple[object, ...]]


def a_token(store: Conn, **kwargs: object) -> Token:
    defaults: dict[str, object] = {"now": at(T0)}
    defaults.update(kwargs)
    return issue(store, **defaults)  # type: ignore[arg-type]


class TestTheTokenItself:
    def test_it_is_readable_aloud(self) -> None:
        """No `O`, `0`, `I` or `1`: a link gets read out and retyped."""
        for banned in "O0I1":
            assert banned not in ALPHABET
        assert len(ALPHABET) == 32
        one = new_token()
        assert len(one) == TOKEN_CHARS + 1 and one[4] == "-"
        assert all(c in ALPHABET for c in one.replace("-", ""))

    def test_two_tokens_are_not_the_same(self) -> None:
        assert len({new_token() for _ in range(200)}) == 200

    def test_transcription_noise_is_forgiven_but_a_wrong_token_is_not(self) -> None:
        """Case and the dash are noise. Anything else must simply fail to match."""
        assert normalise("ab23cd45") == "AB23-CD45"
        assert normalise("  AB23-CD45 ") == "AB23-CD45"
        assert normalise("AB23CD45") == "AB23-CD45"
        # A character outside the alphabet is NOT silently repaired into a
        # different token -- it is left alone so the lookup misses. `O` and `1`
        # are the interesting cases: they LOOK like `0` and `I`, which is exactly
        # why the alphabet excludes all four.
        assert normalise("AB23-CD4O") == "AB23-CD4O"
        assert normalise("AB12-CD34") == "AB12-CD34"
        assert normalise("short") == "short"

    def test_the_shape_sketched_during_shaping_is_NOT_a_producible_token(self) -> None:
        """`AB12-CD34` was the shape agreed for the link, and it cannot occur.

        It contains `1`, which the alphabet excludes so a link survives being read
        aloud. The *shape* is what was decided -- four, a dash, four -- and this
        pins the fact that the illustration itself is not a valid token, so nobody
        later "fixes" the alphabet to make an example work.
        """
        assert "1" not in ALPHABET
        assert normalise("AB12-CD34") == "AB12-CD34"  # left alone, so it misses


class TestIssuingListingRevoking:
    def test_an_issued_token_is_worth_what_it_says(self, store: Conn) -> None:
        one = a_token(store, note="a reviewer")
        assert one.query_limit == QUERIES_PER_TOKEN
        assert one.remaining == QUERIES_PER_TOKEN
        assert one.expires_at - one.issued_at == access.TOKEN_LIFETIME
        assert one.note == "a reviewer"
        assert one.cost_usd == 0.0

    def test_the_link_is_the_token_in_a_path(self, store: Conn) -> None:
        one = a_token(store)
        assert one.link("http://localhost:8080/") == f"http://localhost:8080/d/{one.token}"

    def test_a_worthless_token_cannot_be_issued(self, store: Conn) -> None:
        with pytest.raises(AccessError, match="at least one query"):
            a_token(store, queries=0)
        with pytest.raises(AccessError, match="outlive its issue"):
            a_token(store, lifetime=timedelta(0))

    def test_revoking_is_idempotent_and_keeps_the_first_time(self, store: Conn) -> None:
        one = a_token(store)
        first = revoke(store, one.token, now=at(T0 + timedelta(minutes=1)))
        again = revoke(store, one.token, now=at(T0 + timedelta(minutes=5)))
        assert first.revoked_at == again.revoked_at

    def test_revoking_something_that_was_never_issued_is_an_error(self, store: Conn) -> None:
        with pytest.raises(AccessError, match="no such token"):
            revoke(store, "ZZZZ-ZZZZ")

    def test_tokens_lists_newest_first(self, store: Conn) -> None:
        old = a_token(store, now=at(T0))
        new = a_token(store, now=at(T0 + timedelta(hours=1)))
        assert [t.token for t in tokens(store)] == [new.token, old.token]


class TestEveryCapDeniesAndChargesNothingWhenItDoes:
    """A denial must not consume the query it refused."""

    def test_an_unknown_token_is_denied(self, store: Conn) -> None:
        with pytest.raises(Denied, match="no such token"):
            reserve(store, "ZZZZ-ZZZZ", now=at(T0))

    def test_a_REVOKED_token_never_answers(self, store: Conn) -> None:
        one = a_token(store)
        revoke(store, one.token, now=at(T0))
        with pytest.raises(Denied, match="was revoked") as caught:
            reserve(store, one.token, now=at(T0 + timedelta(minutes=1)))
        assert "peruutettu" in caught.value.finnish
        assert access.find(store, one.token) is not None
        found = access.find(store, one.token)
        assert found is not None and found.queries_used == 0

    def test_an_EXPIRED_token_never_answers(self, store: Conn) -> None:
        """Injected clock: 24 hours pass without the test sleeping."""
        one = a_token(store)
        # One second before expiry it still works...
        reserve(store, one.token, now=at(one.expires_at - timedelta(seconds=1)))
        # ...and at expiry it does not. The boundary is pinned from both sides,
        # so an off-by-one in either direction fails.
        with pytest.raises(Denied, match="expired") as caught:
            reserve(store, one.token, now=at(one.expires_at))
        assert "voimassaolo on päättynyt" in caught.value.finnish
        found = access.find(store, one.token)
        assert found is not None and found.queries_used == 1, "the denial charged a query"

    def test_an_OVER_CAP_token_never_answers(self, store: Conn) -> None:
        one = a_token(store, queries=3)
        for expected_remaining in (2, 1, 0):
            got = reserve(store, one.token, now=at(T0))
            assert got.remaining_after == expected_remaining
        with pytest.raises(Denied, match="used 3 of 3") as caught:
            reserve(store, one.token, now=at(T0))
        assert "3 kysymystä on käytetty" in caught.value.finnish
        found = access.find(store, one.token)
        assert found is not None and found.queries_used == 3, "the denial charged a fourth"

    def test_the_GLOBAL_DAILY_ceiling_stops_every_token(self, store: Conn) -> None:
        """A fresh, unused token is denied because the *day* is full."""
        first = a_token(store, queries=5)
        second = a_token(store, queries=5)
        reserve(store, first.token, now=at(T0), queries_per_day=2)
        reserve(store, first.token, now=at(T0), queries_per_day=2)
        with pytest.raises(Denied, match="global daily ceiling") as caught:
            reserve(store, second.token, now=at(T0), queries_per_day=2)
        assert "päivittäinen kysymysmäärä on täynnä" in caught.value.finnish
        untouched = access.find(store, second.token)
        assert untouched is not None and untouched.queries_used == 0

    def test_the_daily_ceiling_resets_on_the_NEXT_DAY(self, store: Conn) -> None:
        """Otherwise it is a lifetime cap wearing a daily name."""
        one = a_token(store, queries=5, lifetime=timedelta(days=30))
        reserve(store, one.token, now=at(T0), queries_per_day=1)
        with pytest.raises(Denied, match="global daily"):
            reserve(store, one.token, now=at(T0 + timedelta(hours=1)), queries_per_day=1)
        tomorrow = T0 + timedelta(days=1)
        assert reserve(store, one.token, now=at(tomorrow), queries_per_day=1)

    def test_the_MONTHLY_DOLLAR_ceiling_stops_every_token(self, store: Conn) -> None:
        """The only cap denominated in money, and it is the one that matters.

        Enforced on **measured** spend, so it stops the query *after* the one that
        crossed it: the honest guarantee is "one answer of overshoot, then
        nothing", exactly as `answer.TokenBudget` words it for tokens.
        """
        one = a_token(store, queries=50, lifetime=timedelta(days=30))
        got = reserve(store, one.token, now=at(T0), dollars_per_month=0.02)
        access.record_spend(store, got, 0.0177)
        # Under the ceiling, so the next one is allowed.
        second = reserve(store, one.token, now=at(T0), dollars_per_month=0.02)
        access.record_spend(store, second, 0.0177)
        # Now over. Note it took TWO answers to cross a two-cent ceiling: that is
        # the overshoot, and it is a property, not a bug.
        with pytest.raises(Denied, match="monthly spend ceiling") as caught:
            reserve(store, one.token, now=at(T0), dollars_per_month=0.02)
        assert "budjetti on käytetty" in caught.value.finnish

    def test_the_monthly_ceiling_resets_on_the_NEXT_MONTH(self, store: Conn) -> None:
        one = a_token(store, queries=50, lifetime=timedelta(days=90))
        got = reserve(store, one.token, now=at(T0), dollars_per_month=0.01)
        access.record_spend(store, got, 0.02)
        with pytest.raises(Denied, match="monthly spend"):
            reserve(store, one.token, now=at(T0), dollars_per_month=0.01)
        september = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        assert reserve(store, one.token, now=at(september), dollars_per_month=0.01)

    def test_the_shipped_defaults_are_the_decided_ones(self) -> None:
        """The numbers in ADR-0013, pinned so a drive-by edit fails the gate."""
        assert QUERIES_PER_TOKEN == 10
        assert timedelta(hours=24) == access.TOKEN_LIFETIME
        assert QUERIES_PER_DAY == 200
        assert DOLLARS_PER_MONTH == 10.00


class TestReserveThenRefund:
    def test_a_refund_gives_the_query_back_to_all_three_counters(self, store: Conn) -> None:
        one = a_token(store, queries=2)
        got = reserve(store, one.token, now=at(T0))
        refund(store, got)
        found = access.find(store, one.token)
        assert found is not None and found.queries_used == 0
        # And the day is free again, proven by a ceiling of 1 that now passes.
        assert reserve(store, one.token, now=at(T0), queries_per_day=1)

    def test_a_double_refund_cannot_MINT_queries(self, store: Conn) -> None:
        """`GREATEST(..., 0)`. Otherwise a retried refund is free money."""
        one = a_token(store, queries=2)
        got = reserve(store, one.token, now=at(T0))
        refund(store, got)
        refund(store, got)
        found = access.find(store, one.token)
        assert found is not None and found.queries_used == 0

    def test_spend_is_recorded_against_the_token_the_day_and_the_month(self, store: Conn) -> None:
        one = a_token(store)
        got = reserve(store, one.token, now=at(T0))
        access.record_spend(store, got, 0.0161)
        found = access.find(store, one.token)
        assert found is not None and found.cost_usd == pytest.approx(0.0161)
        with store.cursor() as cur:
            cur.execute("SELECT cost_usd FROM demo_day WHERE day = %s", (got.day,))
            assert float(str(cur.fetchall()[0][0])) == pytest.approx(0.0161)
            cur.execute("SELECT cost_usd FROM demo_month WHERE month = %s", (got.month,))
            assert float(str(cur.fetchall()[0][0])) == pytest.approx(0.0161)


class TestTheStoreSurvivesAndIsNeverDropped:
    def test_the_schema_has_no_DROP(self) -> None:
        """The exact opposite of `db.SCHEMA`, and the difference is the point.

        A corpus that survives an ingest has drifted from the manifest. A token
        store that does NOT survive is a link that broke.
        """
        assert "DROP" not in access.SCHEMA.upper()
        assert access.SCHEMA.upper().count("IF NOT EXISTS") == 3

    def test_creating_the_schema_twice_keeps_the_tokens(self, store: Conn) -> None:
        one = a_token(store)
        access.create_schema(store)
        access.create_schema(store)
        assert access.find(store, one.token) is not None

    def test_ensure_database_is_idempotent(self, store_url: str) -> None:
        """It runs on every `serve` start, on a volume that is already
        initialised -- which is exactly why an initdb script would be dead code."""
        try:
            assert access.ensure_database(store_url) == store_url
            assert access.ensure_database(store_url) == store_url
        except AccessError as exc:
            pytest.skip(f"no demo state store: {exc}")

    def test_a_url_with_no_database_is_refused(self) -> None:
        with pytest.raises(AccessError, match="names no database"):
            access.ensure_database("postgresql://litellm:litellm@localhost:5435/")

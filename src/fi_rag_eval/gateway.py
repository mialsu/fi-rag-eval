"""The gateway's administration: the budgeted key the harness spends through.

This module exists because a red-proof failed. `SPEC-slice-5` D8 names the
LiteLLM Proxy's **per-key** budget as the cost ceiling's second enforcer, and the
gateway's first configuration here put the budget in `litellm_settings` and
authenticated with the proxy's master key. Measured:

    master key,  spend $0.074910 against a $0.001 budget  -> HTTP 200, served
    virtual key, spend $0.000029 against a $0.00001 budget -> HTTP 429, refused

The master key is an admin credential and bypasses budget checks entirely. A
budget it cannot trip is a number in a file, which is this project's own
"standard with no enforcer" -- so the harness spends through a virtual key that
carries the budget, exactly as D8 specified.

The key is **derived** from the master key rather than stored. A second secret in
`.env` is a second secret to leak, to forget to rotate, and to be missing from a
clean clone; and anyone holding the master key can already do everything this key
can, so deriving it gives nothing away. It also means rotating the master key
rotates this one, instead of leaving an orphan with a live budget.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from typing import Any

ALIAS = "fi-rag-eval"
MONTHLY_BUDGET_USD = 25.0
"""The Owner's Groq cap, mirrored at the gateway (D8 enforcer #3 -> #2).

Deliberately the same number rather than a lower one: the per-run token ceiling
in `answer.TokenBudget` is what trips first on a runaway, and it trips two orders
of magnitude earlier. This one is the monthly backstop, and it should refuse at
the line the provider would.
"""
BUDGET_DURATION = "30d"
TIMEOUT_SECONDS = 15


class GatewayError(RuntimeError):
    """The gateway could not be administered, so the harness has no budgeted key."""


def spending_key_id(master_key: str) -> str:
    """A stable key value for this project, derived from the master key.

    Deterministic so that every run reuses the *same* key and therefore the same
    accumulating spend. Regenerating a fresh key per run would reset the budget
    to zero every time, which would leave the enforcer looking installed and
    enforcing nothing -- the failure mode this whole module is a correction for.
    """
    digest = hashlib.sha256(master_key.encode()).hexdigest()[:16]
    return f"sk-{ALIAS}-{digest}"


def _request(url: str, *, master_key: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {master_key}",
            "Content-Type": "application/json",
            # Set explicitly: Groq's edge and tampere.fi both reject the default
            # `Python-urllib` User-Agent, and that confession generalised once
            # already. Cheaper to set it everywhere than to remember where.
            "User-Agent": "fi-rag-eval/0.0.0",
        },
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.load(response)


def ensure_budgeted_key(*, proxy_url: str, master_key: str) -> str:
    """The virtual key this project spends through, created once and then reused.

    Idempotent by construction: the key's *value* is derived, so an existing key
    is found by looking itself up rather than by searching for an alias. Returns
    the key whether it already existed or was just created.
    """
    key = spending_key_id(master_key)
    base = proxy_url.rstrip("/")
    try:
        _request(f"{base}/key/info?key={key}", master_key=master_key)
    except urllib.error.HTTPError:
        # Not found (or not readable) -- create it. Any other failure surfaces
        # from the generate call below with the gateway's own message.
        try:
            _request(
                f"{base}/key/generate",
                master_key=master_key,
                payload={
                    "key": key,
                    "key_alias": ALIAS,
                    "max_budget": MONTHLY_BUDGET_USD,
                    "budget_duration": BUDGET_DURATION,
                },
            )
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise GatewayError(
                f"could not create the budgeted key at {base}: {exc}\n"
                "Without it the harness would spend through the master key, whose "
                "budget the gateway does not enforce."
            ) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GatewayError(
            f"the gateway at {base} could not be reached to provision a budgeted key: "
            f"{exc}\nStart it with `make services-up`."
        ) from exc
    return key

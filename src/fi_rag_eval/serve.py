"""The demo surface: one server-rendered page over the retrieval the harness measures.

`SPEC-mvp-demo` tracer 2. Localhost only -- there is no token gate here, and
nothing in this module may be exposed to a stranger until tracer 3 adds one.

Four properties are deliberate, and each is asserted rather than intended.

**It calls `ask.ask` and re-implements nothing.** The whole argument for this
surface is that it demonstrates the *measured* pipeline: the published cell, the
harness's lexemes, the harness's ranking. A second retrieval behind a demo would
drift from every published number and both would still look fine, so the
constraint is enforced twice -- the injected asker's default **is** `ask.ask` by
identity, and a test parses this module's AST and fails if it so much as names
`db.search`.

**The question travels in a request body, never a URL.** A `GET` with the
question in the query string would put a resident's own words into uvicorn's
access log, the browser's history and any proxy in between. `CLAUDE.md`'s "no
personal data, ever" and `ask.ASK_ID` already refuse to derive an id from the
text; this is the same rule applied to the transport, and `GET /ask` is a 405.

**The body is read with a cap and parsed by the standard library.** Starlette's
`request.form()` requires `python-multipart`, a file-upload parser this surface
will never need; `parse_qsl` covers the one form it actually serves. The body is
streamed against `MAX_BODY_BYTES` rather than accumulated, so a chunked request
with no `Content-Length` cannot grow without bound.

**Nothing reaches the answerer that could not be answered.** Every `AskError`
path -- no question, no *kunta*, an unknown *kunta*, a partially covered one, a
question that normalises to nothing, a search that returns nothing, and a
question longer than `MAX_QUESTION_CHARS` -- renders a refusal without a model
call. The answerer is injected so a test can pass one that **raises**, exactly as
`test_ask.py` does: on a surface wired to a paid provider, "this path is free" has
to be a test failure rather than a comment.

**The *kunta* select opens on nothing chosen.** A dropdown defaulting to its first
entry would make the harness pick a jurisdiction, which is the one thing
`manifest.resolve_municipality` exists to refuse and `CLAUDE.md`'s third
verification layer explicitly forbids. The empty option is the load-bearing part
of the form.

One concurrency note, and it is a feature rather than a limitation. A single lock
serialises the answering path: `libvoikko`'s thread-safety is unspecified and one
`Morphology` is shared, but the reason to keep it after that is that it bounds
**in-flight spend to one model call**. `GET /` never takes the lock, so the page
still loads while an answer is in progress.
"""

from __future__ import annotations

import ast
import html
import sys
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qsl

import psycopg
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from fi_rag_eval import db
from fi_rag_eval.analyse import Morphology
from fi_rag_eval.answer import ANSWERER, AnswerError, TokenBudget, answer_question
from fi_rag_eval.ask import Answerer, Asked, AskError, ask, municipalities
from fi_rag_eval.evaluate import DEFAULT_K, PUBLISHED, Cell
from fi_rag_eval.manifest import Manifest

TEMPLATE = "demo.html"

MAX_QUESTION_CHARS = 500
"""Longer than any question in the golden set, and a spend control.

Tokens are money and the prompt carries the question verbatim. The golden set's
longest question is well under this, so the cap cannot refuse anything the
harness itself measures -- and refusing a 100KB paste costs nothing, which is the
point.
"""

MAX_BODY_BYTES = 8 * 1024
"""How much request body is read at all, enforced while streaming.

`MAX_QUESTION_CHARS` bounds what reaches the model; this bounds what reaches
memory, and it is checked chunk by chunk rather than after the fact so a client
sending a chunked body without a `Content-Length` cannot make the server
accumulate it. Comfortably above a 500-character question plus a *kunta*.
"""

ASK_PATH = "/ask"
"""Where the form posts. A slot rather than a literal in the template because
tracer 3 moves it under a token (`/d/AB12-CD34/ask`)."""


# ---------------------------------------------------------------------------
# Escaping, made structural
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Html:
    """A string that is already safe to place in the page.

    The demo echoes a stranger's question back into HTML, so escaping is the one
    thing here that must not depend on remembering to do it. `render` accepts
    **only** `Html`, so passing a raw `str` is a mypy error under `strict` --
    which puts the guarantee in the gate instead of in a comment.
    """

    text: str


NOTHING = Html("")
"""An empty slot. A module singleton because `Html("")` in a default is a lint error."""


def esc(value: object) -> Html:
    """Escape a value for HTML, including inside attributes."""
    return Html(html.escape(str(value), quote=True))


def joined(parts: Iterable[Html]) -> Html:
    return Html("".join(part.text for part in parts))


def render(template: str, slots: Mapping[str, Html]) -> str:
    """Fill every `{{SLOT}}` in `template`, and fail on any mismatch.

    Total by construction: a slot in the template with no value, or a value with
    no slot, raises. A partially rendered page would ship `{{RESULT}}` to a
    reader, and a silently ignored slot would ship a page missing the thing it
    was told to show.
    """
    found = {template[start + 2 : end] for start, end in _slot_spans(template)}
    if found != set(slots):
        missing = sorted(found - set(slots))
        extra = sorted(set(slots) - found)
        raise ValueError(
            f"template slots do not match the values given: missing {missing}, extra {extra}"
        )
    out = template
    for name, value in slots.items():
        out = out.replace("{{" + name + "}}", value.text)
    return out


def _slot_spans(template: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    while (start := template.find("{{", cursor)) != -1:
        end = template.find("}}", start)
        if end == -1:
            raise ValueError("template has an unclosed '{{'")
        spans.append((start, end))
        cursor = end + 2
    return spans


def load_template(path: Path | None = None) -> str:
    """The page shell. Read from the package, so a wheel carries it too."""
    if path is not None:
        return path.read_text(encoding="utf-8")
    return resources.files("fi_rag_eval").joinpath("static", TEMPLATE).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def options(names: Sequence[str], chosen: str) -> Html:
    """The *kunta* dropdown, opening on **nothing chosen**.

    The empty option is not a nicety. Without it the browser submits the first
    municipality in the list, and the harness would be answering from a
    jurisdiction the asker never picked -- the failure the hard filter exists to
    prevent, arriving through the form instead of through the query.
    """
    parts = [
        Html(
            '<option value=""'
            + ("" if chosen else " selected")
            + ">&mdash; valitse kunta &mdash;</option>"
        )
    ]
    for name in names:
        selected = " selected" if name == chosen else ""
        value = esc(name).text
        parts.append(Html(f'<option value="{value}"{selected}>{value}</option>'))
    return joined(parts)


def excerpts(asked: Asked) -> Html:
    """The retrieved chunks, addresses and all.

    Shown for a refusal exactly as for an answer. On the harness's surfaces that
    is a diagnostic; here it is the demo's whole argument -- a reader can see what
    the system was given and judge whether the refusal was honest or lazy. ADR-0010
    made the same call for refusal citations: the more auditable refusal is the
    better one.
    """
    rows = [
        Html(f'<li><span class="addr">{esc(hit.address).text}</span> {esc(hit.citation).text}</li>')
        for hit in asked.hits
    ]
    return Html(f'<ol class="otteet">{joined(rows).text}</ol>')


def answer_block(asked: Asked) -> Html:
    """One answered (or refused) question, rendered."""
    usage = asked.answer.usage
    verdict = (
        '<span class="verdict ei">EI VASTAUSTA</span>'
        if asked.refused
        else '<span class="verdict vastaus">VASTAUS</span>'
    )
    note = (
        '<p class="hint">Järjestelmä kieltäytyi vastaamasta näiden otteiden perusteella. '
        "Otteet näkyvät yllä, joten voit itse tarkistaa, oliko kieltäytyminen perusteltu.</p>"
        if asked.refused
        else ""
    )
    citations = (
        joined(
            [Html(f'<span class="addr">{esc(c).text}</span> ') for c in asked.answer.citations]
        ).text
        or '<span class="hint">ei viittauksia</span>'
    )
    return Html(
        "<section>"
        f'<p class="meta">{esc(asked.municipality).text} &rarr; '
        f"{esc(asked.authority_name).text} ({esc(asked.authority_key).text}), "
        f"haku {esc(asked.cell).text}</p>"
        f"<h2>Haetut otteet (top-{len(asked.hits)})</h2>{excerpts(asked).text}"
        f"<h2>Vastaus</h2>{verdict}"
        f'<p class="body">{esc(asked.answer.text).text}</p>{note}'
        f"<h2>Viittaukset</h2><p>{citations}</p>"
        f'<p class="price">Hinta ${usage.cost_usd:.4f} &mdash; mitattu gatewaylla, ei arvioitu '
        f"({usage.total_tokens} tokenia, joista {usage.reasoning_tokens} päättelyä).</p>"
        "</section>"
    )


def notice(heading: str, message: str, *, hint: str = "") -> Html:
    """A labelled honest empty state. Never "coming soon", never a raw traceback."""
    tail = f'<p class="hint">{esc(hint).text}</p>' if hint else ""
    return Html(
        "<section>"
        f"<h2>{esc(heading).text}</h2>"
        f'<p class="body">{esc(message).text}</p>{tail}'
        "</section>"
    )


def page(
    template: str,
    *,
    names: Sequence[str],
    question: str = "",
    chosen: str = "",
    result: Html = NOTHING,
    cell: Cell = PUBLISHED,
    action: str = ASK_PATH,
) -> str:
    return render(
        template,
        {
            "ACTION": esc(action),
            "QUESTION": esc(question),
            "OPTIONS": options(names, chosen),
            "RESULT": result,
            "CELL": esc(cell.name),
        },
    )


# ---------------------------------------------------------------------------
# Reading the request
# ---------------------------------------------------------------------------


async def read_body(request: Request, limit: int) -> bytes | None:
    """The whole body, or `None` if it is over `limit`.

    Streamed and counted rather than `await request.body()`: the latter
    accumulates whatever arrives, so a chunked body with no `Content-Length` is
    unbounded. Refusing here costs nothing, which on a surface wired to a paid
    provider is the point.
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def form_fields(body: bytes) -> dict[str, str]:
    """Parse `application/x-www-form-urlencoded`, and nothing else.

    Starlette's `request.form()` needs `python-multipart`, whose reason to exist
    is file uploads. This surface has one text field and one select and will never
    accept a file, so the narrower parser is both one fewer dependency and one
    fewer thing reachable from outside: a multipart body simply does not parse
    here. `parse_qsl` is stdlib -- reuse, not a hand-rolled decoder.

    `keep_blank_values` is deliberate: an empty *kunta* is the "nothing chosen"
    case the form is built around, and dropping the field would turn a refusal
    into a missing key.
    """
    text = body.decode("utf-8", errors="replace")
    return dict(parse_qsl(text, keep_blank_values=True))


# ---------------------------------------------------------------------------
# The application
# ---------------------------------------------------------------------------


class Asker(Protocol):
    """`ask.ask`'s contract, so the default can be checked to *be* it.

    Written out rather than inferred: mypy verifies `ask.ask` conforms, which
    makes this the one place where "the demo's logic is the harness's logic" is a
    type error to break rather than a paragraph to trust.
    """

    def __call__(
        self,
        conn: psycopg.Connection[tuple[object, ...]],
        *,
        manifest: Manifest,
        question: str,
        municipality: str,
        k: int = ...,
        cell: Cell = ...,
        morphology: Morphology | None = ...,
        model: str = ...,
        reasoning: bool = ...,
        budget: TokenBudget | None = ...,
        answerer: Answerer = ...,
    ) -> Asked: ...


Connect = Callable[[], psycopg.Connection[tuple[object, ...]]]

UNAVAILABLE_HEADING = "Palvelu ei ole juuri nyt käytettävissä"
UNAVAILABLE_BODY = (
    "Aineistoon ei saatu yhteyttä, joten kysymykseen ei voitu vastata. "
    "Kyse on teknisestä häiriöstä, ei kieltäytymisestä."
)

INTERNAL_MESSAGES_NEVER_RENDERED = (db.DatabaseError, AnswerError)
"""Exception types whose message must not reach the page.

`db.connect`'s message contains the database URL with its credentials, and a
gateway error carries the proxy's URL. Both are useful on stderr and neither is
anyone else's business. The `AskError` above is the opposite case: it is written
for the asker, in two languages, and *is* rendered.
"""


def log(line: str) -> None:
    """Server-side diagnostics. Never the question, ever.

    `CLAUDE.md`: "Never log raw end-user queries or anything identifying." What
    goes here is what failed, not what was asked -- which is also why
    `DESIGN.md:35`'s structured per-query logging stays unbuilt on this surface
    until the Owner resolves that tension (`SPEC-mvp-demo`, open question 1).
    """
    print(f"fi-rag-eval serve: {line}", file=sys.stderr, flush=True)


def create_app(
    *,
    manifest: Manifest,
    morphology: Morphology | None,
    connect: Connect = db.connect,
    answerer: Answerer = answer_question,
    asker: Asker = ask,
    k: int = DEFAULT_K,
    cell: Cell = PUBLISHED,
    model: str = ANSWERER,
    template: str | None = None,
) -> Starlette:
    """The demo application.

    The answerer defaults to the real, paid one. It is a parameter at all so a
    test can inject one that **raises**, which is how every free-refusal claim in
    this module is asserted rather than asserted about.
    """
    shell = template if template is not None else load_template()
    names = municipalities(manifest)
    # Serialises the paid path. See the module docstring: unspecified libvoikko
    # thread-safety is the reason it appears, bounded in-flight spend is the
    # reason it stays.
    lock = threading.Lock()

    def blank() -> str:
        return page(shell, names=names, cell=cell)

    def home(request: Request) -> Response:
        return HTMLResponse(blank())

    def run(question: str, municipality: str) -> Response:
        """Everything blocking: the connection, the analyser, the model call."""
        try:
            with lock, connect() as conn:
                asked = asker(
                    conn,
                    manifest=manifest,
                    question=question,
                    municipality=municipality,
                    k=k,
                    cell=cell,
                    morphology=morphology,
                    model=model,
                    budget=TokenBudget(),
                    answerer=answerer,
                )
        except AskError as exc:
            # `exc.finnish`, never `str(exc)`: the English half is the maintainer's
            # and names the design decision behind the refusal; this page is read
            # by a resident, and `CLAUDE.md`'s definition of done requires their
            # language. The English still reaches stderr below.
            log(f"refused: {exc}")
            return HTMLResponse(
                page(
                    shell,
                    names=names,
                    question=question,
                    chosen=municipality,
                    cell=cell,
                    result=notice("Ei vastausta", exc.finnish),
                ),
                status_code=400,
            )
        except db.DatabaseError as exc:
            # The message is NEVER rendered. `db.connect` puts the database URL in
            # it, credentials and all, and this page is reachable by someone who
            # must not read it. Server-side only.
            log(f"database unreachable: {exc}")
            return HTMLResponse(
                page(
                    shell,
                    names=names,
                    question=question,
                    chosen=municipality,
                    cell=cell,
                    result=notice(UNAVAILABLE_HEADING, UNAVAILABLE_BODY),
                ),
                status_code=503,
            )
        except AnswerError as exc:
            # Same rule as above, for the same reason: a gateway error carries the
            # proxy's own URL and whatever the provider chose to say.
            log(f"answering failed: {exc}")
            return HTMLResponse(
                page(
                    shell,
                    names=names,
                    question=question,
                    chosen=municipality,
                    cell=cell,
                    result=notice(
                        "Vastausta ei saatu",
                        "Vastauksen muodostaminen ei onnistunut. Tämä on tekninen "
                        "häiriö, ei kieltäytyminen -- yritä hetken kuluttua uudelleen.",
                    ),
                ),
                status_code=502,
            )
        return HTMLResponse(
            page(
                shell,
                names=names,
                question=question,
                chosen=municipality,
                cell=cell,
                result=answer_block(asked),
            )
        )

    async def ask_route(request: Request) -> Response:
        body = await read_body(request, MAX_BODY_BYTES)
        if body is None:
            return HTMLResponse(
                page(
                    shell,
                    names=names,
                    cell=cell,
                    result=notice(
                        "Ei vastausta",
                        f"Pyyntö on liian suuri. Enintään {MAX_BODY_BYTES} tavua.",
                    ),
                ),
                status_code=413,
            )
        fields = form_fields(body)
        question = fields.get("kysymys", "")
        municipality = fields.get("kunta", "")
        if len(question) > MAX_QUESTION_CHARS:
            # Refused before the connection is even opened: the prompt carries the
            # question verbatim, so length is spend.
            return HTMLResponse(
                page(
                    shell,
                    names=names,
                    chosen=municipality,
                    cell=cell,
                    result=notice(
                        "Ei vastausta",
                        f"Kysymys on liian pitkä ({len(question)} merkkiä). "
                        f"Enintään {MAX_QUESTION_CHARS} merkkiä.",
                    ),
                ),
                status_code=400,
            )
        return await run_in_threadpool(run, question, municipality)

    return Starlette(
        routes=[
            Route("/", home, methods=["GET"]),
            Route(ASK_PATH, ask_route, methods=["POST"]),
        ]
    )


# ---------------------------------------------------------------------------
# The reuse guarantee, as an enforcer
# ---------------------------------------------------------------------------

FORBIDDEN_NAMES = frozenset(
    {"search", "cell_query_lexemes", "or_tsquery", "snowball_stopwords", "chunk_bodies"}
)
"""Retrieval primitives this module must never call.

`ask.ask` calls every one of them. If `serve.py` calls one too, there are two
retrieval paths behind one published number and the demo has begun to drift.
`retrieval_names_used` reads this module's own source, so the check cannot be
satisfied by a comment.
"""


def retrieval_names_used(source: str) -> frozenset[str]:
    """Every `FORBIDDEN_NAMES` identifier a module's source actually references."""
    tree = ast.parse(source)
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            used.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            used.add(node.id)
        elif isinstance(node, ast.ImportFrom):
            used.update(alias.name for alias in node.names if alias.name in FORBIDDEN_NAMES)
    return frozenset(used)

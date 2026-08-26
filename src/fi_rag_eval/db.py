"""Postgres: schema, ingestion, and the lexical retrieval under measurement.

Slice 1 measures **`ts_rank` over a `finnish` text-search configuration, and
nothing else** -- no embeddings, no pgvector, no reranker, no BM25 extension.

`ts_rank` is not BM25. It has no inverse document frequency, so it cannot
down-weight a term that appears in most of the corpus, and at its default
normalisation (0) it does not normalise for document length either. Every number
this module produces is a `ts_rank` number and is labelled as such.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

import psycopg
from psycopg import sql
from psycopg.rows import class_row

from fi_rag_eval.addressing import ChunkAddress
from fi_rag_eval.chunking import Chunk
from fi_rag_eval.manifest import Authority, Source

DEFAULT_URL = "postgresql://fi_rag_eval:fi_rag_eval@localhost:5434/fi_rag_eval"
URL_ENV = "FI_RAG_EVAL_DATABASE_URL"
TEXT_SEARCH_CONFIG = "finnish"

SCHEMA = """
DROP TABLE IF EXISTS chunk;
DROP TABLE IF EXISTS source;
DROP TABLE IF EXISTS authority;

CREATE TABLE authority (
    key            text PRIMARY KEY,
    name           text NOT NULL,
    municipalities text[] NOT NULL
);

CREATE TABLE source (
    authority_key  text NOT NULL REFERENCES authority (key),
    effective_date date NOT NULL,
    title          text NOT NULL,
    url            text NOT NULL,
    sha256         text NOT NULL,
    PRIMARY KEY (authority_key, effective_date)
);

CREATE TABLE chunk (
    address        text PRIMARY KEY,
    authority_key  text NOT NULL,
    effective_date date NOT NULL,
    clause         integer NOT NULL,
    sub_key        text,
    citation       text NOT NULL,
    body           text NOT NULL,
    content_sha256 text NOT NULL,
    tsv            tsvector GENERATED ALWAYS AS
                       (to_tsvector('finnish', body)) STORED,
    FOREIGN KEY (authority_key, effective_date)
        REFERENCES source (authority_key, effective_date) ON DELETE CASCADE
);

CREATE INDEX chunk_tsv ON chunk USING gin (tsv);
CREATE INDEX chunk_jurisdiction ON chunk (authority_key, effective_date);
"""


class DatabaseError(RuntimeError):
    """The database is unreachable, or is not in the state the harness needs."""


@dataclass(frozen=True, slots=True)
class Hit:
    """One retrieved chunk, with its 1-based position in the ranking."""

    position: int
    address: str
    citation: str
    rank: float


@dataclass(frozen=True, slots=True)
class CorpusSummary:
    authority_key: str
    effective_date: date
    chunks: int
    definitions: int
    clauses: int


def database_url() -> str:
    return os.environ.get(URL_ENV, DEFAULT_URL)


def connect(url: str | None = None) -> psycopg.Connection[tuple[object, ...]]:
    target = url or database_url()
    try:
        return psycopg.connect(target, autocommit=False)
    except psycopg.Error as exc:
        raise DatabaseError(
            f"cannot reach Postgres at {target}: {exc}\n"
            f"Start it with `make db-up`, or point {URL_ENV} somewhere else."
        ) from exc


def create_schema(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    """Recreate the schema from scratch. Ingestion is a full reload, by design.

    An incremental ingest is how a corpus quietly diverges from the manifest,
    and every golden label points into the corpus.

    Deliberately does **not** commit: the caller commits once, so a reload that
    fails halfway rolls back to the previous corpus instead of leaving an empty
    one behind. A half-loaded corpus would make the next eval blame retrieval
    for missing chunks.
    """
    with conn.cursor() as cur:
        cur.execute(sql.SQL(SCHEMA))


def assert_finnish_config(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_ts_config WHERE cfgname = %s",
            (TEXT_SEARCH_CONFIG,),
        )
        row = cur.fetchone()
    if row is None or row[0] == 0:
        raise DatabaseError(
            f"this Postgres has no {TEXT_SEARCH_CONFIG!r} text-search configuration, "
            "so the lexical baseline cannot be measured as specified."
        )


def insert_authority(conn: psycopg.Connection[tuple[object, ...]], authority: Authority) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO authority (key, name, municipalities) VALUES (%s, %s, %s)",
            (authority.key, authority.name, list(authority.municipalities)),
        )


def insert_source(
    conn: psycopg.Connection[tuple[object, ...]], authority_key: str, source: Source
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO source (authority_key, effective_date, title, url, sha256) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                authority_key,
                source.effective_date,
                source.title,
                source.url,
                source.sha256,
            ),
        )


def insert_chunks(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    authority_key: str,
    effective_date: date,
    chunks: Iterable[Chunk],
) -> int:
    rows = []
    for chunk in chunks:
        address = ChunkAddress(
            authority=authority_key,
            effective_date=effective_date,
            clause=chunk.clause,
            sub_key=chunk.sub_key,
        )
        rows.append(
            (
                str(address),
                authority_key,
                effective_date,
                chunk.clause,
                chunk.sub_key,
                chunk.citation,
                chunk.text,
                hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
            )
        )
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO chunk (address, authority_key, effective_date, clause, "
            "sub_key, citation, body, content_sha256) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
    return len(rows)


def corpus_summary(
    conn: psycopg.Connection[tuple[object, ...]],
) -> list[CorpusSummary]:
    with conn.cursor(row_factory=class_row(CorpusSummary)) as cur:
        cur.execute(
            "SELECT authority_key, effective_date, count(*) AS chunks, "
            "count(sub_key) AS definitions, count(DISTINCT clause) AS clauses "
            "FROM chunk GROUP BY authority_key, effective_date "
            "ORDER BY authority_key, effective_date"
        )
        return cur.fetchall()


def query_lexemes(conn: psycopg.Connection[tuple[object, ...]], text: str) -> list[str]:
    """Stem a question with the same configuration the index uses.

    Going through the database rather than reimplementing the stemmer is the
    point: the query and the corpus must be normalised identically, or the
    measurement is of two different analysers.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT lexeme FROM unnest(to_tsvector(%s::regconfig, %s)) ORDER BY lexeme",
            (TEXT_SEARCH_CONFIG, text),
        )
        return [str(row[0]) for row in cur.fetchall()]


def escape_lexeme(lexeme: str) -> str:
    """Escape a lexeme for a single-quoted tsquery literal.

    Inside the quotes both the backslash and the quote are special, so both are
    doubled. Finnish body text rarely produces either, but the corpus contains
    URLs and the questions are free text -- and a mis-escaped lexeme changes the
    query's *meaning*, which would corrupt a measurement silently.
    """
    return lexeme.replace("\\", "\\\\").replace("'", "''")


def or_tsquery(lexemes: Sequence[str]) -> str:
    """Build the bag-of-words query a ranked lexical baseline needs.

    ``plainto_tsquery`` ANDs every term, which for an eight-word question means
    "return only chunks containing all eight stems" -- a boolean filter, not a
    ranked retrieval, and it would measure something nobody would ship. Terms
    are therefore OR-ed and left to ``ts_rank`` to order.

    The result is a **tsquery literal over lexemes that are already stemmed**, so
    it must be cast (``::tsquery``), never passed through ``to_tsquery``.
    ``to_tsquery`` runs the stemmer again: it turns ``biojät`` into ``biojä`` and
    ``tarkoit`` into ``tarkoi``, and a query stemmed one round further than the
    index silently stops matching chunks that contain the term verbatim. That bug
    produced a *higher* headline number than the truth on this corpus, which is
    exactly the kind of flattering defect this harness exists to catch.
    """
    if not lexemes:
        raise ValueError("cannot build a tsquery from zero lexemes")
    return " | ".join(f"'{escape_lexeme(lexeme)}'" for lexeme in lexemes)


def search(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    tsquery: str,
    authority_key: str,
    effective_date: date,
    limit: int,
) -> list[Hit]:
    """Top-``limit`` chunks by ``ts_rank``, inside one jurisdiction.

    The authority filter is applied in the WHERE clause, before ranking, so a
    chunk from another jurisdiction cannot be retrieved and then filtered out --
    it is never a candidate (ADR-0002).

    Ties break on address so the ranking is fully deterministic; the regression
    gate depends on the same corpus and question producing the same result.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT address, citation, ts_rank(tsv, query) AS rank "
            "FROM chunk, CAST(%s AS tsquery) AS query "
            "WHERE authority_key = %s AND effective_date = %s AND tsv @@ query "
            "ORDER BY rank DESC, address ASC LIMIT %s",
            (tsquery, authority_key, effective_date, limit),
        )
        return [
            Hit(
                position=position,
                address=str(row[0]),
                citation=str(row[1]),
                rank=float(str(row[2])),
            )
            for position, row in enumerate(cur.fetchall(), start=1)
        ]


def resolve_addresses(
    conn: psycopg.Connection[tuple[object, ...]], addresses: Iterable[str]
) -> set[str]:
    wanted = list(dict.fromkeys(addresses))
    if not wanted:
        return set()
    with conn.cursor() as cur:
        cur.execute("SELECT address FROM chunk WHERE address = ANY(%s)", (wanted,))
        return {str(row[0]) for row in cur.fetchall()}


def addresses_matching(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    addresses: Sequence[str],
    tsquery: str,
) -> set[str]:
    """Which of these chunks share *any* stemmed token with the query.

    This is the miss diagnostic. A required chunk that was not retrieved is
    either unreachable (no shared stem at all -- a morphology failure, which
    lemmatisation would fix) or reachable but out-ranked (a ranking failure,
    which is where the missing IDF would have helped). Pure arithmetic, no
    model, no cost.
    """
    if not addresses:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT address FROM chunk, CAST(%s AS tsquery) AS query "
            "WHERE address = ANY(%s) AND tsv @@ query",
            (tsquery, list(addresses)),
        )
        return {str(row[0]) for row in cur.fetchall()}

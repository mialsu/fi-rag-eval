"""Postgres: schema, ingestion, and the lexical retrieval under measurement.

Everything measured here is **`ts_rank` over a `tsvector`** -- no embeddings, no
pgvector, no reranker, no BM25 extension. Slice 3 widens that to a grid of eight
cells: four analysers (`analyse.Analyser`) crossed with two `ts_rank`
normalisation settings.

`ts_rank` is not BM25. It has no inverse document frequency, so it cannot
down-weight a term that appears in most of the corpus, and at its default
normalisation (0) it does not normalise for document length either -- which is
why normalisation is the grid's second axis rather than a fixed choice. Every
number this module produces is a `ts_rank` number and is labelled as such.

**One column per analyser, and the application writes three of them.** The
snowball `tsv` stays a generated column, so Postgres itself guarantees it can
never disagree with the body. The three lemma columns cannot be generated -- the
morphology lives in Python (ADR-0005) -- so they are written by the ingest and
then *asserted* to be populated for every chunk, because a silently empty index
would score zero and blame retrieval for it.
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
from fi_rag_eval.analyse import Analyser
from fi_rag_eval.chunking import Chunk
from fi_rag_eval.manifest import Authority, Source

DEFAULT_URL = "postgresql://fi_rag_eval:fi_rag_eval@localhost:5434/fi_rag_eval"
URL_ENV = "FI_RAG_EVAL_DATABASE_URL"
TEXT_SEARCH_CONFIG = "finnish"

NORMALISATIONS: tuple[int, ...] = (0, 1, 2)
"""The `ts_rank` normalisation settings under measurement -- the grid's second axis.

The axis exists to test slice 1's measured finding: `ts_rank` at its default
normalisation does not divide by document length, so a long clause accumulates
more matched-term weight than a short one, and definition chunks were 39% of this
corpus and 0% of every top-5.

* `0` -- the default. Divides by nothing. The control, and what slice 1 measured.
* `1` -- divides by ``1 + log(document length)``. The soft, BM25-shaped version.
* `2` -- divides by the document length. The blunt version.

**`32` is deliberately absent, and its absence is a correction.** The slice-3
spec named it as the second axis. It is documented as "divides the rank by itself
+ 1" -- that is ``rank / (rank + 1)``, a strictly monotonic rescale of the score
into `[0, 1)`, so it **cannot reorder a single result**. Measured: every one of
the eight cells scored identically at 0 and at 32, to three decimals, with an
identical per-question pass matrix. It never tested the hypothesis. Pinned by
`test_normalisation_32_cannot_reorder_anything` so it is not reintroduced.
"""

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
    -- Written by the ingest, not generated: see the module docstring. The empty
    -- default plus `assert_lemma_vectors_populated` turns "the ingest forgot" from
    -- a silent zero into a hard error.
    lemma_base_tsv  tsvector NOT NULL DEFAULT ''::tsvector,
    lemma_safe_tsv  tsvector NOT NULL DEFAULT ''::tsvector,
    lemma_reasm_tsv tsvector NOT NULL DEFAULT ''::tsvector,
    FOREIGN KEY (authority_key, effective_date)
        REFERENCES source (authority_key, effective_date) ON DELETE CASCADE
);

CREATE INDEX chunk_tsv ON chunk USING gin (tsv);
CREATE INDEX chunk_lemma_base_tsv ON chunk USING gin (lemma_base_tsv);
CREATE INDEX chunk_lemma_safe_tsv ON chunk USING gin (lemma_safe_tsv);
CREATE INDEX chunk_lemma_reasm_tsv ON chunk USING gin (lemma_reasm_tsv);
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
    authority_key: str
    """Read from the stored row, **not** parsed back out of the address.

    `evaluate` asserts every hit belongs to the question's own authority. Deriving
    that from the address would re-check the string this module composed a moment
    earlier; reading the column checks the row the WHERE clause actually filtered
    on, which is the thing that could regress (slice 4, D9).
    """


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
    document: str,
) -> int:
    """Load one document's chunks, stamping each citation with the document.

    ``document`` is the source's title plus its published edition, and it is
    joined onto the clause-level citation here rather than in `chunking` -- which
    reads one document and knows nothing about how it is published. With two
    authorities in the corpus a bare ``23 § KERÄYSVÄLINETYYPIT`` no longer says
    whose 23 §, and with six editions of Pirkanmaa's text sharing one address the
    edition is the only place a human learns which one they are reading (D3).

    The body is untouched: the citation is display-only and is not indexed, so
    this changes what a reader sees and no metric.
    """
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
                f"{chunk.citation} ({document})",
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
    """Stem a question with the same configuration the snowball index uses.

    Going through the database rather than reimplementing the stemmer is the
    point: the query and the corpus must be normalised identically, or the
    measurement is of two different analysers. The lemma analysers keep the same
    discipline by a different route -- one Python function normalises both sides
    (`analyse.Morphology.positioned`).
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
    analyser: Analyser = Analyser.SNOWBALL,
    normalisation: int = 0,
) -> list[Hit]:
    """Top-``limit`` chunks by ``ts_rank``, inside one jurisdiction.

    The authority filter is applied in the WHERE clause, before ranking, so a
    chunk from another jurisdiction cannot be retrieved and then filtered out --
    it is never a candidate (ADR-0002).

    Ties break on address so the ranking is fully deterministic; the regression
    gate depends on the same corpus and question producing the same result.

    ``analyser`` selects which `tsvector` column is queried and ``normalisation``
    which `ts_rank` normalisation flag is passed -- together, one cell of the
    grid. The column name comes from the `Analyser` enum, never from caller
    input, so it is composed as an identifier rather than interpolated.
    """
    _assert_normalisation(normalisation)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT address, citation, ts_rank({column}, query, %s) AS rank, "
                "authority_key FROM chunk, CAST(%s AS tsquery) AS query "
                "WHERE authority_key = %s AND effective_date = %s AND {column} @@ query "
                "ORDER BY rank DESC, address ASC LIMIT %s"
            ).format(column=sql.Identifier(analyser.column)),
            (normalisation, tsquery, authority_key, effective_date, limit),
        )
        return [
            Hit(
                position=position,
                address=str(row[0]),
                citation=str(row[1]),
                rank=float(str(row[2])),
                authority_key=str(row[3]),
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


def chunk_lexemes(
    conn: psycopg.Connection[tuple[object, ...]],
    addresses: Sequence[str],
    analyser: Analyser = Analyser.SNOWBALL,
) -> set[str]:
    """The union of normalised tokens in these chunks, as this analyser sees them.

    Used to measure how much of a question's own vocabulary is already sitting in
    the chunk it is supposed to retrieve -- see `metrics.lexical_leakage`. Read
    per analyser, because leakage is a property of the question *under an
    analyser*: words that snowball stems apart, lemmatisation may join, so the
    same golden set leaks differently in different cells. That is why each cell
    is gated against its own recorded leakage and never against another cell's.
    """
    if not addresses:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT DISTINCT entry.lexeme FROM chunk, unnest(chunk.{column}) AS entry "
                "WHERE chunk.address = ANY(%s)"
            ).format(column=sql.Identifier(analyser.column)),
            (list(addresses),),
        )
        return {str(row[0]) for row in cur.fetchall()}


def addresses_matching(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    addresses: Sequence[str],
    tsquery: str,
    analyser: Analyser = Analyser.SNOWBALL,
) -> set[str]:
    """Which of these chunks share *any* normalised token with the query.

    This is the miss diagnostic, and it is what chose this slice. A required
    chunk that was not retrieved is either unreachable (no shared token at all --
    a morphology failure, which lemmatisation is meant to fix) or reachable but
    out-ranked (a ranking failure, which is where the missing IDF would have
    helped). Pure arithmetic, no model, no cost.

    Run per cell, it also says whether lemmatisation did what it claimed: a
    zero-overlap miss that becomes ranked-out was reached by morphology and lost
    by ranking, which is a different fix from the one that was applied.
    """
    if not addresses:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT address FROM chunk, CAST(%s AS tsquery) AS query "
                "WHERE address = ANY(%s) AND {column} @@ query"
            ).format(column=sql.Identifier(analyser.column)),
            (tsquery, list(addresses)),
        )
        return {str(row[0]) for row in cur.fetchall()}


def _assert_normalisation(normalisation: int) -> None:
    if normalisation not in NORMALISATIONS:
        raise DatabaseError(
            f"ts_rank normalisation {normalisation} is not one of the settings under "
            f"measurement {NORMALISATIONS}. Adding one is a deliberate change to the "
            "grid, and every cell in the baseline is recorded against a fixed set."
        )


def snowball_stopwords(
    conn: psycopg.Connection[tuple[object, ...]], tokens: Iterable[str]
) -> frozenset[str]:
    """Which of these surface tokens the `finnish` configuration throws away.

    Asked of Postgres rather than answered from a vendored word list, so the
    lemma analysers stop on **exactly the decision snowball makes** -- `mitä`,
    `on`, `ja`, `olla` out; `kuinka`, `usein`, `monta` in. That keeps the grid
    honest: the only difference between the control cell and a lemma cell is how
    a kept word is normalised, not which words are kept.

    Without this the lemma cells would index and query `olla` -- a word in nearly
    every clause -- and the grid would be measuring
    lemmatisation-plus-no-stopping against snowball-plus-stopping. Two variables,
    one number.

    A token that yields no lexeme at all (punctuation, `§`) also lands here, which
    is the same thing snowball does with it.
    """
    wanted = sorted({token.lower() for token in tokens})
    if not wanted:
        return frozenset()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT token FROM unnest(%s::text[]) AS token "
            "WHERE to_tsvector(%s::regconfig, token) = ''::tsvector",
            (wanted, TEXT_SEARCH_CONFIG),
        )
        return frozenset(str(row[0]) for row in cur.fetchall())


def tsvector_literal(entries: Sequence[tuple[str, Sequence[int]]]) -> str:
    """Serialise (lexeme, positions) pairs into a `tsvector` literal.

    Built by hand rather than by round-tripping the lemmas through
    `to_tsvector('simple', ...)`, which would re-tokenise text that voikko has
    already tokenised and analysed -- a second tokeniser silently disagreeing
    with the first is exactly the class of bug this harness exists to catch.

    Positions are kept because `ts_rank` reads them as term frequencies. Dropping
    them would flatten every repeated term to a single occurrence and change the
    ranking under measurement.
    """
    if not entries:
        raise DatabaseError(
            "refusing to build an empty tsvector: a chunk that indexes to nothing "
            "is unretrievable, and would be scored as a retrieval failure"
        )
    parts: list[str] = []
    for lexeme, positions in entries:
        if not lexeme:
            raise DatabaseError("a tsvector lexeme cannot be empty")
        if not positions:
            raise DatabaseError(f"lexeme {lexeme!r} has no positions")
        joined = ",".join(str(position) for position in positions)
        parts.append(f"'{escape_lexeme(lexeme)}':{joined}")
    return " ".join(parts)


def chunk_bodies(conn: psycopg.Connection[tuple[object, ...]]) -> list[tuple[str, str]]:
    """Every chunk's address and body, in address order. The lemma indexer's input."""
    with conn.cursor() as cur:
        cur.execute("SELECT address, body FROM chunk ORDER BY address")
        return [(str(row[0]), str(row[1])) for row in cur.fetchall()]


def set_lemma_vectors(
    conn: psycopg.Connection[tuple[object, ...]],
    rows: Sequence[tuple[str, str, str, str]],
) -> int:
    """Write the three application-maintained `tsvector` columns.

    Takes `(address, base, safe, reasm)` literals. All three columns are written
    in one statement per chunk so a chunk can never end up with one analyser's
    index populated and another's empty -- a state that would look like a
    retrieval failure in exactly one cell.
    """
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE chunk SET lemma_base_tsv = CAST(%s AS tsvector), "
            "lemma_safe_tsv = CAST(%s AS tsvector), "
            "lemma_reasm_tsv = CAST(%s AS tsvector) WHERE address = %s",
            [(base, safe, reasm, address) for address, base, safe, reasm in rows],
        )
    return len(rows)


def assert_lemma_vectors_populated(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    """Every chunk has a non-empty index in every analyser's column.

    The invariant the generated `tsv` column gets from Postgres for free, and the
    three written columns have to earn. An empty lemma vector is not a small bug:
    the chunk becomes unretrievable in that cell, the question scores as a miss,
    and the miss is attributed to the analyser rather than to the ingest.
    """
    for analyser in Analyser:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT count(*) FROM chunk WHERE {column} = ''::tsvector").format(
                    column=sql.Identifier(analyser.column)
                )
            )
            row = cur.fetchone()
        empty = 0 if row is None else int(str(row[0]))
        if empty:
            raise DatabaseError(
                f"{empty} chunk(s) have an empty {analyser.column} index, so they are "
                f"unretrievable in the {analyser} cells and would be scored as "
                "retrieval misses. The ingest did not populate them."
            )


def lexeme_counts(conn: psycopg.Connection[tuple[object, ...]]) -> dict[Analyser, int]:
    """Total distinct lexemes indexed per analyser, over the whole corpus.

    Reported because it is the evidence for the grid's second axis. Compound
    splitting inflates the number of lexemes in a chunk, and `ts_rank` at
    normalisation 0 rewards accumulated term weight -- so the analyser change and
    the normalisation change interact, and measuring them in sequence would
    confound exactly the interaction worth seeing.
    """
    columns = sql.SQL(", ").join(
        sql.SQL("sum(length({column}))").format(column=sql.Identifier(analyser.column))
        for analyser in Analyser
    )
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT {columns} FROM chunk").format(columns=columns))
        row = cur.fetchone()
    if row is None or row[0] is None:
        raise DatabaseError("the corpus is empty, so it has no lexeme counts")
    return {analyser: int(str(row[index])) for index, analyser in enumerate(Analyser)}

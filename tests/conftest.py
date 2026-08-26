"""Shared fixtures.

The database-backed tests are the only ones that exercise the harness end to end
-- extraction, chunking, addressing, indexing and ranking together -- so they
carry most of the suite's real weight. They skip when Postgres is unreachable,
and the skip reason says so loudly: a skipped integration test proves nothing,
and `make gate` passing without it means only that the pure functions are sound.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from fi_rag_eval import db
from fi_rag_eval.golden import GoldenSet, load_golden_set
from fi_rag_eval.ingest import ingest
from fi_rag_eval.manifest import Manifest, load_manifest

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "corpus" / "manifest.yaml"
GOLDEN = REPO / "corpus" / "golden" / "lounais-suomi.yaml"
RAW_DIR = REPO / "data" / "raw"


@pytest.fixture(scope="session")
def manifest() -> Manifest:
    return load_manifest(MANIFEST)


@pytest.fixture(scope="session")
def golden(manifest: Manifest) -> GoldenSet:
    return load_golden_set(GOLDEN, manifest)


@pytest.fixture(scope="session")
def corpus(manifest: Manifest) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """A live database with the real corpus ingested. Session-scoped: one load."""
    try:
        conn = db.connect()
    except db.DatabaseError as exc:
        pytest.skip(f"no database, so the end-to-end tests did not run: {exc}")
    try:
        ingest(conn, manifest, RAW_DIR)
        yield conn
    finally:
        conn.close()

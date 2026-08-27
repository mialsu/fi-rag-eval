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
from fi_rag_eval.analyse import AnalyserError, Morphology
from fi_rag_eval.evaluate import GridRun, evaluate_grid
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
def morphology() -> Morphology:
    """The voikko analyser, or a loud skip.

    The dictionary (`voikko-fi`) is a system package that `uv sync` cannot supply,
    so this can be absent on a clean machine. The pure tests in
    `test_analyse.py` still run and still pin the reassembly rule; what skips here
    is only the proof that the recorded fixtures match today's dictionary.
    """
    try:
        return Morphology.open()
    except AnalyserError as exc:
        pytest.skip(f"no Finnish analyser, so the morphology tests did not run: {exc}")


@pytest.fixture(scope="session")
def corpus(
    manifest: Manifest, morphology: Morphology
) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """A live database with the real corpus ingested. Session-scoped: one load.

    Takes the analyser explicitly so the whole suite shares one dictionary load
    and one lemma cache, and so an absent dictionary skips here for the same
    stated reason rather than failing deep inside the ingest.
    """
    try:
        conn = db.connect()
    except db.DatabaseError as exc:
        pytest.skip(f"no database, so the end-to-end tests did not run: {exc}")
    try:
        ingest(conn, manifest, RAW_DIR, morphology)
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="session")
def grid(
    corpus: psycopg.Connection[tuple[object, ...]],
    manifest: Manifest,
    golden: GoldenSet,
    morphology: Morphology,
) -> GridRun:
    """Every cell, scored once. Session-scoped because several tests read it.

    This is the same computation `make eval` performs, so a test asserting
    against it is asserting against the published measurement rather than a
    re-implementation of it.
    """
    return evaluate_grid(corpus, manifest=manifest, golden=golden, k=5, morphology=morphology)

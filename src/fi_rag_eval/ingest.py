"""Ingestion: manifest -> PDF -> chunks -> Postgres, with the instrument checked.

Every step that could silently change the corpus is asserted against the
manifest, because the golden labels point into the corpus by hand and a silent
re-parse destroys them.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import psycopg

from fi_rag_eval import db
from fi_rag_eval.chunking import Chunk, Clause, chunk_clauses, parse_toc, split_clauses
from fi_rag_eval.extract import Extraction, extract
from fi_rag_eval.manifest import Authority, Manifest, Source

_VOIMAANTULO = re.compile(r"tulevat\s+voimaan\s+(\d{1,2})\.(\d{1,2})\.(\d{4})")
_DOWNLOAD_TIMEOUT_SECONDS = 60


class IngestError(RuntimeError):
    """A source did not ingest the way the manifest says it must."""


@dataclass(frozen=True, slots=True)
class SourceReport:
    authority_key: str
    effective_date: date
    clauses: int
    chunks: int
    definitions: int
    hyphen_joins: int
    conjunction_guards: int
    page_breaks: int
    downloaded: bool


@dataclass(frozen=True, slots=True)
class IngestReport:
    sources: tuple[SourceReport, ...]

    @property
    def chunks(self) -> int:
        return sum(source.chunks for source in self.sources)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(source: Source, raw_dir: Path) -> tuple[Path, bool]:
    """Make sure the source PDF is on disk and is the one the manifest pins.

    Returns the path and whether it had to be downloaded. A checksum mismatch is
    a hard error rather than a re-download: the manifest names one document, and
    silently accepting a different one changes what every label means.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / source.filename
    if target.is_file():
        actual = sha256_of(target)
        if actual == source.sha256:
            return target, False
        raise IngestError(
            f"{target} does not match the manifest.\n"
            f"  manifest: {source.sha256}\n"
            f"  on disk:  {actual}\n"
            "Delete the file to re-download, but understand first why it changed: "
            "every golden label points into this document."
        )

    if urllib.parse.urlparse(source.url).scheme != "https":
        raise IngestError(
            f"manifest source url must be https, got {source.url!r}. The corpus is "
            "public documents fetched over a verified channel, nothing else."
        )
    with urllib.request.urlopen(source.url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:
        payload = response.read()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != source.sha256:
        raise IngestError(
            f"downloaded {source.url} but its checksum is {actual}, not the "
            f"{source.sha256} the manifest pins. The published document has changed; "
            "re-label deliberately rather than ingesting a different text."
        )
    target.write_bytes(payload)
    return target, True


def read_effective_date(clauses: Sequence[Clause]) -> date:
    """Read the in-force date out of the document, per ADR-0004's closing note.

    The date is *not* taken from the manifest -- the manifest's copy is checked
    against this one. The front matter of this document advertises three dates
    (approved 30.5.2024, in force 1.8.2024, 25 § amended 22.10.2025), so a
    guess is exactly what ADR-0004 forbids.
    """
    matches = {
        date(int(m[3]), int(m[2]), int(m[1]))
        for clause in clauses
        for m in _VOIMAANTULO.finditer(clause.body)
    }
    if len(matches) != 1:
        raise IngestError(
            "could not read a single in-force date out of the document; found "
            f"{sorted(matches) or 'none'}. Refusing to guess: the effective date is "
            "part of every chunk address."
        )
    return matches.pop()


def prepare(source: Source, raw_dir: Path) -> tuple[Extraction, list[Clause], list[Chunk], bool]:
    path, downloaded = fetch(source, raw_dir)
    extraction = extract(path)
    clauses = split_clauses(extraction.text, parse_toc(extraction.toc))
    chunks = chunk_clauses(clauses)

    read = read_effective_date(clauses)
    if read != source.effective_date:
        raise IngestError(
            f"{source.filename}: the document says it comes into force {read}, the "
            f"manifest says {source.effective_date}. The effective date is part of "
            "every chunk address, so this is a hard error."
        )

    definitions = sum(1 for chunk in chunks if chunk.sub_key is not None)
    actual = (len(clauses), len(chunks), definitions)
    expected = (source.expected.clauses, source.expected.chunks, source.expected.definitions)
    if actual != expected:
        raise IngestError(
            f"{source.filename} parsed to {actual[0]} clauses / {actual[1]} chunks / "
            f"{actual[2]} definitions, but the manifest expects "
            f"{expected[0]} / {expected[1]} / {expected[2]}.\n"
            "The chunker or the document changed. Every hand-written golden label "
            "points into this parse, so the harness refuses to load a different one. "
            "Update corpus/manifest.yaml only after checking the labels still hold."
        )
    return extraction, clauses, chunks, downloaded


def ingest(
    conn: psycopg.Connection[tuple[object, ...]],
    manifest: Manifest,
    raw_dir: Path,
) -> IngestReport:
    """Reload the whole corpus. Ingestion is never incremental, by design."""
    db.assert_finnish_config(conn)
    db.create_schema(conn)

    reports: list[SourceReport] = []
    for authority in manifest.authorities:
        db.insert_authority(conn, authority)
        for source in authority.sources:
            reports.append(_ingest_source(conn, authority, source, raw_dir))
    conn.commit()
    return IngestReport(sources=tuple(reports))


def _ingest_source(
    conn: psycopg.Connection[tuple[object, ...]],
    authority: Authority,
    source: Source,
    raw_dir: Path,
) -> SourceReport:
    extraction, clauses, chunks, downloaded = prepare(source, raw_dir)
    db.insert_source(conn, authority.key, source)
    loaded = db.insert_chunks(
        conn,
        authority_key=authority.key,
        effective_date=source.effective_date,
        chunks=chunks,
    )
    if loaded != len(chunks):  # pragma: no cover - executemany is all-or-nothing
        raise IngestError(f"{source.filename}: loaded {loaded} of {len(chunks)} chunks")
    return SourceReport(
        authority_key=authority.key,
        effective_date=source.effective_date,
        clauses=len(clauses),
        chunks=len(chunks),
        definitions=sum(1 for chunk in chunks if chunk.sub_key is not None),
        hyphen_joins=extraction.hyphen_joins,
        conjunction_guards=extraction.conjunction_guards,
        page_breaks=extraction.page_breaks,
        downloaded=downloaded,
    )

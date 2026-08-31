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
from fi_rag_eval.analyse import LEMMA_ANALYSERS, Analyser, Morphology
from fi_rag_eval.chunking import Chunk, Clause, chunk_clauses, parse_toc, split_clauses
from fi_rag_eval.extract import Extraction, extract
from fi_rag_eval.manifest import Authority, Manifest, Source

_VOIMAANTULO = re.compile(r"tulevat\s+voimaan\s+(\d{1,2})\.(\d{1,2})\.(\d{4})")
_FRONT_MATTER_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_DOWNLOAD_TIMEOUT_SECONDS = 60

USER_AGENT = "fi-rag-eval/0.0 (evaluation harness; fetches public waste regulations)"
"""Identify the fetcher. Not cosmetic: without it a clean clone cannot ingest.

`urllib` sends `Python-urllib/<version>`, and **tampere.fi answers that with
HTTP 403** while serving the same public PDF to a request that names itself. The
document is public, the manifest pins its sha256, and this string says truthfully
what is asking -- it does not pretend to be a browser. Found the only way it could
be: by running `make eval` in a genuinely clean clone, where the PDFs are absent
because `data/raw/` is git-ignored.
"""


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
class LemmaIndexReport:
    """What the Python-side analyser did, and enough of it to be checked by eye.

    The fingerprint is the load-bearing field: `libvoikko` reports the *library*
    version but not the *dictionary* version, and it is the dictionary that
    decides the numbers.
    """

    library_version: str
    fingerprint: str
    word_tokens: int
    unique_words: int
    stopped_tokens: int
    unanalysable_words: int
    lexemes: tuple[tuple[Analyser, int], ...]

    @property
    def unanalysable_share(self) -> float:
        return self.unanalysable_words / self.unique_words if self.unique_words else 0.0


@dataclass(frozen=True, slots=True)
class IngestReport:
    sources: tuple[SourceReport, ...]
    lemmas: LemmaIndexReport

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
    request = urllib.request.Request(source.url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:
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


def fetch_sources(manifest: Manifest, raw_dir: Path) -> tuple[tuple[Path, bool], ...]:
    """Put every manifest source on disk, verified, and touch no database.

    Exists for the container build (`SPEC-mvp-demo` tracer 4): the PDFs are
    gitignored, so an image that wants them baked in has to fetch them at build
    time -- and at build time there is no Postgres to ingest into. `ingest` does
    both jobs and cannot be used for half of one.

    The verification is `fetch`'s, unchanged: a checksum mismatch is a hard error,
    because silently accepting a different document changes what every golden
    label means.
    """
    return tuple(
        fetch(source, raw_dir) for authority in manifest.authorities for source in authority.sources
    )


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


def read_front_matter_dates(front_matter: str) -> tuple[date, ...]:
    """Every ``DD.MM.YYYY`` date in the front matter, sorted and de-duplicated.

    This is what makes the manifest's `edition` label falsifiable instead of a
    hand-written string nobody can check. The front matter is where an authority
    records its approval and amendment history -- Pirkanmaa's reads *"Hyväksytty
    ... 19.5.2021, päivitetty 7.6.2023, 6.3.2024, 9.4.2025 ja 22.10.2025"* -- so a
    republished document with a sixth amendment changes this list, and ingest
    refuses to load it under the old edition label.

    Deliberately shape-agnostic: it does not try to understand *which* date is
    the approval and which the amendments, because the two documents in the
    corpus already write that three different ways. It only has to detect change.
    """
    return tuple(
        sorted(
            {
                date(int(year), int(month), int(day))
                for day, month, year in _FRONT_MATTER_DATE.findall(front_matter)
            }
        )
    )


def assert_edition(source: Source, front_matter: str) -> None:
    """The manifest's edition label must still match the document's own history.

    Without this the label is a hand-written string with nothing tying it to the
    PDF -- and an unverifiable edition on every citation is the same defect as an
    unverifiable metric in the README, just aimed at a human reader instead of at
    CI. Pirkanmaa's text has been amended five times since the Voimaantulo date
    its address keys on, so the citation is the only place a reader learns which
    of the six editions they are being shown (slice 4, D3).
    """
    dates = read_front_matter_dates(front_matter)
    if dates != source.edition.front_matter_dates:
        raise IngestError(
            f"{source.filename}: the front matter carries the dates "
            f"{[d.isoformat() for d in dates]}, the manifest's edition "
            f"{source.edition.label!r} was recorded against "
            f"{[d.isoformat() for d in source.edition.front_matter_dates]}.\n"
            "The document's approval or amendment history has moved, so the edition "
            "label every citation carries is now wrong. Read the new front matter and "
            "update the edition deliberately -- an edition nobody checked is exactly "
            "the misleading citation the edition field exists to prevent."
        )


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

    assert_edition(source, extraction.front_matter)

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
    morphology: Morphology | None = None,
) -> IngestReport:
    """Reload the whole corpus. Ingestion is never incremental, by design."""
    db.assert_finnish_config(conn)
    db.create_schema(conn)

    reports: list[SourceReport] = []
    for authority in manifest.authorities:
        db.insert_authority(conn, authority)
        for source in authority.sources:
            reports.append(_ingest_source(conn, authority, source, raw_dir))
    lemmas = index_lemmas(conn, morphology or Morphology.open())
    conn.commit()
    return IngestReport(sources=tuple(reports), lemmas=lemmas)


def index_lemmas(
    conn: psycopg.Connection[tuple[object, ...]], morphology: Morphology
) -> LemmaIndexReport:
    """Build the three lemma `tsvector` columns for every chunk already loaded.

    Runs once over the whole corpus rather than per source, because the stopword
    decision is asked of Postgres in a single round trip and the analyser cache
    then pays for itself: this corpus has 6.4k word tokens over 2.5k distinct
    forms, so three quarters of the analysis calls are repeats.
    """
    bodies = db.chunk_bodies(conn)
    if not bodies:
        raise IngestError(
            "no chunks to index. A lemma index built over an empty corpus would "
            "make every question a miss and blame the analyser for it."
        )
    if LEMMA_ANALYSERS != (
        Analyser.LEMMA_BASEFORM,
        Analyser.LEMMA_SAFE,
        Analyser.LEMMA_REASM,
    ):  # pragma: no cover - a guard against a silent column/argument mismatch
        raise IngestError(
            f"lemma analyser order changed to {LEMMA_ANALYSERS}; "
            "db.set_lemma_vectors takes (base, safe, reasm) positionally"
        )

    tokens = [word for _, body in bodies for word in morphology.words(body)]
    stopwords = db.snowball_stopwords(conn, tokens)
    unique = sorted(set(tokens))

    rows: list[tuple[str, str, str, str]] = []
    for address, body in bodies:
        literals = [
            db.tsvector_literal(morphology.positioned(body, analyser, stopwords=stopwords))
            for analyser in LEMMA_ANALYSERS
        ]
        rows.append((address, literals[0], literals[1], literals[2]))
    written = db.set_lemma_vectors(conn, rows)
    if written != len(bodies):  # pragma: no cover - executemany is all-or-nothing
        raise IngestError(f"indexed {written} of {len(bodies)} chunks")
    db.assert_lemma_vectors_populated(conn)

    return LemmaIndexReport(
        library_version=morphology.library_version,
        fingerprint=morphology.fingerprint(),
        word_tokens=len(tokens),
        unique_words=len(unique),
        stopped_tokens=sum(1 for token in tokens if token.lower() in stopwords),
        unanalysable_words=sum(1 for word in unique if not morphology.readings(word)),
        lexemes=tuple(db.lexeme_counts(conn).items()),
    )


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
        document=source.document,
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

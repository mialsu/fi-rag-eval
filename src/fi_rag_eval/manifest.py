"""The checked-in source inventory.

Raw documents stay out of git, so the manifest is what makes ingestion
reproducible. It also carries the *expected* parse -- clause, chunk and
definition counts -- because a document that silently parses differently
invalidates every hand-written golden label pointing into it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_VERSION = 1


class ManifestError(ValueError):
    """The manifest is missing, malformed, or disagrees with itself."""


@dataclass(frozen=True, slots=True)
class ExpectedParse:
    """What the chunker produced when the golden set was labelled by hand."""

    clauses: int
    chunks: int
    definitions: int


@dataclass(frozen=True, slots=True)
class Source:
    filename: str
    title: str
    url: str
    sha256: str
    effective_date: date
    expected: ExpectedParse


@dataclass(frozen=True, slots=True)
class Authority:
    key: str
    name: str
    municipalities: tuple[str, ...]
    sources: tuple[Source, ...]


@dataclass(frozen=True, slots=True)
class Manifest:
    authorities: tuple[Authority, ...]

    def authority(self, key: str) -> Authority:
        for authority in self.authorities:
            if authority.key == key:
                return authority
        known = ", ".join(a.key for a in self.authorities) or "none"
        raise ManifestError(f"unknown authority {key!r}; the manifest lists: {known}")

    def resolve_municipality(self, municipality: str) -> Authority:
        """Resolve a *kunta* to the authority that publishes its regulations.

        The resident says "Turku" and means an 18-municipality document
        (ADR-0002). Ambiguity is a hard error rather than a first match: two
        authorities claiming one municipality is a manifest bug, and silently
        picking one is exactly the cross-jurisdiction answer the filter exists
        to prevent.
        """
        folded = municipality.casefold()
        matches = [
            a for a in self.authorities if any(m.casefold() == folded for m in a.municipalities)
        ]
        if not matches:
            raise ManifestError(
                f"no authority in the manifest covers the municipality {municipality!r}"
            )
        if len(matches) > 1:
            raise ManifestError(
                f"municipality {municipality!r} is claimed by "
                f"{[a.key for a in matches]}; a municipality has exactly one authority"
            )
        return matches[0]


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ManifestError(f"{where}: missing required key {key!r}")
    return mapping[key]


def _parse_date(value: Any, where: str) -> date:
    if isinstance(value, date):
        return value
    raise ManifestError(f"{where}: effective_date must be a YYYY-MM-DD date, got {value!r}")


def _parse_source(raw: Mapping[str, Any], where: str) -> Source:
    expected = _require(raw, "expected", where)
    if not isinstance(expected, Mapping):
        raise ManifestError(f"{where}: expected must be a mapping")
    return Source(
        filename=str(_require(raw, "filename", where)),
        title=str(_require(raw, "title", where)),
        url=str(_require(raw, "url", where)),
        sha256=str(_require(raw, "sha256", where)).lower(),
        effective_date=_parse_date(_require(raw, "effective_date", where), where),
        expected=ExpectedParse(
            clauses=int(_require(expected, "clauses", where)),
            chunks=int(_require(expected, "chunks", where)),
            definitions=int(_require(expected, "definitions", where)),
        ),
    )


def load_manifest(path: Path) -> Manifest:
    if not path.is_file():
        raise ManifestError(f"manifest not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ManifestError(f"{path}: expected a mapping at the top level")
    version = _require(document, "version", str(path))
    if version != SUPPORTED_VERSION:
        raise ManifestError(f"{path}: manifest version {version!r}, expected {SUPPORTED_VERSION}")

    raw_authorities = _require(document, "authorities", str(path))
    if not isinstance(raw_authorities, Sequence) or not raw_authorities:
        raise ManifestError(f"{path}: authorities must be a non-empty list")

    authorities: list[Authority] = []
    for raw in raw_authorities:
        if not isinstance(raw, Mapping):
            raise ManifestError(f"{path}: each authority must be a mapping")
        key = str(_require(raw, "key", str(path)))
        where = f"{path} authority {key!r}"
        raw_sources = _require(raw, "sources", where)
        if not isinstance(raw_sources, Sequence) or not raw_sources:
            raise ManifestError(f"{where}: sources must be a non-empty list")
        raw_municipalities = _require(raw, "municipalities", where)
        if not isinstance(raw_municipalities, Sequence) or not raw_municipalities:
            raise ManifestError(f"{where}: municipalities must be a non-empty list")
        authorities.append(
            Authority(
                key=key,
                name=str(_require(raw, "name", where)),
                municipalities=tuple(str(m) for m in raw_municipalities),
                sources=tuple(_parse_source(s, where) for s in raw_sources),
            )
        )

    keys = [a.key for a in authorities]
    if len(set(keys)) != len(keys):
        raise ManifestError(f"{path}: duplicate authority keys in {keys}")
    return Manifest(authorities=tuple(authorities))

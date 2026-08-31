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
    """The manifest is missing, malformed, or disagrees with itself.

    Carries an optional **Finnish** sentence beside the English one. Almost every
    `ManifestError` is a maintainer-facing parse failure that stops the process at
    startup, and those leave `finnish` as `None`. The four raised by
    `resolve_municipality` are different: they are the only ones a *resident* can
    provoke, and `CLAUDE.md`'s definition of done requires the copy they read to be
    in their own language. The two texts live at the same raise site so the nuance
    -- Sastamala's partial coverage in particular -- cannot drift between them, and
    so the demo surface never has to recover a reason by matching on a message.
    """

    def __init__(self, message: str, *, finnish: str | None = None) -> None:
        super().__init__(message)
        self.finnish = finnish


@dataclass(frozen=True, slots=True)
class ExpectedParse:
    """What the chunker produced when the golden set was labelled by hand."""

    clauses: int
    chunks: int
    definitions: int


@dataclass(frozen=True, slots=True)
class Edition:
    """Which published revision of a document this is, and how that claim is checked.

    The chunk address keys on Voimaantulo (ADR-0004), which is the date the
    document's own text declares. For Pirkanmaa that date is 2021-07-01 while the
    authority publishes the text as "1.5.2026 alkaen" after five amendments, so
    the address alone tells a human something true and misleading at once. The
    edition is therefore declared here and carried into the citation, where it is
    actually read (slice 4, D3).

    `front_matter_dates` is what stops `label` from being an unfalsifiable
    hand-written string: ingest reads every date out of the document's front
    matter and refuses to load a document whose amendment history has moved.
    """

    label: str
    """Human-facing, verbatim from how the authority publishes it: "1.5.2026 alkaen"."""

    front_matter_dates: tuple[date, ...]
    """Every date in the front matter, sorted. Asserted at ingest, never assumed."""


@dataclass(frozen=True, slots=True)
class Source:
    filename: str
    title: str
    url: str
    sha256: str
    effective_date: date
    edition: Edition
    expected: ExpectedParse

    @property
    def document(self) -> str:
        """How a citation names this document: title plus the edition a human reads."""
        return f"{self.title}, {self.edition.label}"


@dataclass(frozen=True, slots=True)
class Authority:
    key: str
    name: str
    municipalities: tuple[str, ...]
    partial_municipalities: tuple[tuple[str, str], ...]
    """Kunnat this authority covers only *in part*, with the part named.

    Deliberately **not** merged into `municipalities`: a partially covered kunta
    must not resolve, because most of its residents are bound by a different
    authority's rules and answering them from this one is failure mode #1 with a
    correct-looking citation (slice 4, D4). It is recorded rather than dropped so
    the refusal can say *why*, and so the counterexample to ADR-0002's
    one-authority-per-municipality model stays visible in the data.
    """

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

        **An absent municipality is refused rather than defaulted** (slice 5,
        AC14). `CLAUDE.md`'s third verification layer requires that asking with
        no municipality set must not silently pick one, and the cheapest place to
        guarantee that is here: nothing downstream can reach a corpus without an
        authority key, and this is where the key comes from. A default would be
        indefensible whichever way it fell -- the first authority in the manifest
        is arbitrary, and the largest is a guess about the asker.
        """
        if not municipality.strip():
            raise ManifestError(
                "no municipality was given, so there is no authority to answer from. "
                "The harness refuses rather than picking one: every answer is bound to "
                "the jurisdiction it was asked about, and a defaulted jurisdiction is "
                "the cross-municipality answer the hard filter exists to prevent "
                "(DESIGN.md:15,67), wearing a correct-looking citation.",
                finnish=(
                    "Kuntaa ei ole valittu, joten ei ole viranomaista, jonka määräyksistä "
                    "vastaus voisi tulla. Kunta on valittava itse: jos järjestelmä "
                    "valitsisi sen puolestasi, vastaus voisi tulla väärän viranomaisen "
                    "määräyksistä oikean näköisen viittauksen kanssa."
                ),
            )
        folded = municipality.casefold()
        matches = [
            a for a in self.authorities if any(m.casefold() == folded for m in a.municipalities)
        ]
        if not matches:
            partial = [
                (a, part)
                for a in self.authorities
                for kunta, part in a.partial_municipalities
                if kunta.casefold() == folded
            ]
            if partial:
                # The part is quoted rather than paraphrased: it is the authority's
                # own Finnish, and it is rendered verbatim to a resident below.
                detail = "; ".join(f'{a.key} covers only "{part}"' for a, part in partial)
                suomeksi = "; ".join(f"{a.name} kattaa kunnasta vain {part}" for a, part in partial)
                raise ManifestError(
                    f"the municipality {municipality!r} is covered only in part: {detail}. "
                    "These regulations bind part of the kunta and not the rest, so the "
                    "harness refuses rather than answering a resident from rules that may "
                    "not bind them. A municipality does not always resolve to exactly one "
                    "authority (ADR-0002, amended).",
                    finnish=(
                        f"Kunta {municipality} kuuluu tämän aineiston piiriin vain "
                        "osittain, joten nämä määräykset sitovat osaa kunnasta eivätkä "
                        "muuta osaa. Järjestelmä kieltäytyy vastaamasta sen sijaan, että "
                        "se vastaisi määräyksistä, jotka eivät ehkä sido sinua. "
                        f"Osittainen kattavuus: {suomeksi}."
                    ),
                )
            raise ManifestError(
                f"no authority in the manifest covers the municipality {municipality!r}",
                finnish=(
                    f"Kuntaa {municipality} ei ole tässä aineistossa. Valitse kunta "
                    "valikosta -- aineisto kattaa vain kahden jätehuoltoviranomaisen "
                    "alueen."
                ),
            )
        if len(matches) > 1:
            raise ManifestError(
                f"municipality {municipality!r} is claimed by "
                f"{[a.key for a in matches]}; a municipality has exactly one authority",
                finnish=(
                    f"Kunnalle {municipality} löytyy aineistosta useampi kuin yksi "
                    "viranomainen, joten oikeaa ei voi valita. Tämä on virhe "
                    "aineistossa, ei kysymyksessä."
                ),
            )
        return matches[0]


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ManifestError(f"{where}: missing required key {key!r}")
    return mapping[key]


def _parse_date(value: Any, where: str) -> date:
    if isinstance(value, date):
        return value
    raise ManifestError(f"{where}: expected a YYYY-MM-DD date, got {value!r}")


def _parse_edition(raw: Any, where: str) -> Edition:
    if not isinstance(raw, Mapping):
        raise ManifestError(f"{where}: edition must be a mapping with label and dates")
    label = str(_require(raw, "label", where)).strip()
    if not label:
        raise ManifestError(f"{where}: edition label must not be empty")
    raw_dates = _require(raw, "front_matter_dates", where)
    if not isinstance(raw_dates, Sequence) or isinstance(raw_dates, str) or not raw_dates:
        raise ManifestError(f"{where}: edition front_matter_dates must be a non-empty list")
    dates = tuple(sorted(_parse_date(value, f"{where} edition") for value in raw_dates))
    return Edition(label=label, front_matter_dates=dates)


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
        edition=_parse_edition(_require(raw, "edition", where), where),
        expected=ExpectedParse(
            clauses=int(_require(expected, "clauses", where)),
            chunks=int(_require(expected, "chunks", where)),
            definitions=int(_require(expected, "definitions", where)),
        ),
    )


def _parse_partial_municipalities(raw: Any, where: str) -> tuple[tuple[str, str], ...]:
    """Kunnat covered only in part, as ``kunta: the part covered``.

    Optional, and empty for an authority whose area is whole kunnat. Pirkanmaa's
    1 § claims Sastamala only "Mouhijärven ja Suodenniemen osalta", which is the
    counterexample to ADR-0002 (slice 4, D4).
    """
    if raw is None:
        return ()
    if not isinstance(raw, Mapping) or not raw:
        raise ManifestError(
            f"{where}: partial_municipalities must be a non-empty mapping of "
            "kunta -> the part of it this authority covers"
        )
    return tuple((str(kunta), str(part)) for kunta, part in raw.items())


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
        municipalities = tuple(str(m) for m in raw_municipalities)
        partial = _parse_partial_municipalities(raw.get("partial_municipalities"), where)
        folded = {m.casefold() for m in municipalities}
        overlap = sorted(kunta for kunta, _ in partial if kunta.casefold() in folded)
        if overlap:
            raise ManifestError(
                f"{where}: {overlap} are listed both as fully and as partially covered. "
                "A partially covered kunta must not resolve, so listing it in both places "
                "would make the refusal unreachable."
            )
        authorities.append(
            Authority(
                key=key,
                name=str(_require(raw, "name", where)),
                municipalities=municipalities,
                partial_municipalities=partial,
                sources=tuple(_parse_source(s, where) for s in raw_sources),
            )
        )

    keys = [a.key for a in authorities]
    if len(set(keys)) != len(keys):
        raise ManifestError(f"{path}: duplicate authority keys in {keys}")
    return Manifest(authorities=tuple(authorities))

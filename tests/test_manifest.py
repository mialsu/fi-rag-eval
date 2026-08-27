"""The manifest: the edition a citation names, and who covers which kunta.

Slice 4 adds two things worth their own tests. The **edition** is the only place
a human learns which of six published revisions of Pirkanmaa's text they are
reading, because the chunk address keys on a Voimaantulo date five amendments
old (D3). **Partial coverage** is the counterexample to ADR-0002's model: a
municipality does not always resolve to exactly one authority (D4).
"""

from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path

import pytest

from fi_rag_eval.ingest import IngestError, assert_edition, read_front_matter_dates
from fi_rag_eval.manifest import ManifestError, load_manifest

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "corpus" / "manifest.yaml"

# Copied verbatim from what `extract` returns for each source. Committed so the
# parser is tested against the two real shapes and not against an invented one.
LOUNAIS_FRONT = (
    "Lounais-Suomen jätehuoltolautakunta 30.5.2024 § 17 (12245-2022)\n"
    "Jätehuoltomääräykset\nLounais-Suomessa\n"
    "Määräykset ovat voimassa 1.8.2024 lähtien seuraavissa kunnissa ja kaupungeissa:\n"
    "25 §:n muutos Lounais-Suomen jätehuoltolautakunta 22.10.2025 § 12245-2022\n"
)
PIRKANMAA_FRONT = (
    "Kunnalliset jätehuoltomääräykset\n"
    "  (Hyväksytty alueellisessa jätehuoltolautakunnassa 19.5.2021, § 27,\n"
    "päivitetty 7.6.2023 § 25, 6.3.2024 § 13, 9.4.2025 § 18 ja 22.10.2025 § 49)\n"
)


def test_front_matter_dates_are_read_from_the_two_real_shapes() -> None:
    """Deliberately shape-agnostic: it detects change, it does not interpret."""
    assert read_front_matter_dates(LOUNAIS_FRONT) == (
        date(2024, 5, 30),
        date(2024, 8, 1),
        date(2025, 10, 22),
    )
    assert read_front_matter_dates(PIRKANMAA_FRONT) == (
        date(2021, 5, 19),
        date(2023, 6, 7),
        date(2024, 3, 6),
        date(2025, 4, 9),
        date(2025, 10, 22),
    )


def test_a_repeated_date_is_counted_once() -> None:
    assert read_front_matter_dates("1.7.2021 ja uudelleen 1.7.2021") == (date(2021, 7, 1),)


def test_the_declared_edition_matches_both_real_documents() -> None:
    manifest = load_manifest(MANIFEST)
    assert_edition(manifest.authority("lounais-suomi").sources[0], LOUNAIS_FRONT)
    assert_edition(manifest.authority("pirkanmaa").sources[0], PIRKANMAA_FRONT)


def test_a_sixth_amendment_fails_the_ingest_rather_than_going_unnoticed() -> None:
    """The gate seen red: the authority republishes, the edition label goes stale."""
    source = load_manifest(MANIFEST).authority("pirkanmaa").sources[0]
    republished = PIRKANMAA_FRONT.replace("§ 49)", "§ 49, 14.1.2026 § 3)")
    with pytest.raises(IngestError, match="approval or amendment history has moved"):
        assert_edition(source, republished)


def test_the_citation_names_the_edition_a_human_reads() -> None:
    """AC7: not the 2021 Voimaantulo date the address is keyed on."""
    manifest = load_manifest(MANIFEST)
    document = manifest.authority("pirkanmaa").sources[0].document
    assert document == "Kunnalliset jätehuoltomääräykset, 1.5.2026 alkaen"
    assert "2021" not in document


def test_the_real_manifest_declares_an_edition_for_every_source() -> None:
    for authority in load_manifest(MANIFEST).authorities:
        for source in authority.sources:
            assert source.edition.label
            assert source.edition.front_matter_dates


BARE = textwrap.dedent(
    """\
    version: 1
    authorities:
      - key: a
        name: A
        municipalities: [Alpha]
    {extra}
        sources:
          - filename: a.pdf
            title: T
            url: https://example.invalid/a.pdf
            sha256: ab
            effective_date: 2024-08-01
    {edition}
            expected: {{clauses: 1, chunks: 1, definitions: 0}}
    """
)
EDITION = "        edition:\n          label: L\n          front_matter_dates: [2024-08-01]"


def write(tmp_path: Path, *, extra: str = "", edition: str = EDITION) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(BARE.format(extra=extra, edition=edition), encoding="utf-8")
    return path


def test_a_source_without_an_edition_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="missing required key 'edition'"):
        load_manifest(write(tmp_path, edition=""))


def test_an_empty_edition_label_is_rejected(tmp_path: Path) -> None:
    edition = "        edition:\n          label: ''\n          front_matter_dates: [2024-08-01]"
    with pytest.raises(ManifestError, match="label must not be empty"):
        load_manifest(write(tmp_path, edition=edition))


def test_an_edition_with_no_dates_is_rejected(tmp_path: Path) -> None:
    """A label with nothing to check it against is the thing the field prevents."""
    edition = "        edition:\n          label: L\n          front_matter_dates: []"
    with pytest.raises(ManifestError, match="front_matter_dates must be a non-empty list"):
        load_manifest(write(tmp_path, edition=edition))


def test_a_kunta_listed_as_both_whole_and_partial_is_rejected(tmp_path: Path) -> None:
    """Listing it in both places would make the refusal unreachable."""
    extra = "    partial_municipalities:\n      Alpha: only the north"
    with pytest.raises(ManifestError, match="both as fully and as partially covered"):
        load_manifest(write(tmp_path, extra=extra))


def test_partial_coverage_is_optional(tmp_path: Path) -> None:
    manifest = load_manifest(write(tmp_path))
    assert manifest.authority("a").partial_municipalities == ()

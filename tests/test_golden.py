"""Golden-set loading, and the provenance rules that keep it auditable."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from fi_rag_eval.golden import GoldenSetError, Phrasing, load_golden_set
from fi_rag_eval.manifest import Manifest, load_manifest

REPO = Path(__file__).resolve().parent.parent
ENTRY = textwrap.dedent(
    """\
    version: 1
    questions:
      - id: q
        question: Mitä biojäte tarkoittaa?
        phrasing: {phrasing}
    {source}
        municipality: Turku
        required_chunks:
          - lounais-suomi@2024-08-01#2.biojatteella
        label_source: 2 § Määritelmät
    """
)


@pytest.fixture(scope="module")
def manifest() -> Manifest:
    return load_manifest(REPO / "corpus" / "manifest.yaml")


def write(tmp_path: Path, phrasing: str, source: str = "") -> Path:
    path = tmp_path / "golden.yaml"
    path.write_text(ENTRY.format(phrasing=phrasing, source=source), encoding="utf-8")
    return path


def test_the_real_golden_set_loads_and_records_its_provenance(manifest: Manifest) -> None:
    golden = load_golden_set(REPO / "corpus" / "golden" / "lounais-suomi.yaml", manifest)
    harvested = golden.count_by_phrasing(Phrasing.HARVESTED)
    assert harvested > 0, "at least some wording must come from outside our own reading"
    assert harvested + golden.count_by_phrasing(Phrasing.AUTHORED) == len(golden)
    for question in golden.questions:
        if question.phrasing is Phrasing.HARVESTED:
            assert question.phrasing_source is not None
            assert question.phrasing_source.startswith("https://")


def test_harvested_wording_must_name_its_source(tmp_path: Path, manifest: Manifest) -> None:
    with pytest.raises(GoldenSetError, match="phrasing_source must name that page"):
        load_golden_set(write(tmp_path, "harvested"), manifest)


def test_authored_wording_must_not_claim_a_source(tmp_path: Path, manifest: Manifest) -> None:
    with pytest.raises(GoldenSetError, match="must be absent"):
        load_golden_set(
            write(tmp_path, "authored", "    phrasing_source: https://example.invalid/"),
            manifest,
        )


def test_an_unknown_phrasing_is_rejected(tmp_path: Path, manifest: Manifest) -> None:
    with pytest.raises(GoldenSetError, match="phrasing must be one of"):
        load_golden_set(write(tmp_path, "guessed"), manifest)


def test_a_label_pointing_outside_the_municipality_authority_is_rejected(
    tmp_path: Path, manifest: Manifest
) -> None:
    path = tmp_path / "golden.yaml"
    path.write_text(
        ENTRY.format(phrasing="authored", source="").replace(
            "lounais-suomi@2024-08-01#2.biojatteella", "savo-pielinen@2024-08-01#2.biojatteella"
        ),
        encoding="utf-8",
    )
    with pytest.raises(GoldenSetError, match="crosses"):
        load_golden_set(path, manifest)


def test_an_empty_required_chunk_list_is_rejected(tmp_path: Path, manifest: Manifest) -> None:
    path = tmp_path / "golden.yaml"
    path.write_text(
        """version: 1
questions:
  - id: q
    question: Miten kompostorin saa toimimaan?
    phrasing: authored
    municipality: Turku
    required_chunks: []
    label_source: not in the regulations at all
""",
        encoding="utf-8",
    )
    with pytest.raises(GoldenSetError, match="non-empty"):
        load_golden_set(path, manifest)

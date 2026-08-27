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
    """The whole directory: a pair spans two files, so one file alone is incomplete."""
    golden = load_golden_set(REPO / "corpus" / "golden", manifest)
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


PAIR_ENTRY = textwrap.dedent(
    """\
    version: 1
    questions:
      - id: {id_a}
        question: {question_a}
        phrasing: authored
        municipality: {municipality_a}
        pair: {pair_a}
        required_chunks:
          - {chunk_a}
        label_source: read by hand
      - id: {id_b}
        question: {question_b}
        phrasing: authored
        municipality: {municipality_b}
        pair: {pair_b}
        required_chunks:
          - {chunk_b}
        label_source: read by hand
    """
)

WELL_FORMED_PAIR = {
    "id_a": "kimppa-ls",
    "question_a": "Voimmeko käyttää naapurin kanssa samaa astiaa?",
    "municipality_a": "Turku",
    "pair_a": "yhteinen-astia",
    "chunk_a": "lounais-suomi@2024-08-01#7",
    "id_b": "kimppa-pir",
    "question_b": "Voimmeko käyttää naapurin kanssa samaa astiaa?",
    "municipality_b": "Tampere",
    "pair_b": "yhteinen-astia",
    "chunk_b": "pirkanmaa@2021-07-01#8",
}


def write_pair(tmp_path: Path, **overrides: str) -> Path:
    path = tmp_path / "pair.yaml"
    path.write_text(PAIR_ENTRY.format(**{**WELL_FORMED_PAIR, **overrides}), encoding="utf-8")
    return path


def test_a_well_formed_pair_loads_and_is_reported(tmp_path: Path, manifest: Manifest) -> None:
    golden = load_golden_set(write_pair(tmp_path), manifest)
    assert {q.pair for q in golden.questions} == {"yhteinen-astia"}
    assert {q.authority for q in golden.questions} == {"lounais-suomi", "pirkanmaa"}


def test_a_lone_half_of_a_pair_is_rejected(tmp_path: Path, manifest: Manifest) -> None:
    """A pair exists to hold the text fixed while the authority changes.

    The second entry asks something else and claims no pair, so only the first
    declares one -- which isolates this rule from the identical-text rule.
    """
    golden = write_pair(
        tmp_path,
        question_b="Kuinka usein astia tyhjennetään?",
        pair_b="~",
    )
    with pytest.raises(GoldenSetError, match="half/halves"):
        load_golden_set(golden, manifest)


def test_halves_that_ask_different_things_are_rejected(tmp_path: Path, manifest: Manifest) -> None:
    golden = write_pair(tmp_path, question_b="Kuinka usein astia tyhjennetään?")
    with pytest.raises(GoldenSetError, match="ask different things"):
        load_golden_set(golden, manifest)


def test_a_single_file_is_incomplete_when_a_pair_spans_two(manifest: Manifest) -> None:
    """Loading one authority's file alone must not silently score half a pair."""
    with pytest.raises(GoldenSetError, match="half/halves"):
        load_golden_set(REPO / "corpus" / "golden" / "pirkanmaa.yaml", manifest)


def test_a_pair_that_does_not_cross_authorities_is_rejected(
    tmp_path: Path, manifest: Manifest
) -> None:
    """Two halves in one jurisdiction cannot show the rules differ."""
    golden = write_pair(
        tmp_path,
        municipality_b="Kaarina",
        chunk_b="lounais-suomi@2024-08-01#9",
    )
    with pytest.raises(GoldenSetError, match=r"labelled against authority"):
        load_golden_set(golden, manifest)


def test_a_directory_of_files_loads_as_one_pooled_set(tmp_path: Path, manifest: Manifest) -> None:
    """One file per authority on disk, one pooled set in the metrics (D11)."""
    (tmp_path / "a-lounais.yaml").write_text(
        ENTRY.format(phrasing="authored", source=""), encoding="utf-8"
    )
    (tmp_path / "b-pirkanmaa.yaml").write_text(
        textwrap.dedent(
            """\
            version: 1
            questions:
              - id: p
                question: Mitä keräysväline tarkoittaa?
                phrasing: authored
                municipality: Tampere
                required_chunks:
                  - pirkanmaa@2021-07-01#2.kerausvalineella
                label_source: 2 § MÄÄRITELMÄT
            """
        ),
        encoding="utf-8",
    )
    golden = load_golden_set(tmp_path, manifest)
    assert [q.id for q in golden.questions] == ["q", "p"], "filename order, so N is stable"
    assert {q.authority for q in golden.questions} == {"lounais-suomi", "pirkanmaa"}


def test_an_id_repeated_across_two_files_is_rejected(tmp_path: Path, manifest: Manifest) -> None:
    """Merging must not hide a collision the single-file check would have caught."""
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(ENTRY.format(phrasing="authored", source=""), encoding="utf-8")
    with pytest.raises(GoldenSetError, match="duplicate question ids"):
        load_golden_set(tmp_path, manifest)


def test_an_empty_golden_directory_is_an_error_not_an_empty_set(
    tmp_path: Path, manifest: Manifest
) -> None:
    with pytest.raises(GoldenSetError, match=r"no \*\.yaml golden-set files"):
        load_golden_set(tmp_path, manifest)

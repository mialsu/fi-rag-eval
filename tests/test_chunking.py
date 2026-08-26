"""Chunking, tested against the hazards the real document actually contains."""

import textwrap

import pytest

from fi_rag_eval.chunking import (
    ChunkingError,
    chunk_clauses,
    parse_toc,
    split_clauses,
)

TOC = textwrap.dedent(
    """\
    Sisällys
    1 LUKU Soveltamisala ja tavoitteet ........................................... 3
       1 § Soveltamisala .......................................................... 3
       2 § Määritelmät............................................................. 4
    2 LUKU Jäteastiat ............................................................ 16
       3 § Asumisessa syntyvien jätteiden lajittelu- ja erilliskeräysvelvoitteet ..... 12
       4 § Jätteen hyödyntäminen omassa maanrakentamisessa ja
       maanparannusaineena ...................................................... 15
    """
)


def test_parse_toc_reads_clauses_chapters_and_wrapped_titles() -> None:
    toc = parse_toc(TOC)
    assert toc.clauses[1] == "Soveltamisala"
    assert toc.clauses[2] == "Määritelmät"
    assert toc.chapters == {1: "Soveltamisala ja tavoitteet", 2: "Jäteastiat"}
    assert toc.clauses[4] == (
        "Jätteen hyödyntäminen omassa maanrakentamisessa ja maanparannusaineena"
    )


def test_parse_toc_rejects_an_inventory_with_holes() -> None:
    with pytest.raises(ChunkingError, match="skips clauses"):
        parse_toc("   1 § Soveltamisala ....... 3\n   3 § Jäteastiat ....... 5\n")


BODY = textwrap.dedent(
    """\
    1 LUKU Soveltamisala ja tavoitteet

    1 § Soveltamisala
    Nämä jätehuoltomääräykset ovat voimassa toimialueella.
    Muilla kiinteistöillä syntyvää jätettä koskevat seuraavat pykälät ja momentit:
    3 § Asumisessa syntyvien jätteiden lajittelu, momentit 1-3
    4 § Jätteen hyödyntäminen
    Näitä jätehuoltomääräyksiä ei sovelleta jätteenkäsittelyyn.


    2 § Määritelmät
    Näissä määräyksissä tarkoitetaan:

    Biojätteellä biologisesti hajoavaa elintarvikejätettä.

    Kunnan järjestämällä jätteenkuljetuksella jätelain 36 §:n mukaista kuljetusta.

    Kunnan jätehuoltojärjestelmällä kunnan järjestämän jätehuollon kokonaisuutta.

    2 LUKU Jäteastiat

    3 § Asumisessa syntyvien jätteiden lajittelu- ja erilliskeräysvelvoitteet
    Kiinteistöille on järjestettävä jäteastiat.

    4 § Jätteen hyödyntäminen omassa maanrakentamisessa ja
    maanparannusaineena
    Mursketta sisältävä rakenne on suojattava.
    """
)


def test_a_cross_reference_list_is_not_mistaken_for_headings() -> None:
    """The hazard ADR-0004 names: 1 § ends with a list of other clauses."""
    clauses = split_clauses(BODY, parse_toc(TOC))
    assert [c.number for c in clauses] == [1, 2, 3, 4]
    assert "3 § Asumisessa syntyvien jätteiden lajittelu, momentit 1-3" in clauses[0].body
    assert "4 § Jätteen hyödyntäminen\n" in clauses[0].body


def test_chapter_headings_are_stripped_and_recorded() -> None:
    clauses = split_clauses(BODY, parse_toc(TOC))
    assert [c.chapter for c in clauses] == [
        "Soveltamisala ja tavoitteet",
        "Soveltamisala ja tavoitteet",
        "Jäteastiat",
        "Jäteastiat",
    ]
    assert "LUKU" not in clauses[1].body


def test_a_wrapped_heading_is_consumed_whole() -> None:
    clauses = split_clauses(BODY, parse_toc(TOC))
    assert clauses[3].title == (
        "Jätteen hyödyntäminen omassa maanrakentamisessa ja maanparannusaineena"
    )
    assert clauses[3].body == "Mursketta sisältävä rakenne on suojattava."


def test_a_body_that_disagrees_with_the_contents_is_a_hard_error() -> None:
    truncated = BODY[: BODY.index("2 LUKU Jäteastiat")]
    with pytest.raises(ChunkingError, match="two halves disagree"):
        split_clauses(truncated, parse_toc(TOC))


def test_a_heading_the_contents_titles_differently_is_a_hard_error() -> None:
    body = BODY.replace("1 § Soveltamisala\n", "1 § Soveltamisalue\n")
    with pytest.raises(ChunkingError, match="does not match the table of contents"):
        split_clauses(body, parse_toc(TOC))


def test_definitions_split_one_chunk_per_term_with_the_preamble_kept() -> None:
    chunks = chunk_clauses(split_clauses(BODY, parse_toc(TOC)))
    definitions = [c for c in chunks if c.clause == 2]
    assert [c.sub_key for c in definitions] == [
        None,
        "biojatteella",
        "kunnan-jarjestamalla",
        "kunnan-jatehuoltojarjestelmalla",
    ]
    assert definitions[0].text.endswith("Näissä määräyksissä tarkoitetaan:")
    assert definitions[1].text.startswith("Biojätteellä biologisesti")
    assert definitions[1].citation == "2 § Määritelmät — Biojätteellä"


def test_a_colliding_first_word_extends_the_sub_key_but_no_further() -> None:
    """Three definitions open with "Kunnan"; only those pay for the collision."""
    chunks = chunk_clauses(split_clauses(BODY, parse_toc(TOC)))
    keys = {c.sub_key for c in chunks if c.clause == 2}
    assert "biojatteella" in keys, "an unambiguous term keeps its one-word key"
    assert "kunnan" not in keys


def test_a_definition_that_lost_its_opening_line_is_a_hard_error() -> None:
    body = BODY.replace(
        "Biojätteellä biologisesti hajoavaa elintarvikejätettä.",
        "biologisesti hajoavaa elintarvikejätettä.",
    )
    with pytest.raises(ChunkingError, match="does not open with a defined term"):
        chunk_clauses(split_clauses(body, parse_toc(TOC)))


def test_whole_clauses_carry_their_heading_into_the_indexed_text() -> None:
    chunks = chunk_clauses(split_clauses(BODY, parse_toc(TOC)))
    third = next(c for c in chunks if c.clause == 3)
    assert third.text.startswith(
        "3 § Asumisessa syntyvien jätteiden lajittelu- ja erilliskeräysvelvoitteet\n"
    )
    assert third.sub_key is None

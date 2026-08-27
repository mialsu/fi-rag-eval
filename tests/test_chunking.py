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


BULLET_BODY = BODY.replace(
    textwrap.dedent(
        """\
        Näissä määräyksissä tarkoitetaan:

        Biojätteellä biologisesti hajoavaa elintarvikejätettä.

        Kunnan järjestämällä jätteenkuljetuksella jätelain 36 §:n mukaista kuljetusta.
        """
    ),
    textwrap.dedent(
        """\
        Näissä määräyksissä tarkoitetaan:

            •   biojätteellä eloperäistä elintarvike- ja puutarhajätettä, joka on
                kokonaisuudessaan biologisesti hajoavaa,
            •   kunnan järjestämällä jätteenkuljetuksella jätelain 36 §:n mukaista
                kuljetusta,
        """
    ),
)
"""Pirkanmaa's shape: `• term ...` items, lower-case definiendum, one paragraph."""


def test_bulleted_definitions_split_one_chunk_per_item() -> None:
    """Pirkanmaa writes 2 § as bullets, not blank-line paragraphs (spec slice 4, D5)."""
    chunks = chunk_clauses(split_clauses(BULLET_BODY, parse_toc(TOC)))
    definitions = [c for c in chunks if c.clause == 2]
    assert [c.sub_key for c in definitions] == [
        None,
        "biojatteella",
        "kunnan-jarjestamalla",
        "kunnan-jatehuoltojarjestelmalla",
    ]
    assert definitions[0].text.endswith("Näissä määräyksissä tarkoitetaan:")
    assert definitions[1].text.startswith("biojätteellä eloperäistä")
    assert definitions[1].citation == "2 § Määritelmät — biojätteellä"


def test_a_bulleted_definiendum_may_be_lower_case() -> None:
    """The bullet is the evidence the item is whole, so the upper-case rule lifts.

    Without this the whole of Pirkanmaa's 2 § is rejected: every one of its 41
    definienda is lower-case.
    """
    chunks = chunk_clauses(split_clauses(BULLET_BODY, parse_toc(TOC)))
    assert any(c.sub_key == "biojatteella" for c in chunks if c.clause == 2)


def test_an_unbulleted_definition_still_has_to_open_with_a_defined_term() -> None:
    """Lifting the rule for bullets must not lift it for the paragraph shape."""
    body = BODY.replace(
        "Biojätteellä biologisesti hajoavaa elintarvikejätettä.",
        "biologisesti hajoavaa elintarvikejätettä.",
    )
    with pytest.raises(ChunkingError, match="does not open with a defined term"):
        chunk_clauses(split_clauses(body, parse_toc(TOC)))


def test_text_before_the_first_bullet_is_a_hard_error_not_a_silent_join() -> None:
    """A definition that lost its bullet would otherwise vanish into the one above."""
    body = BULLET_BODY.replace(
        "    •   biojätteellä eloperäistä",
        "    jatkuu edelliseltä sivulta,\n    •   biojätteellä eloperäistä",
    )
    with pytest.raises(ChunkingError, match="before the first bullet"):
        chunk_clauses(split_clauses(body, parse_toc(TOC)))


def test_a_preamble_holding_bullets_is_a_hard_error() -> None:
    """Bullets in the preamble would silently swallow real definitions."""
    body = BULLET_BODY.replace(
        "Näissä määräyksissä tarkoitetaan:\n\n    •   biojätteellä",
        "Näissä määräyksissä tarkoitetaan:\n    •   biojätteellä",
    )
    with pytest.raises(ChunkingError, match="preamble"):
        chunk_clauses(split_clauses(body, parse_toc(TOC)))


def test_the_paragraph_shape_is_untouched_by_the_bullet_rule() -> None:
    """Prediction 6: Lounais-Suomi's 82/32 counts must not move."""
    plain = chunk_clauses(split_clauses(BODY, parse_toc(TOC)))
    assert [(c.clause, c.sub_key) for c in plain if c.clause == 2] == [
        (2, None),
        (2, "biojatteella"),
        (2, "kunnan-jarjestamalla"),
        (2, "kunnan-jatehuoltojarjestelmalla"),
    ]


def test_a_sub_key_is_unique_on_the_slug_not_on_the_raw_words() -> None:
    """`slugify` casefolds, so two definienda differing only in case still collide.

    Surfaced by Pirkanmaa, whose 41 definienda are lower-case where
    Lounais-Suomi's are capitalised: comparing raw words let `kunnan` and
    `Kunnan` both keep a one-word prefix and then slugify to one address.
    """
    chunks = chunk_clauses(split_clauses(BULLET_BODY, parse_toc(TOC)))
    keys = [c.sub_key for c in chunks if c.clause == 2 and c.sub_key is not None]
    assert len(keys) == len(set(keys))
    assert "kunnan-jarjestamalla" in keys
    assert "kunnan-jatehuoltojarjestelmalla" in keys

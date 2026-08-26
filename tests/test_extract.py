"""Extraction normalisation, tested against real fragments of the source PDF."""

from fi_rag_eval.extract import dehyphenate, split_page_breaks


def test_repairs_a_line_break_hyphen() -> None:
    # Verbatim from 15 §: the word the taajama questions turn on.
    text = "yli 10 000 asukkaan taa-\njamassa sijaitsevat kiinteistöt"
    repaired, joins, guards = dehyphenate(text)
    assert "taajamassa" in repaired
    assert (joins, guards) == (1, 0)


def test_repairs_a_hyphen_across_indented_layout_text() -> None:
    text = "Biojäte, joka kerätään tuulettu-\n    vaan biojäteastiaan"
    repaired, _, _ = dehyphenate(text)
    assert "tuulettuvaan" in repaired


def test_keeps_a_real_hyphen_before_a_conjunction() -> None:
    text = "saostus-\nja umpisäiliölietteiden kuljetus"
    repaired, joins, guards = dehyphenate(text)
    assert "saostus-\nja umpisäiliölietteiden" in repaired
    assert (joins, guards) == (0, 1)


def test_does_not_join_when_the_next_line_starts_a_sentence() -> None:
    text = "kuten 140 - 660 l -\nJäteastiat on tyhjennettävä"
    repaired, joins, _ = dehyphenate(text)
    assert joins == 0
    assert repaired == text


def test_does_not_join_across_a_blank_line() -> None:
    text = "erilliskeräysvelvoite ei koske kiinteistöjä -\n\nkiinteistön haltija"
    _, joins, _ = dehyphenate(text)
    assert joins == 0


def test_page_break_before_a_new_paragraph_becomes_a_paragraph_break() -> None:
    # 2 § Määritelmät: a definition starts on a fresh page, with no blank line.
    text = "koneellisesti jäteautoon\n\fSyväkeräysastialla maahan upotettuja"
    paged, breaks = split_page_breaks(text)
    assert paged == "koneellisesti jäteautoon\n\nSyväkeräysastialla maahan upotettuja"
    assert breaks == 1


def test_page_break_inside_a_paragraph_keeps_the_paragraph_whole() -> None:
    text = "toimitetaan näiden jätehuolto-\n\fkiinteistökohtaisen järjestelmän"
    paged, breaks = split_page_breaks(text)
    assert "\n\n" not in paged
    assert breaks == 1
    repaired, joins, _ = dehyphenate(paged)
    assert "jätehuoltokiinteistökohtaisen" in repaired
    assert joins == 1


def test_page_break_before_a_bullet_becomes_a_paragraph_break() -> None:
    text = "jäteastioina voidaan käyttää\n\f•   kannellisia jätesäiliöitä"
    paged, _ = split_page_breaks(text)
    assert paged.startswith("jäteastioina voidaan käyttää\n\n•")

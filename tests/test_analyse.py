"""The morphological analyser, and the hand-rolled rule at its centre.

Split deliberately in two. The **pure** tests parse recorded `WORDBASES` strings
and need no dictionary, so they run in every `make gate`; they are where the
reassembly rule -- the riskiest component in slice 3 -- is pinned. The **live**
tests need voikko and prove the recorded strings are still what voikko produces,
because a fixture that has drifted from reality tests nothing.
"""

from __future__ import annotations

import pytest

from fi_rag_eval.analyse import (
    LEMMA_ANALYSERS,
    PROBE_WORDS,
    Analyser,
    AnalyserError,
    Morphology,
    Reading,
    Segment,
    SegmentKind,
    normalise,
    parse_wordbases,
    reassembled_parts,
    safe_parts,
    word_lexemes,
)

# (word, WORDBASES, conservative parts, reassembled parts) -- every row copied from
# a live run over this corpus, and re-checked against voikko by the live test below.
FIXTURES: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("biojäteastiaan", "+bio+jäte(jäte)+astia(astia)", (), ("biojäte", "astia")),
    ("kesäaikana", "+kesä(kesä)+aika(aika)", ("kesä", "aika"), ("kesä", "aika")),
    (
        "jätehuoltomääräyksistä",
        "+jäte(jäte)+huolto(huolto)+määrä(määrätä)+ys(+ys)",
        (),
        ("jäte", "huolto", "määräys"),
    ),
    ("määräyksistä", "+määrä(määrätä)+ys(+ys)", (), ("määräys",)),
    ("tyhjennettävä", "+tyhjen(tyhjetä)net(+tää)+täv+ä(+ä)", (), ("tyhjennettävä",)),
    ("asuinkiinteistö", "+asuin+kiinteistö(kiinteistö)", (), ("asuinkiinteistö",)),
    ("ajoneuvojen", "+ajo(ajo)+neuvo(neuvo)", ("ajo", "neuvo"), ("ajo", "neuvo")),
    ("ajoneuvojen", "+ajoneuvo(ajo=neuvo)", ("ajoneuvo",), ("ajoneuvo", "ajo", "neuvo")),
    (
        "vastaanottopaikan",
        "+vastaanot(vastaan=ottaa)+to(+to)+paikka(paikka)",
        (),
        ("vastaanotto", "paikka"),
    ),
    (
        "kuljetusjärjestelyistä",
        "+kuljet(kuljettaa)+us(+us)+järjestel(järjestää)(+lä)+y(+y)",
        (),
        ("kuljetus", "järjestely"),
    ),
    ("lainsäädännön", "+lain(laki)+säädäntö(säädäntö)", ("laki", "säädäntö"), ("laki", "säädäntö")),
    ("taloyhtiössä", "+talo(talo)+yhtiö(yhtiö)", ("talo", "yhtiö"), ("talo", "yhtiö")),
)


@pytest.mark.parametrize(("word", "wordbases", "conservative", "reassembled"), FIXTURES)
def test_the_recorded_decompositions_are_what_the_rules_produce(
    word: str, wordbases: str, conservative: tuple[str, ...], reassembled: tuple[str, ...]
) -> None:
    segments = parse_wordbases(wordbases)
    assert safe_parts(segments) == conservative, word
    assert reassembled_parts(segments) == reassembled, word


def test_a_morph_may_lack_its_leading_plus() -> None:
    """The shape that mangled the first draft of this parser.

    `+` cannot be the delimiter: in `+tyhjen(tyhjetä)net(+tää)+täv+ä(+ä)` the
    `net` morph has no `+` in front of it, and splitting on `+` produced the
    lexeme `'tyhjentää)tävä'` -- a junk entry that would have gone into the index
    silently. The parser reads surfaces and bases positionally instead.
    """
    segments = parse_wordbases("+tyhjen(tyhjetä)net(+tää)+täv+ä(+ä)")
    assert [segment.surface for segment in segments] == ["tyhjen", "net", "täv", "ä"]
    assert [segment.kind for segment in segments] == [
        SegmentKind.WORD,
        SegmentKind.AFFIX,
        SegmentKind.BOUND,
        SegmentKind.AFFIX,
    ]
    assert reassembled_parts(segments) == ("tyhjennettävä",)


def test_two_bases_may_follow_one_surface() -> None:
    """`+järjestel(järjestää)(+lä)` -- nine forms in this corpus do this.

    The second base arrives attached to a zero-length surface, which folds nothing
    onto the part and is therefore harmless rather than corrupting.
    """
    segments = parse_wordbases("+järjestel(järjestää)(+lä)+y(+y)")
    assert [(s.kind, s.surface) for s in segments] == [
        (SegmentKind.WORD, "järjestel"),
        (SegmentKind.AFFIX, ""),
        (SegmentKind.AFFIX, "y"),
    ]
    assert reassembled_parts(segments) == ("järjestely",)


def test_the_derivational_affix_is_folded_back_into_a_word() -> None:
    """The whole reason `reassembled_parts` exists, and the trap it avoids.

    `määräys` means *regulation*; the bare surface morph `määrä` means *quantity*.
    Indexing the morph would make "kuinka suuri määrä" match every regulation
    clause in the corpus -- a precision failure that looks like a recall win.
    """
    parts = reassembled_parts(parse_wordbases("+määrä(määrätä)+ys(+ys)"))
    assert parts == ("määräys",)
    assert "määrä" not in parts
    assert "määrätä" not in parts


def test_a_bound_prefix_never_stands_alone() -> None:
    """`bio` is not a word. It merges forward into the part it belongs to."""
    parts = reassembled_parts(parse_wordbases("+bio+jäte(jäte)+astia(astia)"))
    assert parts == ("biojäte", "astia")
    assert "bio" not in parts


def test_the_conservative_split_refuses_a_derived_compound() -> None:
    """`lemma-safe` invents nothing: every part it emits is a lemma voikko gave it.

    That is exactly why it is predicted to leave the `määräykset` miss red -- the
    `+ys` morph is not a lemma, so the conservative rule declines to split at all.
    """
    assert safe_parts(parse_wordbases("+jäte(jäte)+huolto(huolto)+määrä(määrätä)+ys(+ys)")) == ()
    assert safe_parts(parse_wordbases("+kesä(kesä)+aika(aika)")) == ("kesä", "aika")


def test_the_conservative_split_is_contained_in_the_reassembled_one() -> None:
    """The grid's analysers must nest, or a cell-to-cell delta means nothing.

    `lemma-safe` adds one mechanism to `lemma-baseform` and `lemma-reasm` adds one
    to `lemma-safe`. If a conservative part ever went missing from the reassembled
    set, the two cells would differ in two directions at once and neither delta
    would attribute to anything.
    """
    for word, wordbases, _, _ in FIXTURES:
        segments = parse_wordbases(wordbases)
        assert set(safe_parts(segments)) <= set(reassembled_parts(segments)), word


def test_voikkos_compound_marker_never_reaches_a_lexeme() -> None:
    """`ajo=neuvo` is not a word and would match nothing at all.

    The marker records a boundary the surface form hides, so it is stripped for the
    lemma and used as an extra split point for the parts.
    """
    assert normalise("ajo=neuvo") == "ajoneuvo"
    parts = reassembled_parts(parse_wordbases("+ajoneuvo(ajo=neuvo)"))
    assert parts == ("ajoneuvo", "ajo", "neuvo")
    assert not any("=" in part for part in parts)


def test_an_unbalanced_parenthesis_is_an_error_not_a_partial_split() -> None:
    """A truncated decomposition would put junk lexemes into the index quietly."""
    with pytest.raises(AnalyserError, match="unbalanced parenthesis"):
        parse_wordbases("+jäte(jäte")
    with pytest.raises(AnalyserError, match="no morphs at all"):
        parse_wordbases("")


def test_a_segment_kind_that_cannot_stand_alone_has_no_lemma() -> None:
    affix = Segment(kind=SegmentKind.AFFIX, surface="ys", base="+ys")
    bound = Segment(kind=SegmentKind.BOUND, surface="bio", base=None)
    for segment in (affix, bound):
        with pytest.raises(AnalyserError, match="no lemma of its own"):
            _ = segment.lemma


def test_the_baseform_is_always_emitted_so_a_bad_split_can_only_add_noise() -> None:
    """The nesting property that makes the reassembler safe to try.

    A decomposition that goes wrong adds junk lexemes -- it can never remove the
    reliable signal, because the baseform is emitted first in every lemma mode.
    """
    reading = Reading(baseform="jätehuoltomääräys", wordbases="+jäte(jäte)+huolto(huolto)")
    for analyser in LEMMA_ANALYSERS:
        assert reading.lexemes(analyser)[0] == "jätehuoltomääräys"


def test_a_reading_with_no_wordbases_still_yields_its_baseform() -> None:
    """Six forms in this corpus have no decomposition at all (`Ruokaviraston`)."""
    reading = Reading(baseform="Ruokavirasto", wordbases=None)
    for analyser in LEMMA_ANALYSERS:
        assert reading.lexemes(analyser) == ("ruokavirasto",)


def test_the_snowball_analyser_has_no_python_lexemes() -> None:
    """It is Postgres's, and asking this module for it would be measuring twice."""
    with pytest.raises(AnalyserError, match="not a lemmatising analyser"):
        Reading(baseform="jäte", wordbases=None).lexemes(Analyser.SNOWBALL)


def test_a_capitalised_baseform_is_dropped_for_a_lowercase_word() -> None:
    """A fifth of this corpus's forms are ambiguous, and most of it is name junk.

    `akut` reads as `Aku` (a first name) or `akku` (a battery). Indexing `aku` for
    every occurrence of `akut` is a silent precision loss of exactly the kind the
    double-stemming bug was.
    """
    readings = (Reading("Aku", "+Aku(Aku)"), Reading("akku", "+akku(akku)"))
    assert word_lexemes("akut", readings, Analyser.LEMMA_BASEFORM) == ("akku",)


def test_genuine_ambiguity_keeps_every_reading() -> None:
    """`ajan` is `aika` (time) or `ajaa` (to drive). An index should hold both."""
    readings = (Reading("aika", "+aika(aika)"), Reading("ajaa", "+ajaa(ajaa)"))
    assert word_lexemes("ajan", readings, Analyser.LEMMA_BASEFORM) == ("aika", "ajaa")


def test_a_capitalised_word_keeps_its_capitalised_reading() -> None:
    """Sentence-initial or not, `Aura` really is a municipality in this corpus."""
    readings = (Reading("Aura", "+Aura(Aura)"),)
    assert word_lexemes("Aura", readings, Analyser.LEMMA_BASEFORM) == ("aura",)


def test_the_name_filter_never_empties_a_word_out_of_the_index() -> None:
    """If every reading of a lowercase word is a name, keep them: losing the word
    is worse than indexing a name, because an unindexed word cannot be retrieved
    for at all."""
    readings = (Reading("Aku", "+Aku(Aku)"),)
    assert word_lexemes("aku", readings, Analyser.LEMMA_BASEFORM) == ("aku",)


def test_an_unanalysable_word_falls_back_to_its_raw_token() -> None:
    """`bokashi` is a composting method a resident would genuinely ask about.

    Fifty-five forms here get no analysis. Dropping them would delete them from
    the index entirely; the fallback keeps them findable by their surface form,
    which is the honest limit of it -- `bokashilla` will not match `bokashi`.
    """
    assert word_lexemes("Bokashilla", (), Analyser.LEMMA_REASM) == ("bokashilla",)
    assert word_lexemes("840-1", (), Analyser.LEMMA_BASEFORM) == ("840-1",)


def test_the_probe_list_is_a_set_of_distinct_words() -> None:
    """The fingerprint is order-dependent, so a duplicate would be dead weight."""
    assert len(set(PROBE_WORDS)) == len(PROBE_WORDS)


# --- live: everything below needs the dictionary on the host -----------------


@pytest.mark.requires_voikko
@pytest.mark.parametrize(("word", "wordbases", "conservative", "reassembled"), FIXTURES)
def test_the_recorded_fixtures_are_still_what_voikko_produces(
    morphology: Morphology,
    word: str,
    wordbases: str,
    conservative: tuple[str, ...],
    reassembled: tuple[str, ...],
) -> None:
    """The other half of the pure tests above: fixtures that have drifted from
    reality test nothing at all. This is also the human-readable half of the
    fingerprint gate -- if voikko-fi changes a decomposition, this fails and says
    which word."""
    del conservative, reassembled
    assert wordbases in {r.wordbases for r in morphology.readings(word)}


@pytest.mark.requires_voikko
def test_the_resident_word_and_the_document_word_meet_at_the_conservative_split(
    morphology: Morphology,
) -> None:
    """`kesällä` vs `kesäaikana` -- the miss `lemma-safe` is predicted to fix."""
    resident = set(morphology.lexemes("kesällä", Analyser.LEMMA_SAFE))
    document = set(morphology.lexemes("kesäaikana", Analyser.LEMMA_SAFE))
    assert resident & document == {"kesä"}
    assert not set(morphology.lexemes("kesällä", Analyser.LEMMA_BASEFORM)) & set(
        morphology.lexemes("kesäaikana", Analyser.LEMMA_BASEFORM)
    ), "baseform alone must not reach it, or the safe cell's delta means nothing"


@pytest.mark.requires_voikko
def test_the_regulation_word_needs_the_reassembler(morphology: Morphology) -> None:
    """`määräyksistä` vs `jätehuoltomääräyksistä` -- the miss only `reasm` reaches.

    This is the measurement that decides whether the reassembler earns its place
    rather than being deleted, so it is pinned in both directions.
    """
    for analyser in (Analyser.LEMMA_BASEFORM, Analyser.LEMMA_SAFE):
        assert not set(morphology.lexemes("määräyksistä", analyser)) & set(
            morphology.lexemes("jätehuoltomääräyksistä", analyser)
        ), analyser
    shared = set(morphology.lexemes("määräyksistä", Analyser.LEMMA_REASM)) & set(
        morphology.lexemes("jätehuoltomääräyksistä", Analyser.LEMMA_REASM)
    )
    assert shared == {"määräys"}


@pytest.mark.requires_voikko
def test_voikkos_tokeniser_keeps_a_url_and_a_hyphenated_number_whole(
    morphology: Morphology,
) -> None:
    """Documented because Postgres's parser splits both, and the difference is
    visible in the corpus (`840-1`, the manifest's source URLs)."""
    words = morphology.words("Ks. https://lsjh.fi/ohje 840-1 esim. biojäteastiaan; 3 §.")
    assert words == ("Ks", "https://lsjh.fi/ohje", "840-1", "esim", "biojäteastiaan", "3")


@pytest.mark.requires_voikko
def test_positions_are_kept_so_ts_rank_still_sees_term_frequency(
    morphology: Morphology,
) -> None:
    """Dropping positions would flatten a repeated term to one occurrence and
    change the ranking under measurement without changing any lexeme."""
    entries = dict(
        morphology.positioned(
            "Biojäteastia tyhjennetään. Biojäteastia pestään.",
            Analyser.LEMMA_BASEFORM,
            stopwords=frozenset(),
        )
    )
    assert entries["biojäteastia"] == (1, 3)
    assert entries["tyhjentää"] == (2,)


@pytest.mark.requires_voikko
def test_a_stopped_word_takes_no_position(morphology: Morphology) -> None:
    """Stopping must not leave a positional hole, or two analysers would disagree
    about term positions for reasons that have nothing to do with morphology."""
    entries = dict(
        morphology.positioned(
            "Mitä biojätteellä tarkoitetaan",
            Analyser.LEMMA_BASEFORM,
            stopwords=frozenset({"mitä"}),
        )
    )
    assert entries["biojäte"] == (1,)
    assert "mitä" not in entries


@pytest.mark.requires_voikko
def test_the_fingerprint_is_stable_and_notices_a_changed_lemma(
    morphology: Morphology,
) -> None:
    """D8's gate. `libvoikko` reports the library version but not the dictionary
    version, so hashing the analyser's own output is the only signal that
    `voikko-fi` moved -- and a dictionary upgrade would move every published
    number with no code change."""
    recorded = morphology.fingerprint()
    assert recorded == morphology.fingerprint(), "the fingerprint must be deterministic"

    original = morphology.lexemes

    def perturbed(word: str, analyser: Analyser) -> tuple[str, ...]:
        """One probe word's lemma changed -- what a voikko-fi upgrade looks like."""
        lexemes = original(word, analyser)
        return ("kesa", *lexemes[1:]) if word == "kesällä" else lexemes

    morphology.lexemes = perturbed  # type: ignore[method-assign]
    try:
        assert morphology.fingerprint() != recorded
    finally:
        del morphology.lexemes
    assert morphology.fingerprint() == recorded, "the perturbation must be undone"


class _SilentVoikko:
    """A voikko that loaded but has no dictionary: it analyses nothing.

    The failure mode that motivated `assert_dictionary_present`, and the one that
    cannot be reproduced by hiding the dictionary from a live install --
    `VOIKKO_DICTIONARY_PATH` adds a search path rather than replacing the system
    one, so a real dictionary is still found. Hence a stub.
    """

    def analyze(self, word: str) -> list[dict[str, str]]:
        del word
        return []

    def tokens(self, text: str) -> list[object]:
        del text
        return []


def test_an_analyser_with_no_dictionary_fails_instead_of_degrading() -> None:
    """The requirement in full: a helpful message, and never a silent fallback.

    Without this guard every word would take the raw-token path, the lemma cells
    would collapse to something worse than snowball, and the harness would publish
    it as lemmatisation.
    """
    silent = Morphology(_SilentVoikko(), "4.3.2")
    with pytest.raises(AnalyserError) as raised:
        silent.assert_dictionary_present()
    message = str(raised.value)
    assert "analyses nothing" in message
    assert "apt-get install libvoikko1 voikko-fi" in message
    assert "uv sync" in message, "the message must say why pip cannot fix it"


def test_the_raw_token_fallback_is_reachable_only_per_word() -> None:
    """The fallback exists for the 2.2% of forms voikko cannot analyse, and it must
    not become a whole-corpus fallback: that is what the guard above prevents."""
    silent = Morphology(_SilentVoikko(), "4.3.2")
    assert silent.lexemes("biojäteastiaan", Analyser.LEMMA_REASM) == ("biojäteastiaan",)

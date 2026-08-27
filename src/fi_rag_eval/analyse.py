"""Finnish morphology: lemmas and compound parts, computed in Python.

Slice 3 adds a **lemmatising analyser alongside** the snowball one, because slice
2 measured 4 of 6 misses as zero-overlap -- the query and the index disagreeing
about a word both of them contain. That is a morphology failure, and no amount of
ranking repairs it.

**Why this is Python and not a Postgres text-search dictionary.** The plan of
record said `dict_voikko`. It does not exist: `postgres:17-alpine` ships
`dict_snowball`, `dict_int` and `dict_xsyn`, `pg_ts_template` offers only
ispell/simple/snowball/synonym/thesaurus, and neither libvoikko nor a Finnish
hunspell dictionary is in the Alpine repositories. See ADR-0005.

**What voikko gives us**, per word:

* `BASEFORM` -- the lemma. Fixes the stemmer-disagrees-with-itself case
  (`biojäteastia` stems to `biojäteast`, `biojäteastiaan` to `biojäteastia`).
* `WORDBASES` -- a morph decomposition. Needed for the compound cases, because a
  resident writes `kesällä` where the document writes `kesäaikana`.

`WORDBASES` yields **morphs, not words**, and that distinction is the whole of
`reassembled_parts` below: `+määrä(määrätä)+ys(+ys)` must come back as `määräys`
(*regulation*), never as the surface morph `määrä` (*quantity*), or a question
about how large a quantity is would match every regulation clause in the corpus.
"""

from __future__ import annotations

import hashlib
from collections.abc import Container, Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

TSVECTOR_MAX_POSITION: Final = 16383
"""Postgres drops positions above this. Chunks here are far shorter; asserted anyway."""


class AnalyserError(RuntimeError):
    """The morphological analyser is unavailable, or produced something unusable.

    Never recovered from by falling back to raw tokens: an analyser that silently
    degrades would publish a number under a label it no longer earns.
    """


class Analyser(StrEnum):
    """The analysers under measurement. One dimension of slice 3's grid.

    The three lemma analysers **nest**: each adds exactly one mechanism to the
    one above it, so a delta between adjacent rows attributes to that mechanism
    and nothing else.
    """

    SNOWBALL = "snowball"
    """Postgres `to_tsvector('finnish', ...)`. The control, and the published cell."""

    LEMMA_BASEFORM = "lemma-baseform"
    """voikko `BASEFORM` only. No compound decomposition."""

    LEMMA_SAFE = "lemma-safe"
    """BASEFORM + a compound split taken only where every morph carries a real base."""

    LEMMA_REASM = "lemma-reasm"
    """BASEFORM + a split that folds derivational affixes back into words."""

    @property
    def column(self) -> str:
        """The `tsvector` column this analyser reads. A distinct index per cell."""
        return {
            Analyser.SNOWBALL: "tsv",
            Analyser.LEMMA_BASEFORM: "lemma_base_tsv",
            Analyser.LEMMA_SAFE: "lemma_safe_tsv",
            Analyser.LEMMA_REASM: "lemma_reasm_tsv",
        }[self]

    @property
    def lemmatising(self) -> bool:
        return self is not Analyser.SNOWBALL


LEMMA_ANALYSERS: Final = tuple(a for a in Analyser if a.lemmatising)


class SegmentKind(StrEnum):
    """What one `WORDBASES` morph is, which decides whether it can stand alone."""

    WORD = "word"
    """Carries a real base: `+jäte(jäte)`. A word part, and a lemma of its own."""

    AFFIX = "affix"
    """Its base starts with `+`: `+ys(+ys)`. Derivational or inflectional."""

    BOUND = "bound"
    """No base at all: `+bio`, `+asuin`. Cannot stand alone as a word."""


@dataclass(frozen=True, slots=True)
class Segment:
    kind: SegmentKind
    surface: str
    base: str | None

    @property
    def lemma(self) -> str:
        """This morph's own lemma. Only meaningful for a `WORD` segment."""
        if self.kind is not SegmentKind.WORD or self.base is None:
            raise AnalyserError(f"{self!r} has no lemma of its own")
        return normalise(self.base)


def normalise(lexeme: str) -> str:
    """Casefold, and drop voikko's internal compound marker.

    A `WORDBASES` base may carry `=` where voikko knows a boundary the surface
    form hides: `+ajoneuvo(ajo=neuvo)`, `+vastaanotto(vastaan=otto)`. Nine forms
    in this corpus do. `ajo=neuvo` is not a word and would never match anything,
    so leaving the marker in place would silently drop those words from the index.
    """
    return lexeme.replace("=", "").lower()


def parse_wordbases(wordbases: str) -> tuple[Segment, ...]:
    """Parse a `WORDBASES` string into its morphs, left to right.

    The grammar is looser than it looks and every irregularity below was found in
    this corpus, not imagined:

    * `+jäte(jäte)+huolto(huolto)` -- the regular case.
    * `+bio+jäte(jäte)+astia(astia)` -- a morph may carry no base.
    * `+tyhjen(tyhjetä)net(+tää)+täv+ä(+ä)` -- a morph may lack its leading `+`,
      so `+` cannot be used as the delimiter. This is the shape that mangled the
      first draft of this parser into `'tyhjentää)tävä'`.
    * `+järjestel(järjestää)(+lä)` -- two bases may follow one surface. The second
      arrives as a zero-length surface, which folds nothing and is harmless.

    Raises `AnalyserError` on a shape this parser does not model, rather than
    returning a partial decomposition: a silently truncated split produces junk
    lexemes, and junk lexemes lower precision on *other* questions.
    """
    segments: list[Segment] = []
    index, end = 0, len(wordbases)
    while index < end:
        if wordbases[index] == "+":
            index += 1
            continue
        start = index
        while index < end and wordbases[index] not in "+(":
            index += 1
        surface = wordbases[start:index]
        base: str | None = None
        if index < end and wordbases[index] == "(":
            close = wordbases.find(")", index)
            if close == -1:
                raise AnalyserError(
                    f"unbalanced parenthesis in WORDBASES {wordbases!r}; refusing to "
                    "guess at a decomposition that would become index entries"
                )
            base = wordbases[index + 1 : close]
            index = close + 1
        if not surface and base is None:
            raise AnalyserError(f"empty morph in WORDBASES {wordbases!r}")
        if base is None:
            kind = SegmentKind.BOUND
        elif base.startswith("+"):
            kind = SegmentKind.AFFIX
        else:
            kind = SegmentKind.WORD
        segments.append(Segment(kind=kind, surface=surface, base=base))
    if not segments:
        raise AnalyserError(f"WORDBASES {wordbases!r} decomposes to no morphs at all")
    return tuple(segments)


def safe_parts(segments: Iterable[Segment]) -> tuple[str, ...]:
    """Compound parts, taken **only** where every morph carries a real base.

    The conservative rule: it invents nothing, because each part it emits is a
    lemma voikko itself supplied. `+kesä(kesä)+aika(aika)` splits; the derived
    `+määrä(määrätä)+ys(+ys)` does not, which is why `lemma-safe` is predicted to
    leave `#48` red.
    """
    listed = list(segments)
    if not listed or any(segment.kind is not SegmentKind.WORD for segment in listed):
        return ()
    return tuple(segment.lemma for segment in listed)


def reassembled_parts(segments: Iterable[Segment]) -> tuple[str, ...]:
    """Compound parts, with derivational affixes folded back into whole words.

    A hand-rolled morphological rule, and the riskiest component in this slice --
    its bugs are silent, because a junk lexeme lowers precision on questions other
    than the one it was built for. The rule:

    * a `WORD` morph starts a new part;
    * an `AFFIX` morph folds onto the part in progress -- this is what turns
      `+määrä(määrätä)+ys(+ys)` into `määräys`;
    * a `BOUND` morph folds onto the part in progress if there is one, and is
      otherwise held to merge forward into the next -- `+bio+jäte(jäte)` yields
      `biojäte`, never a bare `bio`;
    * a part of exactly one `WORD` morph renders as its **base** (a lemma), and
      any longer part renders as its morphs' **surfaces** concatenated.

    A base carrying voikko's `=` marker contributes its own boundary too, so
    `+ajoneuvo(ajo=neuvo)` yields `ajoneuvo`, `ajo` and `neuvo`.
    """
    parts: list[list[Segment]] = []
    held: list[Segment] = []
    for segment in segments:
        if segment.kind is SegmentKind.WORD:
            parts.append([*held, segment])
            held = []
        elif parts:
            parts[-1].append(segment)
        else:
            held.append(segment)
    if held:
        if parts:
            parts[-1].extend(held)
        else:
            parts.append(held)

    rendered: list[str] = []
    for part in parts:
        if len(part) == 1 and part[0].kind is SegmentKind.WORD:
            base = part[0].base or ""
            rendered.append(normalise(base))
            rendered.extend(normalise(piece) for piece in base.split("=") if piece)
        else:
            rendered.append(normalise("".join(segment.surface for segment in part)))
    return tuple(_unique(rendered))


@dataclass(frozen=True, slots=True)
class Reading:
    """One of voikko's analyses of one word. A word often has several."""

    baseform: str
    wordbases: str | None
    """Absent for six forms in this corpus (`Ruokaviraston`), so never assumed present."""

    def lexemes(self, analyser: Analyser) -> tuple[str, ...]:
        """The lexemes this reading contributes under `analyser`.

        The lemma analysers nest: `safe` is `baseform` plus its parts, `reasm` is
        `safe`'s superset. The baseform is always emitted, so a decomposition that
        goes wrong can only add noise -- it can never remove the reliable signal.
        """
        if not analyser.lemmatising:
            raise AnalyserError(f"{analyser} is not a lemmatising analyser")
        lexemes = [normalise(self.baseform)]
        if analyser is not Analyser.LEMMA_BASEFORM and self.wordbases is not None:
            segments = parse_wordbases(self.wordbases)
            parts = (
                safe_parts(segments)
                if analyser is Analyser.LEMMA_SAFE
                else reassembled_parts(segments)
            )
            lexemes.extend(parts)
        return tuple(_unique(lexemes))


def word_lexemes(word: str, readings: Iterable[Reading], analyser: Analyser) -> tuple[str, ...]:
    """Every lexeme one surface word contributes, across all of its readings.

    Two rules from the spec live here.

    **All readings, minus proper-noun readings of a lowercase word** (D9). A fifth
    of this corpus's word forms have more than one analysis, and most of that
    ambiguity is proper-noun junk: `akut` reads as `Aku` or `akku`, `aina` as
    `Aina` or `aina`. Dropping a capitalised baseform when the surface word was
    lowercase removes that class on a rule, while genuine ambiguity (`ajan` ->
    `aika` or `ajaa`) keeps both readings -- which is what a retrieval index
    should do. Taking only the first reading was rejected: voikko's ordering is
    not documented as ranked, and `omakotikiinteistöillä` is analysed
    *incorrectly* first (`omakotikiinteistyö`) and correctly second.

    **An unanalysable word falls back to its raw token** (D10). Fifty-five forms
    here get no analysis at all -- `bokashilla`, `fermentoidaan`, `esim`, `840-1`,
    URLs -- and `bokashi` is a composting method a resident would genuinely ask
    about. Dropping them would delete them from the index entirely.
    """
    listed = list(readings)
    if not listed:
        return (normalise(word),)
    kept = listed
    if word[:1].islower():
        filtered = [r for r in listed if not r.baseform[:1].isupper()]
        # A filter must never empty the index of a word. If every reading of a
        # lowercase word is a proper noun, keep them all rather than lose it.
        kept = filtered or listed
    lexemes: list[str] = []
    for reading in kept:
        lexemes.extend(reading.lexemes(analyser))
    return tuple(_unique(lexemes))


def _unique(values: Iterable[str]) -> Iterator[str]:
    """Order-preserving dedup, with empties dropped. Order is the analyser's."""
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            yield value


PROBE_WORDS: Final = (
    # One word per behaviour this slice depends on. Committed, so the fingerprint
    # below is reproducible; ordered, so the hash is stable.
    "biojäteastiaan",
    "biojäteastia",
    "kesällä",
    "kesäaikana",
    "määräyksistä",
    "jätehuoltomääräyksistä",
    "tyhjennetään",
    "tyhjennettävä",
    "asuinkiinteistö",
    "hyötyjätepiste",
    "taloyhtiössä",
    "asuntoa",
    "keskustassa",
    "kiinteistön",
    "huoneistoa",
    "taajamassa",
    "ajoneuvojen",
    "vastaanottopaikan",
    "omakotikiinteistöillä",
    "kuljetusjärjestelyistä",
    "erilliskeräämisestä",
    "lainsäädännön",
    "akut",
    "aina",
    "ajan",
    "bokashilla",
    "esim",
    "840-1",
)
"""The words whose analysis is hashed into `baseline.json`. See `fingerprint`."""


class Morphology:
    """voikko, wrapped so that every failure is an `AnalyserError` with a fix in it.

    `libvoikko` exposes the *library* version but **not the dictionary version**,
    and it is the dictionary that decides the numbers. A `voikko-fi` upgrade would
    therefore move every published metric with no code change -- the one thing
    this project must never allow. `fingerprint` closes that hole the same way the
    corpus `sha256` closes it for the PDF: by hashing the behaviour, not the
    version, because it is the behaviour the numbers depend on.
    """

    _INSTALL_HINT = (
        "Install the Finnish morphological analyser and its dictionary:\n"
        "  Debian/Ubuntu:  sudo apt-get install libvoikko1 voikko-fi\n"
        "  Fedora:         sudo dnf install libvoikko voikko-fi\n"
        "The dictionary is a system package, not a Python one, so `uv sync` "
        "cannot supply it. Slice 3's lemma cells cannot be measured without it, "
        "and the harness will not fall back to raw tokens: a number computed by a "
        "silently degraded analyser is worse than no number."
    )

    def __init__(self, voikko: Any, library_version: str) -> None:
        self._voikko = voikko
        self.library_version = library_version
        self._cache: dict[str, tuple[Reading, ...]] = {}

    @classmethod
    def open(cls) -> Morphology:
        try:
            import libvoikko
        except ImportError as exc:  # pragma: no cover - libvoikko is a hard dependency
            raise AnalyserError(f"cannot import libvoikko: {exc}\n{cls._INSTALL_HINT}") from exc
        try:
            voikko = libvoikko.Voikko("fi")
            version = str(libvoikko.Voikko.getVersion())
        except (libvoikko.VoikkoException, OSError) as exc:
            raise AnalyserError(
                f"cannot open the Finnish analyser: {exc}\n{cls._INSTALL_HINT}"
            ) from exc
        instance = cls(voikko, version)
        instance.assert_dictionary_present()
        return instance

    def assert_dictionary_present(self) -> None:
        """Prove the dictionary is really there, not merely that voikko loaded.

        A voikko without a Finnish dictionary opens happily and then analyses
        nothing. Every word would fall through to the raw-token fallback, every
        lemma cell would collapse to a worse-than-snowball index, and the harness
        would publish that under the label "lemmatisation" -- a number computed by
        a silently degraded analyser, which is the failure mode this project exists
        to make impossible.
        """
        if not self.readings("biojäteastiaan"):
            raise AnalyserError(
                "the Finnish analyser opened but analyses nothing, so its dictionary "
                f"is missing or unreadable.\n{self._INSTALL_HINT}"
            )

    def words(self, text: str) -> tuple[str, ...]:
        """Word tokens, in order, using voikko's own tokeniser.

        It keeps a URL and `840-1` whole, which Postgres's parser splits. Both
        behaviours are defensible; using voikko's keeps tokenisation and analysis
        in one component instead of straddling two.
        """
        return tuple(
            token.tokenText for token in self._voikko.tokens(text) if token.tokenTypeName == "WORD"
        )

    def readings(self, word: str) -> tuple[Reading, ...]:
        """Every analysis of one word. Cached: the corpus repeats itself heavily."""
        cached = self._cache.get(word)
        if cached is not None:
            return cached
        readings = tuple(
            Reading(
                baseform=str(analysis["BASEFORM"]),
                wordbases=str(analysis["WORDBASES"]) if "WORDBASES" in analysis else None,
            )
            for analysis in self._voikko.analyze(word)
            if "BASEFORM" in analysis
        )
        self._cache[word] = readings
        return readings

    def lexemes(self, word: str, analyser: Analyser) -> tuple[str, ...]:
        return word_lexemes(word, self.readings(word), analyser)

    def positioned(
        self, text: str, analyser: Analyser, *, stopwords: Container[str]
    ) -> tuple[tuple[str, tuple[int, ...]], ...]:
        """Lexemes with their 1-based token positions, ready for a `tsvector`.

        Positions are what give `ts_rank` its term frequencies, so they are not
        cosmetic: dropping them would flatten every repeated term to one
        occurrence and change the ranking this slice is measuring.

        **Stopping is deliberately borrowed from snowball** rather than reinvented.
        `stopwords` is the set of surface tokens Postgres's `finnish`
        configuration discards, obtained from Postgres itself
        (`db.snowball_stopwords`). Without it the lemma cells would index and
        query `olla`, `ja` and `mitä` while the control cell does not, and the
        grid would be comparing lemmatisation-plus-no-stopping against
        snowball-plus-stopping -- two variables, one number.
        """
        positions: dict[str, list[int]] = {}
        position = 0
        for word in self.words(text):
            if word.lower() in stopwords:
                continue
            position += 1
            if position > TSVECTOR_MAX_POSITION:
                raise AnalyserError(
                    f"text has more than {TSVECTOR_MAX_POSITION} indexable tokens; "
                    "Postgres would silently drop the positions past that, changing "
                    "the term frequencies ts_rank is computed from"
                )
            for lexeme in self.lexemes(word, analyser):
                slot = positions.setdefault(lexeme, [])
                if not slot or slot[-1] != position:
                    slot.append(position)
        return tuple((lexeme, tuple(positions[lexeme])) for lexeme in sorted(positions))

    def query_lexemes(
        self, text: str, analyser: Analyser, *, stopwords: Container[str]
    ) -> list[str]:
        """The question's lexemes, sorted, as the query side sees them.

        Sorted rather than in text order so that the query -- and therefore the
        recorded baseline -- does not depend on word order in a way no reader
        would expect.
        """
        return [lexeme for lexeme, _ in self.positioned(text, analyser, stopwords=stopwords)]

    def fingerprint(self) -> str:
        """A hash of what this analyser *does*, over `PROBE_WORDS`.

        Hashes the output, not the version, deliberately: a library upgrade that
        changes nothing must not fail the gate, and a dictionary upgrade that
        changes one lemma must.
        """
        digest = hashlib.sha256()
        for word in PROBE_WORDS:
            for analyser in LEMMA_ANALYSERS:
                digest.update(f"{word}\t{analyser}\t".encode())
                digest.update("\x1f".join(self.lexemes(word, analyser)).encode())
                digest.update(b"\x1e")
        return digest.hexdigest()[:16]

    def probe_table(self) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
        """`PROBE_WORDS` with their baseform and reassembled lexemes, for the eye.

        The fingerprint says *whether* the analyser changed; this says *how*.
        """
        return tuple(
            (
                word,
                self.lexemes(word, Analyser.LEMMA_BASEFORM),
                self.lexemes(word, Analyser.LEMMA_REASM),
            )
            for word in PROBE_WORDS
        )

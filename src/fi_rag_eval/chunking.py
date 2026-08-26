"""Clause-level chunking, per ADR-0004.

A chunk is one clause (§), whole, with two carve-outs:

1. ``2 § Määritelmät`` splits into one chunk per defined term -- answering "what
   counts as biojäte" by retrieving all ~30 definitions is dilution, not
   precision.
2. Cross-reference lists and tables stay atomic. In this document that hazard is
   concrete: **1 § Soveltamisala** ends with a 21-line list of the clauses that
   bind non-residential properties, every line of which begins ``<n> §``. A
   splitter keying on ``^\\d+ §`` reads those as twenty-one empty clauses.
   (ADR-0004 attributes that list to 3 §; it is in fact 1 §. The hazard is real,
   the clause number in the ADR is wrong -- corrected there.)

The defence against carve-out 2 is not a special case but an invariant: a
heading candidate is a heading only if its number is the one the document is
due next, and the resulting inventory must match the document's own table of
contents exactly. A cross-reference to 17 § while we are waiting for 2 § is not
a heading, and cannot be mistaken for one.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fi_rag_eval.addressing import slugify

_CLAUSE = re.compile(r"^(?P<number>\d+)\s*§\s+(?P<title>\S.*?)\s*$")
_CHAPTER = re.compile(r"^(?P<number>\d+)\s*LUKU\s+(?P<title>\S.*?)\s*$")
_TOC_TAIL = re.compile(r"\s*\.{4,}\s*\d+\s*$")
_DOT_LEADER = re.compile(r"\.{4,}")
_HEADING_WRAP_LIMIT = 3

DEFINITIONS_CLAUSE = 2
"""The clause the first carve-out applies to."""


class ChunkingError(RuntimeError):
    """The document did not chunk the way the decisions say it must."""


@dataclass(frozen=True, slots=True)
class TableOfContents:
    """The document's own inventory: the ground truth the body is checked against."""

    clauses: Mapping[int, str]
    chapters: Mapping[int, str]


@dataclass(frozen=True, slots=True)
class Clause:
    number: int
    title: str
    chapter: str | None
    body: str


@dataclass(frozen=True, slots=True)
class Chunk:
    """One retrievable, citable unit."""

    clause: int
    sub_key: str | None
    citation: str
    """Human-facing: ``26 § Jäteastioiden tyhjennysvälit``."""
    text: str
    """The document's own text for this unit. This is what gets indexed."""


def _normalise_title(title: str) -> str:
    """Fold a title for comparison: whitespace and hyphens carry no meaning here.

    A wrapped heading may or may not have been rejoined across a line-break
    hyphen, so both sides are compared with hyphens and spaces removed.
    """
    return re.sub(r"[\s\-\u2010-\u2015]+", "", title).casefold()


def parse_toc(toc: str) -> TableOfContents:
    """Read the clause and chapter inventory out of the table of contents.

    Entries wrap: a long title occupies a line with no dot leader, and the dot
    leader plus page number arrive on the next line. Only the dot leader marks
    the end of an entry.
    """
    clauses: dict[int, str] = {}
    chapters: dict[int, str] = {}
    pending = ""

    for line in toc.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if _DOT_LEADER.search(stripped):
            entry = f"{pending} {_TOC_TAIL.sub('', stripped)}".strip()
            pending = ""
            clause = _CLAUSE.match(entry)
            if clause is not None:
                number = int(clause["number"])
                if number in clauses:
                    raise ChunkingError(f"table of contents lists {number} § twice")
                clauses[number] = clause["title"]
                continue
            chapter = _CHAPTER.match(entry)
            if chapter is not None:
                chapters[int(chapter["number"])] = chapter["title"]
            continue
        if _CLAUSE.match(stripped) or _CHAPTER.match(stripped):
            pending = stripped
        elif pending:
            pending = f"{pending} {stripped}"

    if not clauses:
        raise ChunkingError("table of contents lists no clauses")
    expected = list(range(1, max(clauses) + 1))
    missing = [n for n in expected if n not in clauses]
    if missing:
        raise ChunkingError(
            f"table of contents skips clauses {missing}; refusing to chunk against "
            "an inventory with holes in it"
        )
    return TableOfContents(clauses=clauses, chapters=chapters)


def _consume_heading(
    lines: Sequence[str], start: int, expected_title: str, pattern: re.Pattern[str]
) -> int:
    """Return how many lines the heading at ``start`` occupies.

    A heading wraps when the title is long. The document's own table of contents
    says what the whole title is, so the body heading is accumulated until the
    two agree -- which both handles the wrap and cross-checks the two halves of
    the document against each other.
    """
    match = pattern.match(lines[start])
    if match is None:  # pragma: no cover - callers only pass matching lines
        raise ChunkingError(f"line {start} is not a heading: {lines[start]!r}")
    accumulated = match["title"]
    for extra in range(_HEADING_WRAP_LIMIT + 1):
        if _normalise_title(accumulated) == _normalise_title(expected_title):
            return extra + 1
        following = start + extra + 1
        if following >= len(lines) or not lines[following].strip():
            break
        accumulated = f"{accumulated} {lines[following].strip()}"
    raise ChunkingError(
        f"heading at body line {start + 1} does not match the table of contents.\n"
        f"  contents: {expected_title!r}\n"
        f"  body:     {accumulated!r}\n"
        "Refusing to chunk: a heading the two halves of the document disagree about "
        "means the extractor or the layout changed, and every golden label is at risk."
    )


def split_clauses(body: str, toc: TableOfContents) -> list[Clause]:
    """Split the body into clauses, using the contents as the ground truth."""
    lines = body.split("\n")
    marks: list[tuple[str, int, int, int]] = []  # kind, number, start, span
    next_clause, next_chapter = 1, 1
    index = 0

    while index < len(lines):
        line = lines[index]
        chapter = _CHAPTER.match(line)
        if (
            chapter is not None
            and int(chapter["number"]) == next_chapter
            and next_chapter in toc.chapters
        ):
            span = _consume_heading(lines, index, toc.chapters[next_chapter], _CHAPTER)
            marks.append(("chapter", next_chapter, index, span))
            next_chapter += 1
            index += span
            continue
        clause = _CLAUSE.match(line)
        if (
            clause is not None
            and int(clause["number"]) == next_clause
            and next_clause in toc.clauses
        ):
            span = _consume_heading(lines, index, toc.clauses[next_clause], _CLAUSE)
            marks.append(("clause", next_clause, index, span))
            next_clause += 1
            index += span
            continue
        index += 1

    found = [number for kind, number, _, _ in marks if kind == "clause"]
    expected = sorted(toc.clauses)
    if found != expected:
        raise ChunkingError(
            f"body carries clauses {found} but the table of contents lists {expected}. "
            "Refusing to chunk a document whose two halves disagree."
        )

    clauses: list[Clause] = []
    chapter_title: str | None = None
    for position, (kind, number, start, span) in enumerate(marks):
        if kind == "chapter":
            chapter_title = toc.chapters[number]
            continue
        end = marks[position + 1][2] if position + 1 < len(marks) else len(lines)
        clauses.append(
            Clause(
                number=number,
                title=toc.clauses[number],
                chapter=chapter_title,
                body="\n".join(lines[start + span : end]).strip("\n"),
            )
        )
    return clauses


_SUB_KEY_WORD_LIMIT = 5


def _leading_words(paragraph: str, count: int) -> list[str]:
    return [word.strip(",.;:") for word in paragraph.split(maxsplit=count)[:count]]


def _definition_sub_keys(paragraphs: Sequence[str]) -> list[tuple[str, str]]:
    """Give each definition the shortest leading-word prefix that is unique.

    The definiendum in the source is a **bolded phrase** -- "Saostus- ja
    umpisäiliölietteellä", not one word -- and ``pdftotext`` cannot see bold, so
    the phrase boundary is not recoverable from the text alone. The sub-key is
    therefore a prefix of the paragraph rather than the term itself: one word
    where that is unambiguous, extended word by word only where it collides
    (three definitions here open with "Kunnan").

    The prefix depends only on the paragraph's own opening words, so it survives
    re-extraction and re-chunking, which is what ADR-0004 asks of an address.
    """
    prefixes = [_leading_words(p, _SUB_KEY_WORD_LIMIT) for p in paragraphs]
    keyed: list[tuple[str, str]] = []
    for index, words in enumerate(prefixes):
        others = [other for position, other in enumerate(prefixes) if position != index]
        for length in range(1, len(words) + 1):
            head = words[:length]
            if all(other[:length] != head for other in others):
                keyed.append((slugify("-".join(head)), " ".join(head)))
                break
        else:
            raise ChunkingError(
                f"two definitions share their first {_SUB_KEY_WORD_LIMIT} words "
                f"({' '.join(words)!r}); a chunk address cannot be built from the text."
            )
    keys = [key for key, _ in keyed]
    duplicates = {key for key in keys if keys.count(key) > 1}
    if duplicates:
        raise ChunkingError(f"definition sub-keys collide after slugifying: {sorted(duplicates)}")
    return keyed


def _split_definitions(clause: Clause) -> list[Chunk]:
    """Carve-out 1: one chunk per defined term.

    Definitions are blank-line separated paragraphs, each opening with the
    defined term in the adessive (``Biojätteellä``). The paragraph before the
    first definition is the clause's own preamble and becomes the clause chunk.
    """
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", clause.body) if block.strip()]
    if len(paragraphs) < 2:
        raise ChunkingError(
            f"{clause.number} § split into {len(paragraphs)} paragraph(s); expected a "
            "preamble followed by one paragraph per defined term."
        )

    heading = f"{clause.number} § {clause.title}"
    chunks = [
        Chunk(
            clause=clause.number,
            sub_key=None,
            citation=heading,
            text=f"{heading}\n{paragraphs[0]}",
        )
    ]
    definitions = paragraphs[1:]
    for paragraph in definitions:
        if not paragraph[:1].isupper():
            raise ChunkingError(
                f"{clause.number} § definition paragraph does not open with a defined "
                f"term: {paragraph[:80]!r}. A definition that lost its opening line is "
                "a silently wrong chunk, so this is a hard error."
            )
    keyed = _definition_sub_keys(definitions)
    for paragraph, (sub_key, term) in zip(definitions, keyed, strict=True):
        chunks.append(
            Chunk(
                clause=clause.number,
                sub_key=sub_key,
                citation=f"{heading} — {term}",
                text=paragraph,
            )
        )
    return chunks


def chunk_clauses(clauses: Sequence[Clause]) -> list[Chunk]:
    """Turn clauses into chunks, applying carve-out 1."""
    chunks: list[Chunk] = []
    for clause in clauses:
        if clause.number == DEFINITIONS_CLAUSE:
            chunks.extend(_split_definitions(clause))
            continue
        heading = f"{clause.number} § {clause.title}"
        chunks.append(
            Chunk(
                clause=clause.number,
                sub_key=None,
                citation=heading,
                text=f"{heading}\n{clause.body}".strip(),
            )
        )
    return chunks

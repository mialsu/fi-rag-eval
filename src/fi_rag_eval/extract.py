"""PDF text extraction and the normalisation the measurement depends on.

Two normalisations happen here, and both are corrections to *PDF artefacts*
rather than retrieval tricks. Getting this wrong makes the eval measure
typesetting instead of retrieval.

``pdftotext -layout`` was chosen during shaping because it preserves the 26 §
emptying-interval table and its footnote; a non-layout extraction collapses the
columns and the interval becomes unreadable.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PDFTOTEXT = "pdftotext"

# Conjunctions that legitimately follow a *real* hyphen at end of line, as in
# "saostus- / ja umpisäiliöiden". Joining those would fuse two words into one.
# Measured on the Lounais-Suomi source: this guard fires 0 times, so it is a
# safety net for later documents, not a fix for a problem we have seen.
_COORDINATING = frozenset({"ja", "tai", "sekä", "seka", "eli", "että", "etta"})

_DOT_LEADER = re.compile(r"\.{4,}")


class ExtractionError(RuntimeError):
    """The source could not be turned into text we are willing to index."""


@dataclass(frozen=True, slots=True)
class Extraction:
    """Extracted text plus the counts that make the normalisation auditable."""

    text: str
    """Layout-preserved body text: front matter and table of contents removed."""

    front_matter: str
    """Everything before the table of contents. Carries the approval dates."""

    toc: str
    """The table of contents block, kept because it is the clause inventory."""

    hyphen_joins: int
    """Line-break hyphens repaired. A corpus statistic worth reporting."""

    conjunction_guards: int
    """Line-break hyphens deliberately *not* repaired, before a conjunction."""

    page_breaks: int
    """Form feeds seen. Reported so a silent extraction change is visible."""


def pdf_to_text(pdf: Path) -> str:
    """Run ``pdftotext -layout`` and return its UTF-8 output verbatim."""
    if shutil.which(PDFTOTEXT) is None:
        raise ExtractionError(
            f"{PDFTOTEXT} is not on PATH. Install poppler-utils "
            "(Debian/Ubuntu: apt install poppler-utils)."
        )
    if not pdf.is_file():
        raise ExtractionError(f"source not found: {pdf}")
    # Fixed argv; the only variable is a path taken from the checked-in manifest.
    result = subprocess.run(
        [PDFTOTEXT, "-layout", "-enc", "UTF-8", str(pdf), "-"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ExtractionError(
            f"{PDFTOTEXT} failed on {pdf} (exit {result.returncode}): "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    return result.stdout.decode("utf-8")


def split_page_breaks(text: str) -> tuple[str, int]:
    """Turn form feeds into paragraph breaks, but only where a paragraph starts.

    ``pdftotext`` emits ``\\f`` immediately before the first line of a new page,
    with no blank line. Two different things hide behind that:

    * a page break *inside* a paragraph -- the continuation line starts
      lower-case, and stripping the form feed keeps the paragraph whole;
    * a page break *between* paragraphs -- the next line starts upper-case.

    The distinction matters for 2 § Määritelmät, whose ~30 definitions are
    blank-line separated and span a page boundary. Without this, one definition
    swallows the next.
    """
    count = text.count("\f")
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        if not line.startswith("\f"):
            out.append(line)
            continue
        stripped = line.lstrip("\f")
        head = stripped.lstrip()
        if head[:1].isupper() or head[:1] in {"•", "*"}:
            out.append("")
        out.append(stripped)
    return "\n".join(out), count


def dehyphenate(text: str) -> tuple[str, int, int]:
    """Repair line-break hyphens: ``taa-\\njamassa`` -> ``taajamassa``.

    Justified Finnish body text is hyphenated at the right margin, so 258 of this
    document's words arrive split in two. A lexical index over the unrepaired text
    would be measuring the typesetter, not the retriever: ``taajama`` cannot match
    ``taa-`` + ``jamassa`` by any stemmer.

    Returns the repaired text, the number of joins, and the number of times the
    conjunction guard declined to join.
    """
    lines = text.split("\n")
    out: list[str] = []
    joins = 0
    guards = 0
    for line in lines:
        if out and out[-1].endswith("-"):
            head = line.lstrip()
            first_word = re.split(r"[\s,.;:]", head, maxsplit=1)[0]
            if head[:1].islower():
                if first_word.lower() in _COORDINATING:
                    guards += 1
                    out.append(line)
                    continue
                out[-1] = out[-1][:-1] + head
                joins += 1
                continue
        out.append(line)
    return "\n".join(out), joins, guards


def extract(pdf: Path) -> Extraction:
    """Extract a source PDF into indexable body text plus its own inventory.

    The table of contents is separated rather than discarded: it is the
    document's own list of clauses and their full titles, and the body headings
    are cross-checked against it during chunking. Front matter is kept because
    it carries the approval and amendment dates.
    """
    raw = pdf_to_text(pdf)
    paged, page_breaks = split_page_breaks(raw)
    lines = paged.split("\n")

    leader_lines = [i for i, line in enumerate(lines) if _DOT_LEADER.search(line)]
    if not leader_lines:
        raise ExtractionError(
            f"{pdf}: no dot-leader lines found, so the table of contents could not "
            "be located. The extractor or the document layout has changed; refusing "
            "to chunk against an unverified clause inventory."
        )
    first, last = leader_lines[0], leader_lines[-1]

    front_matter = "\n".join(lines[:first])
    toc = "\n".join(lines[first : last + 1])
    body_raw = "\n".join(lines[last + 1 :])
    body, joins, guards = dehyphenate(body_raw)
    return Extraction(
        text=body,
        front_matter=front_matter,
        toc=toc,
        hyphen_joins=joins,
        conjunction_guards=guards,
        page_breaks=page_breaks,
    )

"""Chunk addressing.

A chunk is addressed in the *document's own* terms, never the chunker's, so that
hand-written golden labels survive re-extraction and re-chunking (ADR-0004):

    authority @ effective_date # clause [ . sub_key ]

    lounais-suomi@2024-08-01#26
    lounais-suomi@2024-08-01#2.biojatteella

An address that cannot be resolved is a hard error, never a skipped question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_AUTHORITY = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_SUB_KEY = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_PATTERN = re.compile(
    rf"^(?P<authority>{_AUTHORITY})"
    r"@(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"#(?P<clause>\d+)"
    rf"(?:\.(?P<sub_key>{_SUB_KEY}))?$"
)


class AddressError(ValueError):
    """A chunk address is malformed, or does not resolve to a chunk."""


@dataclass(frozen=True, slots=True, order=True)
class ChunkAddress:
    """One chunk's stable identity."""

    authority: str
    effective_date: date
    clause: int
    sub_key: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(_AUTHORITY, self.authority):
            raise AddressError(f"authority must be a lowercase slug, got {self.authority!r}")
        if self.clause < 1:
            raise AddressError(f"clause must be a positive integer, got {self.clause!r}")
        if self.sub_key is not None and not re.fullmatch(_SUB_KEY, self.sub_key):
            raise AddressError(f"sub_key must be a lowercase slug, got {self.sub_key!r}")

    def __str__(self) -> str:
        tail = "" if self.sub_key is None else f".{self.sub_key}"
        return f"{self.authority}@{self.effective_date.isoformat()}#{self.clause}{tail}"

    @classmethod
    def parse(cls, raw: str) -> ChunkAddress:
        match = _PATTERN.match(raw.strip())
        if match is None:
            raise AddressError(
                f"not a chunk address: {raw!r} (expected authority@YYYY-MM-DD#clause[.sub_key])"
            )
        try:
            effective = date(
                int(match["year"]),
                int(match["month"]),
                int(match["day"]),
            )
        except ValueError as exc:
            raise AddressError(f"not a chunk address: {raw!r} ({exc})") from exc
        return cls(
            authority=match["authority"],
            effective_date=effective,
            clause=int(match["clause"]),
            sub_key=match["sub_key"],
        )


def slugify(word: str) -> str:
    """Fold one Finnish word into an address-safe sub-key.

    Deliberately *not* lemmatising. The document writes its definitions in the
    adessive (``Biojätteellä``), and guessing the nominative needs real
    morphology -- which is exactly what slice 1 does not have and what would make
    an address unstable. The sub-key is therefore the leading word as written.
    """
    folded = word.lower()
    for source, target in (("ä", "a"), ("ö", "o"), ("å", "a"), ("é", "e")):
        folded = folded.replace(source, target)
    folded = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    if not folded:
        raise AddressError(f"cannot build a sub-key from {word!r}")
    return folded

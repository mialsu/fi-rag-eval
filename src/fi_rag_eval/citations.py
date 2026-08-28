"""Citation checking, the half that needs no judge.

`SPEC-slice-5` derives this split from the evidence rather than choosing it:
*"Address validity is pure arithmetic -- is the cited address in the retrieved
set, is it in `required_chunks` -- needing no judge, no floor and no network. Only
'does the cited chunk support this claim' needs the judge."*

So this module answers three questions with no model anywhere in them, and it is
the answer layer's most trustworthy output for exactly the reason `metrics.py` is
the retrieval layer's:

1. **Is the citation an address at all?** A model can emit `[15 §]`, `[#15]` or
   `[lähde 3]`. None of those resolve to a chunk, and a citation that cannot be
   resolved defends nothing.
2. **Was the cited chunk one this question was given?** An address the answerer
   never saw is fabricated, whatever else is true about it -- including the case
   that matters most here, an address belonging to the authority the question was
   *not* asked about.
3. **Was it one the answer was supposed to need?** Cited chunks outside
   `required_chunks` are not wrong -- an answer may legitimately lean on a
   definition clause -- so this one is a diagnostic and never a verdict.

The judged question, *does this chunk carry this claim*, is `judge.py`'s and is
deliberately not here: mixing them would put a floor and a provider dependency on
the one number in this layer that needs neither.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fi_rag_eval.addressing import AddressError, ChunkAddress


@dataclass(frozen=True, slots=True)
class CitationCheck:
    """One answer's citations, checked against the context it was given."""

    question_id: str
    cited: tuple[str, ...]
    """Every citation the answer emitted, as emitted, in order."""

    unparseable: tuple[str, ...]
    """Citations that are not chunk addresses. Cannot defend anything."""

    outside: tuple[str, ...]
    """Parseable addresses the question did not retrieve. Fabricated."""

    inside: tuple[str, ...]
    """Parseable addresses the question did retrieve. The only kind that can support."""

    foreign: tuple[str, ...]
    """The subset of `outside` belonging to another authority than the question's.

    Named separately because it is the product's #1 failure mode
    (`CLAUDE.md` §3) reappearing one layer up: the retrieval filter can be
    perfect while the answerer invents a cross-authority citation out of nothing.
    Tracer slice 3 proved no foreign chunk enters the top-k; that is a different
    claim from "the answer never cites one".
    """

    @property
    def resolvable(self) -> tuple[str, ...]:
        """Citations that name a real chunk this question was handed."""
        return self.inside

    @property
    def invalid(self) -> tuple[str, ...]:
        """Every citation that cannot support a claim about this context."""
        return self.unparseable + self.outside

    @property
    def address_validity(self) -> float | None:
        """Share of emitted citations that name a chunk this question retrieved.

        `None` when the answer cited nothing, so an answer with no citations is
        never averaged in as a zero -- a refusal legitimately cites nothing, and a
        cowardly answer is punished by branch coverage rather than here.
        """
        if not self.cited:
            return None
        return len(self.inside) / len(self.cited)


def check(
    *,
    question_id: str,
    citations: Sequence[str],
    retrieved: Sequence[str],
    authority: str | None = None,
) -> CitationCheck:
    """Classify one answer's citations. Pure; raises only on programmer error.

    `authority` is the authority the question was asked under, used only to split
    `foreign` out of `outside`. Optional because the split is a diagnostic and its
    absence must not make the rest of the check unavailable.
    """
    if not question_id:
        raise ValueError("a citation check is attached to a question id")
    seen = set(retrieved)
    unparseable: list[str] = []
    outside: list[str] = []
    inside: list[str] = []
    foreign: list[str] = []
    for raw in citations:
        try:
            address = ChunkAddress.parse(raw)
        except AddressError:
            # Not an error here by decision: what the model puts inside the
            # envelope is the behaviour under measurement, and raising would
            # delete exactly the failures this module exists to count.
            unparseable.append(raw)
            continue
        # Compared as the address renders, not as the model spelled it, so
        # whitespace or a stray case difference is not scored as fabrication.
        canonical = str(address)
        if canonical in seen:
            inside.append(canonical)
            continue
        outside.append(canonical)
        if authority is not None and address.authority != authority:
            foreign.append(canonical)
    return CitationCheck(
        question_id=question_id,
        cited=tuple(citations),
        unparseable=tuple(unparseable),
        outside=tuple(outside),
        inside=tuple(inside),
        foreign=tuple(foreign),
    )


@dataclass(frozen=True, slots=True)
class AddressValidity:
    """Address validity over a population of answers. No judge, no network."""

    answers: int
    answers_citing: int
    """How many answers cited anything. The denominator that is not `answers`."""

    citations: int
    inside: int
    outside: int
    unparseable: int
    foreign: int
    offenders: tuple[str, ...]
    """Answers that emitted at least one citation which cannot support a claim."""

    foreign_offenders: tuple[str, ...]
    """Answers that cited another authority. Named, because one is one too many."""

    @property
    def validity(self) -> float | None:
        """Share of all emitted citations that name a retrieved chunk."""
        if not self.citations:
            return None
        return self.inside / self.citations

    @property
    def clean_answers(self) -> float | None:
        """Share of citing answers whose every citation resolves.

        Reported beside `validity` because the two fail differently: one bad
        citation in each of ten answers and ten bad citations in one answer give
        the same `validity` and are not the same defect.
        """
        if not self.answers_citing:
            return None
        return (self.answers_citing - len(self.offenders)) / self.answers_citing


def address_validity(checks: Sequence[CitationCheck]) -> AddressValidity:
    """Roll individual checks up. Arithmetic only."""
    if not checks:
        raise ValueError("refusing to compute address validity over zero answers")
    return AddressValidity(
        answers=len(checks),
        answers_citing=sum(1 for c in checks if c.cited),
        citations=sum(len(c.cited) for c in checks),
        inside=sum(len(c.inside) for c in checks),
        outside=sum(len(c.outside) for c in checks),
        unparseable=sum(len(c.unparseable) for c in checks),
        foreign=sum(len(c.foreign) for c in checks),
        offenders=tuple(c.question_id for c in checks if c.invalid),
        foreign_offenders=tuple(c.question_id for c in checks if c.foreign),
    )

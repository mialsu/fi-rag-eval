"""The golden set: the hand-written, hand-answered questions the harness scores against.

Two properties of this file are load-bearing and neither is enforceable by a
test, so they are stated here and audited by hand:

* **Labels are written from the sources, never from retriever output.** A label
  derived from what the retriever returned makes recall@k measure the retriever
  against itself, and every downstream number inherits the circularity. Each
  entry therefore carries a ``label_source`` naming the clause and the sentence
  it was read from.
* **The entry shape is ADR-0003's from the start.** ``required_branches`` and
  ``forbidden`` are validated but unused in slice 1 -- retrieval needs neither.
  They are here so the answering slice does not force a relabelling pass over
  work that is expensive to redo by hand.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from fi_rag_eval.addressing import AddressError, ChunkAddress
from fi_rag_eval.manifest import Manifest

SUPPORTED_VERSION = 1


class GoldenSetError(ValueError):
    """The golden set is malformed, or disagrees with the manifest."""


class Phrasing(StrEnum):
    """Where a question's *wording* came from. The anti-circularity audit trail.

    Only the wording is at stake here -- every label is hand-written from the
    source either way. But a question phrased from the regulation text inherits
    its vocabulary, which inflates recall without improving retrieval, so the
    provenance of the wording is worth recording per question rather than
    asserting once in a comment.
    """

    HARVESTED = "harvested"
    """Copied verbatim from a public resident-facing page. Cannot be circular."""

    AUTHORED = "authored"
    """Written for this set. Held to the leakage of the harvested sample."""


@dataclass(frozen=True, slots=True)
class Branch:
    """One conditional branch a correct answer must state. Scored from slice 4."""

    claim: str
    chunk: ChunkAddress


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    question: str
    phrasing: Phrasing
    phrasing_source: str | None
    municipality: str
    required_chunks: tuple[ChunkAddress, ...]
    required_branches: tuple[Branch, ...]
    forbidden: tuple[str, ...]
    label_source: str

    @property
    def required_addresses(self) -> tuple[str, ...]:
        return tuple(str(address) for address in self.required_chunks)


@dataclass(frozen=True, slots=True)
class GoldenSet:
    questions: tuple[Question, ...]

    def __len__(self) -> int:
        return len(self.questions)

    def count_by_phrasing(self, phrasing: Phrasing) -> int:
        return sum(1 for question in self.questions if question.phrasing is phrasing)


def _address(raw: Any, where: str) -> ChunkAddress:
    try:
        return ChunkAddress.parse(str(raw))
    except AddressError as exc:
        raise GoldenSetError(f"{where}: {exc}") from exc


def _parse_question(raw: Mapping[str, Any], manifest: Manifest, where: str) -> Question:
    for key in ("id", "question", "phrasing", "municipality", "required_chunks", "label_source"):
        if key not in raw:
            raise GoldenSetError(f"{where}: missing required key {key!r}")
    question_id = str(raw["id"])
    where = f"{where} question {question_id!r}"

    raw_required = raw["required_chunks"]
    if not isinstance(raw_required, Sequence) or isinstance(raw_required, str) or not raw_required:
        raise GoldenSetError(
            f"{where}: required_chunks must be a non-empty list. A question with nothing "
            "to retrieve scores a vacuous 1.0; refusal cases arrive with the answering slice."
        )
    required = tuple(_address(item, where) for item in raw_required)
    if len({str(a) for a in required}) != len(required):
        raise GoldenSetError(f"{where}: required_chunks lists the same address twice")

    try:
        phrasing = Phrasing(str(raw["phrasing"]))
    except ValueError as exc:
        allowed = ", ".join(sorted(p.value for p in Phrasing))
        raise GoldenSetError(f"{where}: phrasing must be one of {allowed}") from exc
    phrasing_source = raw.get("phrasing_source")
    if phrasing is Phrasing.HARVESTED and not phrasing_source:
        raise GoldenSetError(
            f"{where}: phrasing 'harvested' claims the wording came from a public "
            "resident-facing page, so phrasing_source must name that page. An unsourced "
            "claim of independence is worth nothing."
        )
    if phrasing is Phrasing.AUTHORED and phrasing_source:
        raise GoldenSetError(
            f"{where}: phrasing 'authored' means the wording is ours, so phrasing_source "
            "must be absent -- otherwise the provenance of the two is indistinguishable."
        )

    municipality = str(raw["municipality"])
    authority = manifest.resolve_municipality(municipality)
    foreign = [str(a) for a in required if a.authority != authority.key]
    if foreign:
        raise GoldenSetError(
            f"{where}: municipality {municipality!r} resolves to authority "
            f"{authority.key!r} but the label points at {foreign}. A label that crosses "
            "jurisdictions is the failure mode the hard filter exists to prevent."
        )

    branches: list[Branch] = []
    for item in raw.get("required_branches") or ():
        if not isinstance(item, Mapping) or "claim" not in item or "chunk" not in item:
            raise GoldenSetError(f"{where}: each required_branch needs a claim and a chunk")
        chunk = _address(item["chunk"], where)
        if str(chunk) not in {str(a) for a in required}:
            raise GoldenSetError(
                f"{where}: branch cites {chunk}, which is not in required_chunks. "
                "A branch whose supporting chunk is not required cannot be grounded."
            )
        branches.append(Branch(claim=str(item["claim"]), chunk=chunk))

    forbidden = tuple(str(item) for item in raw.get("forbidden") or ())
    return Question(
        id=question_id,
        question=str(raw["question"]),
        phrasing=phrasing,
        phrasing_source=None if phrasing_source is None else str(phrasing_source),
        municipality=municipality,
        required_chunks=required,
        required_branches=tuple(branches),
        forbidden=forbidden,
        label_source=str(raw["label_source"]),
    )


def load_golden_set(path: Path, manifest: Manifest) -> GoldenSet:
    if not path.is_file():
        raise GoldenSetError(f"golden set not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise GoldenSetError(f"{path}: expected a mapping at the top level")
    version = document.get("version")
    if version != SUPPORTED_VERSION:
        raise GoldenSetError(
            f"{path}: golden set version {version!r}, expected {SUPPORTED_VERSION}"
        )
    raw_questions = document.get("questions")
    if not isinstance(raw_questions, Sequence) or not raw_questions:
        raise GoldenSetError(f"{path}: questions must be a non-empty list")

    questions = tuple(
        _parse_question(raw, manifest, str(path))
        for raw in raw_questions
        if isinstance(raw, Mapping)
    )
    if len(questions) != len(raw_questions):
        raise GoldenSetError(f"{path}: every question must be a mapping")
    ids = [q.id for q in questions]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise GoldenSetError(f"{path}: duplicate question ids {duplicates}")
    return GoldenSet(questions=questions)

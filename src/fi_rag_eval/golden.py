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


class RefusalKind(StrEnum):
    """The two ways a question can be unanswerable (slice 5, D4).

    They are separated because they are not equally hard and the spec
    pre-registers that difference: out-of-corpus is the *easy* refusal -- little
    or nothing plausible retrieves, so declining is nearly free -- while
    out-of-jurisdiction hands the answerer five plausible, same-topic chunks from
    the authority it was actually asked about. Pooling them would let the easy
    kind carry the metric, which is structurally the same move as diluting a
    golden set with easy questions.
    """

    OUT_OF_CORPUS = "out-of-corpus"
    """The subject matter is genuinely absent from these jatehuoltomaaraykset."""

    OUT_OF_JURISDICTION = "out-of-jurisdiction"
    """Answerable only from authority A, asked with authority B's filter.

    This is the kind that closes the hard-filter debt: `CLAUDE.md` specifies the
    filter as a **refusal**, and until slice 5 what was verified was only that a
    foreign chunk never enters the top-k.
    """


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
    pair: str | None = None
    """Names the paired question this is one half of, or ``None`` (slice 4, D7).

    A **paired question** is one question *text* labelled twice, once per
    authority, on a topic where the two authorities' rules genuinely differ and
    their vocabulary forks (`jäteastia` / `keräysväline`). Both halves carry the
    same slug here, and `load_golden_set` enforces that a slug names exactly two
    entries with identical text and different authorities -- which is what makes
    "the same question retrieves different chunks per authority" a checked
    property rather than an eyeballed one.
    """

    @property
    def authority(self) -> str:
        """The authority every required chunk belongs to. Validated on load."""
        return self.required_chunks[0].authority

    @property
    def required_addresses(self) -> tuple[str, ...]:
        return tuple(str(address) for address in self.required_chunks)


@dataclass(frozen=True, slots=True)
class RefusalQuestion:
    """A question whose only correct answer is a Refusal.

    Deliberately a **different type** from `Question` rather than a `Question`
    with an empty `required_chunks`. The two populations must never be pooled --
    complete-set recall over a question with nothing to retrieve is a vacuous 1.0
    -- and the cheapest way to make that unrepresentable is to make it not
    type-check. `evaluate` takes `Question`s; nothing here can reach it.
    """

    id: str
    question: str
    kind: RefusalKind
    phrasing: Phrasing
    phrasing_source: str | None
    municipality: str
    absent_lexeme: str
    """A substring that would appear in this authority's text if the topic were
    covered, and is asserted at every run to be absent from it.

    **This is a drift detector, not a proof.** The absence *claim* is hand-made
    from the clause list and recorded in `absence_source`; what this string buys
    is that the claim cannot rot silently -- add the clause, or ingest a new
    edition that covers the topic, and the run goes red instead of scoring a
    correct answer as a missed refusal. The converse does not hold: a word can be
    absent while the topic is covered under another name, which is exactly how
    three of this spec's six pre-registered asymmetries were caught being wrong.
    """

    absence_source: str
    """How the absence was established by hand -- the clause list that was read."""

    answerable_from: ChunkAddress | None
    """For out-of-jurisdiction: the chunk in the *other* authority that answers it.

    Required for `OUT_OF_JURISDICTION` and forbidden for `OUT_OF_CORPUS`, so the
    entry cannot claim to be one kind while carrying the other's evidence. It is
    a label that deliberately crosses jurisdictions -- the one thing
    `_parse_question` refuses -- which is the point: the question is asked with
    authority B's filter and the answer lives in authority A.
    """

    label_source: str

    @property
    def foreign_authority(self) -> str | None:
        return None if self.answerable_from is None else self.answerable_from.authority


@dataclass(frozen=True, slots=True)
class GoldenSet:
    questions: tuple[Question, ...]
    """The answerable population. **This alone is the retrieval headline's N.**"""

    refusals: tuple[RefusalQuestion, ...] = ()
    """The refusal population. Scored by the answer layer, never by `compute`."""

    def __len__(self) -> int:
        """The answerable count, deliberately -- `len(golden)` is the recall N.

        Refusal questions are reached through `.refusals`, so no caller can pick
        them up by accident while believing it is iterating the scored set.
        """
        return len(self.questions)

    def count_by_phrasing(self, phrasing: Phrasing) -> int:
        return sum(1 for question in self.questions if question.phrasing is phrasing)


def _address(raw: Any, where: str) -> ChunkAddress:
    try:
        return ChunkAddress.parse(str(raw))
    except AddressError as exc:
        raise GoldenSetError(f"{where}: {exc}") from exc


def _parse_phrasing(raw: Mapping[str, Any], where: str) -> tuple[Phrasing, str | None]:
    """The provenance rules, shared by both populations.

    A refusal question's wording can be harvested or authored exactly like an
    answerable one's, and the anti-circularity argument is the same, so the rule
    lives in one place rather than being restated and allowed to drift.
    """
    try:
        phrasing = Phrasing(str(raw["phrasing"]))
    except ValueError as exc:
        allowed = ", ".join(sorted(p.value for p in Phrasing))
        raise GoldenSetError(f"{where}: phrasing must be one of {allowed}") from exc
    except KeyError as exc:
        raise GoldenSetError(f"{where}: missing required key 'phrasing'") from exc
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
    return phrasing, None if phrasing_source is None else str(phrasing_source)


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

    phrasing, phrasing_source = _parse_phrasing(raw, where)

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
    pair = raw.get("pair")
    return Question(
        id=question_id,
        question=str(raw["question"]),
        phrasing=phrasing,
        phrasing_source=phrasing_source,
        municipality=municipality,
        required_chunks=required,
        required_branches=tuple(branches),
        forbidden=forbidden,
        label_source=str(raw["label_source"]),
        pair=None if pair is None else str(pair),
    )


PIRKANMAA_18 = "pirkanmaa@2021-07-01#18"
"""The one address a refusal question may not point at (slice 5, open questions).

`18 a § KOMPOSTOINTI-ILMOITUS` is a real Pirkanmaa clause absent from the
document's own table of contents, so the body/TOC cross-check is silent and its
text is absorbed into `18 §`'s chunk. Two clauses share one address. Fixing it
changes Pirkanmaa's chunk count, which invalidates the manifest's `expected`
block -- the block that exists to refuse a document parsing differently than it
did when 199 labels were hand-written. The cheap guard was adopted instead.
"""


def _parse_refusal(raw: Mapping[str, Any], manifest: Manifest, where: str) -> RefusalQuestion:
    """One refusal entry, with the checks that keep the two kinds distinguishable."""
    for key in (
        "id",
        "question",
        "kind",
        "phrasing",
        "municipality",
        "absent_lexeme",
        "absence_source",
        "label_source",
    ):
        if key not in raw:
            raise GoldenSetError(f"{where}: missing required key {key!r}")
    refusal_id = str(raw["id"])
    where = f"{where} refusal {refusal_id!r}"

    try:
        kind = RefusalKind(str(raw["kind"]))
    except ValueError as exc:
        allowed = ", ".join(sorted(k.value for k in RefusalKind))
        raise GoldenSetError(f"{where}: kind must be one of {allowed}") from exc

    phrasing, phrasing_source = _parse_phrasing(raw, where)

    municipality = str(raw["municipality"])
    # Resolving here means a refusal question asked for a partially-covered kunta
    # raises the same way a resident's query would -- the harness never carries a
    # municipality it could not have answered for in the first place.
    asked = manifest.resolve_municipality(municipality)

    absent_lexeme = str(raw["absent_lexeme"]).strip()
    if not absent_lexeme:
        raise GoldenSetError(
            f"{where}: absent_lexeme is empty, so nothing about this entry's central "
            "claim would ever be checked. A refusal question with no drift detector is "
            "an assertion, and this project does not score against assertions."
        )

    raw_answerable = raw.get("answerable_from")
    answerable_from = None if raw_answerable is None else _address(raw_answerable, where)
    if kind is RefusalKind.OUT_OF_JURISDICTION:
        if answerable_from is None:
            raise GoldenSetError(
                f"{where}: an out-of-jurisdiction refusal must name answerable_from -- "
                "the chunk in the OTHER authority that does answer it. Without it the "
                "entry claims the hard kind of refusal while carrying no evidence that "
                "the question is answerable anywhere, which is the easy kind."
            )
        if answerable_from.authority == asked.key:
            raise GoldenSetError(
                f"{where}: answerable_from {answerable_from} belongs to {asked.key!r}, "
                f"the very authority {municipality!r} resolves to. An out-of-jurisdiction "
                "refusal is a question asked with the WRONG authority's filter; if the "
                "answer is in the same jurisdiction, the question is answerable and "
                "refusing it would be the defect, not the metric."
            )
    elif answerable_from is not None:
        raise GoldenSetError(
            f"{where}: an out-of-corpus refusal must not name answerable_from. It claims "
            f"the subject matter is absent from the corpus, and {answerable_from} says it "
            "is not. The kinds are scored separately precisely because they differ."
        )

    if answerable_from is not None and str(answerable_from) == PIRKANMAA_18:
        raise GoldenSetError(
            f"{where}: no refusal question may point at {PIRKANMAA_18}. That chunk "
            "silently contains `18 a §`'s text as well as `18 §`'s, so a citation "
            "naming it names a clause that does not have that text under its own "
            "number. Deferred deliberately; see the slice-5 spec's open questions."
        )

    return RefusalQuestion(
        id=refusal_id,
        question=str(raw["question"]),
        kind=kind,
        phrasing=phrasing,
        phrasing_source=phrasing_source,
        municipality=municipality,
        absent_lexeme=absent_lexeme,
        absence_source=str(raw["absence_source"]),
        answerable_from=answerable_from,
        label_source=str(raw["label_source"]),
    )


def load_golden_set(path: Path, manifest: Manifest) -> GoldenSet:
    """Load the golden set from one YAML file, or from a directory of them.

    A directory loads every ``*.yaml`` inside it, in filename order, and merges
    them into one set. The corpus has one file per authority -- each carrying its
    own provenance header, because how its questions were worded is the most
    important thing about it -- while the metrics are pooled over all of them
    (slice 4, D11): one headline over the whole corpus the harness covers, with a
    per-authority breakdown beneath it as a diagnostic.

    Refusal questions live in their own file rather than in the authority files
    (slice 5, tracer 3). They are a separate *population*, not a separate
    authority: they never enter recall, and putting them beside the scored
    questions would make "these are excluded from the headline" a fact you have
    to remember rather than one you can see.
    """
    if path.is_dir():
        files = sorted(path.glob("*.yaml"))
        if not files:
            raise GoldenSetError(f"no *.yaml golden-set files in {path}")
        loaded = [_load_file(file, manifest) for file in files]
        merged = GoldenSet(
            questions=tuple(q for one in loaded for q in one.questions),
            refusals=tuple(r for one in loaded for r in one.refusals),
        )
        return _validated(merged, str(path))
    return _validated(_load_file(path, manifest), str(path))


def _validated(golden: GoldenSet, where: str) -> GoldenSet:
    """Whole-set invariants: unique ids, and well-formed paired questions."""
    # Across BOTH populations: an id is how a run, an answer file and a hand
    # label refer to one another, so a collision between the two populations
    # would silently attach a refusal's verdict to an answerable question.
    ids = [q.id for q in golden.questions] + [r.id for r in golden.refusals]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise GoldenSetError(f"{where}: duplicate question ids {duplicates}")

    refusal_texts: dict[str, list[str]] = {}
    for refusal in golden.refusals:
        refusal_texts.setdefault(refusal.question, []).append(refusal.id)
    answerable_texts = {q.question for q in golden.questions}
    collisions = sorted(t for t in refusal_texts if t in answerable_texts)
    if collisions:
        raise GoldenSetError(
            f"{where}: these question texts appear in BOTH populations: {collisions}. "
            "One text cannot be both answerable and unanswerable in the same corpus; "
            "either the refusal label is wrong or the answerable one is."
        )
    repeated = sorted(t for t, members in refusal_texts.items() if len(members) > 1)
    if repeated:
        raise GoldenSetError(
            f"{where}: these refusal texts appear more than once: {repeated}. Refusal "
            "questions are not paired questions -- a repeated text double-counts one "
            "behaviour in a population of fourteen."
        )

    texts: dict[str, list[Question]] = {}
    for question in golden.questions:
        texts.setdefault(question.question, []).append(question)
    undeclared = {
        text: [q.id for q in members]
        for text, members in texts.items()
        if len(members) > 1 and len({q.pair for q in members}) != 1
    }
    if undeclared:
        raise GoldenSetError(
            f"{where}: these question texts appear more than once without being declared "
            f"a pair: {undeclared}. Two entries asking the same thing IS a paired "
            "question; declaring it makes the comparison visible and checked, and "
            "leaving it undeclared hides a measurement the set is already taking."
        )

    pairs: dict[str, list[Question]] = {}
    for question in golden.questions:
        if question.pair is not None:
            pairs.setdefault(question.pair, []).append(question)
    for slug, members in sorted(pairs.items()):
        if len(members) != 2:
            raise GoldenSetError(
                f"{where}: paired question {slug!r} has {len(members)} half/halves "
                f"({[q.id for q in members]}); a pair is exactly one question text "
                "labelled once per authority, and a lone half measures nothing."
            )
        first, second = members
        if first.question != second.question:
            raise GoldenSetError(
                f"{where}: the halves of paired question {slug!r} ask different things:\n"
                f"  {first.id}: {first.question!r}\n"
                f"  {second.id}: {second.question!r}\n"
                "The pair exists to hold the question text fixed while the authority "
                "changes; two different texts measure two different questions."
            )
        if first.authority == second.authority:
            raise GoldenSetError(
                f"{where}: both halves of paired question {slug!r} are labelled against "
                f"authority {first.authority!r}. A pair that does not cross authorities "
                "cannot show that the same question retrieves different rules."
            )
    return golden


def _load_file(path: Path, manifest: Manifest) -> GoldenSet:
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
    raw_questions = _entries(document, "questions", path)
    raw_refusals = _entries(document, "refusals", path)
    if not raw_questions and not raw_refusals:
        raise GoldenSetError(
            f"{path}: a golden-set file must carry a non-empty 'questions' or "
            "'refusals' list. An empty file contributes nothing and hides a typo in "
            "the key name as though it were an intentional omission."
        )

    questions = tuple(_parse_question(raw, manifest, str(path)) for raw in raw_questions)
    refusals = tuple(_parse_refusal(raw, manifest, str(path)) for raw in raw_refusals)
    return GoldenSet(questions=questions, refusals=refusals)


def _entries(document: Mapping[str, Any], key: str, path: Path) -> tuple[Mapping[str, Any], ...]:
    raw = document.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, str) or not raw:
        raise GoldenSetError(f"{path}: {key} must be a non-empty list when present")
    entries = tuple(item for item in raw if isinstance(item, Mapping))
    if len(entries) != len(raw):
        raise GoldenSetError(f"{path}: every entry under {key} must be a mapping")
    return entries

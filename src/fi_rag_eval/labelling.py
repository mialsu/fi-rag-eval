"""The hand-labelling protocol: 168 blind labels against a committed sample.

ADR-0011 settled the protocol before this module existed, because a label written
under a biased procedure is not a weaker label -- it is worthless, and nobody can
tell by looking at it.

Four properties this module exists to hold.

**Labelling is BLIND.** Nothing the judge produced reaches the Owner: not a
verdict, not a suggestion, not a confidence, and **not a stability flag**. The flag
was proposed as a labelling aid and rejected as one -- it does not reveal which way
the judge went, but it reveals *where the judge was uncertain*, which allocates the
Owner's attention by the judge's own doubt and stops the comparison being a
comparison. Stability is a diagnostic applied afterwards.

**Forced units are not labelled, and not counted.** A refused answer states
nothing, so both the judge (`judge.parse_verdicts` normalises it) and any honest
human are forced to *not stated* / *not asserted* on every one of its units.
Measured on the frozen sample: **31 of 199 units sit under the 7 refused answers**.
Pooling them hands the judge **0.156 agreement before a word is read**, and -- the
part that matters -- **a judge agreeing on only 0.827 of the informative units
would publish at D11's 0.85 floor.** They are excluded from the labelling and from
the denominator, and reported separately so the exclusion is visible rather than
silent.

**Every label is written the moment it is made.** 168 units is one to two hours and
will not happen in one sitting. The file is rewritten atomically after each unit
and labelled units are skipped on restart.

**One pass per unit, grouped by question.** Both fields of a branch in one visit,
so the answer is read once per question rather than once per field.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fi_rag_eval.answer import AnswerError
from fi_rag_eval.golden import GoldenSet
from fi_rag_eval.judging import RecordedRun
from fi_rag_eval.metrics import UnitLabel

DEFAULT_SAMPLE = Path("eval/frozen/sample-tracer5.json")
DEFAULT_LABELS = Path("eval/frozen/labels-owner.yaml")
SUPPORTED_LABEL_VERSION = 1

BRANCH = "branch"
FORBIDDEN = "forbidden"


class LabellingError(AnswerError):
    """The labelling set cannot be built or read honestly."""


@dataclass(frozen=True, slots=True)
class QuestionToLabel:
    """One answer, and every claim that has to be judged about it."""

    question_id: str
    question: str
    municipality: str
    authority_key: str
    answer_text: str
    refused: bool
    citations: tuple[str, ...]
    retrieved: tuple[str, ...]
    branches: tuple[str, ...]
    """The hand-enumerated required branches, in the golden entry's own order."""

    forbidden: tuple[str, ...]

    @property
    def forced(self) -> bool:
        """True when every verdict about this answer is settled before reading it.

        Only refusals, today. A refusal states nothing, so `stated` is false for
        every branch and `asserted` false for every forbidden item on both sides.
        """
        return self.refused

    @property
    def units(self) -> int:
        return len(self.branches) + len(self.forbidden)


@dataclass(frozen=True, slots=True)
class HumanLabel:
    """One unit, labelled by hand. `None` means the field does not apply."""

    question_id: str
    unit: str
    index: int
    stated: bool | None = None
    supported: bool | None = None
    asserted: bool | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.unit not in (BRANCH, FORBIDDEN):
            raise LabellingError(f"unit must be {BRANCH!r} or {FORBIDDEN!r}, got {self.unit!r}")
        if self.index < 1:
            raise LabellingError(f"index is 1-based, got {self.index}")
        if self.unit == BRANCH:
            if self.stated is None:
                raise LabellingError(f"{self.key}: a branch label needs `stated`")
            if self.asserted is not None:
                raise LabellingError(f"{self.key}: a branch has no `asserted`")
            if self.stated and self.supported is None:
                raise LabellingError(
                    f"{self.key}: a branch labelled stated needs `supported` too -- "
                    "groundedness' numerator comes from it"
                )
            if not self.stated and self.supported:
                raise LabellingError(
                    f"{self.key}: supported without stated. A claim the answer never made "
                    "cannot be supported, and this would inflate groundedness above 1.0."
                )
        else:
            if self.asserted is None:
                raise LabellingError(f"{self.key}: a forbidden label needs `asserted`")
            if self.stated is not None or self.supported is not None:
                raise LabellingError(f"{self.key}: a forbidden item has no `stated`/`supported`")

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.question_id, self.unit, self.index)


def questions_to_label(*, golden: GoldenSet, run: RecordedRun) -> tuple[QuestionToLabel, ...]:
    """Pair every answerable answer with its hand-enumerated claims.

    Deterministic and in golden-set order, so two people running this get the same
    sequence and a resumed session continues where it stopped.
    """
    claims = {q.id: q for q in golden.questions}
    answers = {a.question_id: a for a in run.answerable}
    missing = sorted(set(claims) - set(answers))
    if missing:
        raise LabellingError(
            f"the sample has no answer for {missing}. Every golden question is labelled or "
            "agreement is computed over a reduced N."
        )
    out: list[QuestionToLabel] = []
    for question in golden.questions:
        answer = answers[question.id]
        out.append(
            QuestionToLabel(
                question_id=question.id,
                question=answer.question,
                municipality=answer.municipality,
                authority_key=answer.authority_key,
                answer_text=answer.text,
                refused=answer.refused,
                citations=answer.citations,
                retrieved=answer.retrieved,
                branches=tuple(branch.claim for branch in question.required_branches),
                forbidden=tuple(question.forbidden),
            )
        )
    return tuple(out)


def informative(questions: Sequence[QuestionToLabel]) -> tuple[QuestionToLabel, ...]:
    """The answers whose units are worth a human's time. See the module docstring."""
    return tuple(one for one in questions if not one.forced)


def forced_units(questions: Sequence[QuestionToLabel]) -> int:
    return sum(one.units for one in questions if one.forced)


def pending(
    questions: Sequence[QuestionToLabel], labels: Sequence[HumanLabel]
) -> tuple[tuple[QuestionToLabel, str, int], ...]:
    """Every informative unit with no label yet, in order. This is resumability."""
    done = {label.key for label in labels}
    out: list[tuple[QuestionToLabel, str, int]] = []
    for one in informative(questions):
        for index in range(1, len(one.branches) + 1):
            if (one.question_id, BRANCH, index) not in done:
                out.append((one, BRANCH, index))
        for index in range(1, len(one.forbidden) + 1):
            if (one.question_id, FORBIDDEN, index) not in done:
                out.append((one, FORBIDDEN, index))
    return tuple(out)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def load_labels(path: Path) -> tuple[HumanLabel, ...]:
    """Read the label file, or return empty if it does not exist yet."""
    if not path.is_file():
        return ()
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if document is None:
        return ()
    if not isinstance(document, Mapping):
        raise LabellingError(f"{path}: expected a mapping at the top level")
    if document.get("version") != SUPPORTED_LABEL_VERSION:
        raise LabellingError(
            f"{path}: label version {document.get('version')!r}, expected {SUPPORTED_LABEL_VERSION}"
        )
    raw = document.get("labels") or []
    if not isinstance(raw, list):
        raise LabellingError(f"{path}: `labels` must be a list")
    labels: list[HumanLabel] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise LabellingError(f"{path}: label {index} is not a mapping")
        labels.append(
            HumanLabel(
                question_id=str(item.get("question_id", "")),
                unit=str(item.get("unit", "")),
                index=int(item.get("index", 0)),
                stated=_optional_bool(item, "stated", path),
                supported=_optional_bool(item, "supported", path),
                asserted=_optional_bool(item, "asserted", path),
                note=str(item.get("note") or ""),
            )
        )
    keys = [label.key for label in labels]
    if len(set(keys)) != len(keys):
        raise LabellingError(
            f"{path}: the same unit is labelled twice: "
            f"{sorted({k for k in keys if keys.count(k) > 1})}"
        )
    return tuple(labels)


def _optional_bool(item: Mapping[str, Any], field: str, path: Path) -> bool | None:
    value = item.get(field)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise LabellingError(f"{path}: `{field}` must be a boolean or absent, got {value!r}")
    return value


def write_labels(path: Path, labels: Sequence[HumanLabel], *, sample: Path, commit: str) -> None:
    """Rewrite the whole file, atomically.

    Rewritten rather than appended because a label is a small structured record and
    168 of them are a few kilobytes -- and because an interrupted append leaves
    invalid YAML, which would cost the Owner the whole session rather than one
    unit. Atomic via temp-file-and-rename, so a crash mid-write leaves the previous
    file intact.
    """
    payload = {
        "version": SUPPORTED_LABEL_VERSION,
        "sample": str(sample),
        "sample_answered_at_commit": commit,
        "protocol": (
            "BLIND hand labels (ADR-0011). The labeller saw the question, the retrieved "
            "excerpts, the answer and the claim -- and nothing the judge produced. Units "
            "under a refused answer are omitted deliberately: both sides are forced to the "
            "same verdict there, so they measure nothing and would inflate agreement."
        ),
        "labels": [
            {
                key: value
                for key, value in (
                    ("question_id", label.question_id),
                    ("unit", label.unit),
                    ("index", label.index),
                    ("stated", label.stated),
                    ("supported", label.supported),
                    ("asserted", label.asserted),
                    ("note", label.note or None),
                )
                if value is not None
            }
            for label in labels
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=path.name, suffix=".tmp", text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Feeding the agreement arithmetic
# ---------------------------------------------------------------------------


def human_unit_labels(labels: Sequence[HumanLabel]) -> list[UnitLabel]:
    """Flatten hand labels into the shape `metrics.unit_agreement` compares.

    A branch contributes `stated` always and `supported` only when stated -- the
    same coupling `judge.parse_verdicts` enforces on the judge's side, so the two
    sets cover identical units by construction rather than by luck.
    """
    out: list[UnitLabel] = []
    for label in labels:
        if label.unit == BRANCH:
            assert label.stated is not None  # guaranteed by __post_init__
            out.append(
                UnitLabel(
                    question_id=label.question_id,
                    unit=BRANCH,
                    index=label.index,
                    field="stated",
                    value=label.stated,
                )
            )
            if label.stated:
                assert label.supported is not None
                out.append(
                    UnitLabel(
                        question_id=label.question_id,
                        unit=BRANCH,
                        index=label.index,
                        field="supported",
                        value=label.supported,
                    )
                )
        else:
            assert label.asserted is not None
            out.append(
                UnitLabel(
                    question_id=label.question_id,
                    unit=FORBIDDEN,
                    index=label.index,
                    field="asserted",
                    value=label.asserted,
                )
            )
    return out


def judge_unit_labels(
    payload: Mapping[str, Any], *, restrict_to: Sequence[HumanLabel]
) -> list[UnitLabel]:
    """The judge's verdicts for exactly the units a human labelled.

    Restricted rather than filtered afterwards: `unit_agreement` refuses two sets
    that do not cover the same units, and the honest way to satisfy it is to ask
    the judge's file for the human's units -- so a missing verdict is an error
    naming the unit, not a quietly smaller denominator.
    """
    wanted = {label.key: label for label in restrict_to}
    verdicts: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    for answer in payload.get("answers") or []:
        question_id = str(answer.get("question_id", ""))
        for branch in answer.get("branches") or []:
            verdicts[(question_id, BRANCH, int(branch["index"]))] = branch
        for item in answer.get("forbidden") or []:
            verdicts[(question_id, FORBIDDEN, int(item["index"]))] = item

    out: list[UnitLabel] = []
    for key, label in wanted.items():
        verdict = verdicts.get(key)
        if verdict is None:
            raise LabellingError(
                f"the judge's file has no verdict for {key}, which a human labelled. "
                "Agreement over the overlap would be a reduced N nobody chose."
            )
        if label.unit == BRANCH:
            out.append(
                UnitLabel(
                    question_id=key[0],
                    unit=BRANCH,
                    index=key[2],
                    field="stated",
                    value=bool(verdict["stated"]),
                )
            )
            # The human's `stated` decides whether `supported` is in scope, not the
            # judge's. Otherwise the compared unit set would depend on the thing
            # being measured.
            if label.stated:
                out.append(
                    UnitLabel(
                        question_id=key[0],
                        unit=BRANCH,
                        index=key[2],
                        field="supported",
                        value=bool(verdict["supported"]),
                    )
                )
        else:
            out.append(
                UnitLabel(
                    question_id=key[0],
                    unit=FORBIDDEN,
                    index=key[2],
                    field="asserted",
                    value=bool(verdict["asserted"]),
                )
            )
    return out


# ---------------------------------------------------------------------------
# The session
# ---------------------------------------------------------------------------

HELP = (
    "  y / n        the verdict\n"
    "  y <note>     the verdict, with a note (contestable units are worth flagging --\n"
    "               two of the fourteen refusal labels turned out to be arguable)\n"
    "  s            skip this unit, decide later. `agreement` refuses to run while any\n"
    "               unit is unlabelled, so a skip is a deferral and never a silent drop\n"
    "  q            save and quit. Every label already given is on disk\n"
    "  ?            this help"
)


def format_context(
    one: QuestionToLabel, bodies: Mapping[str, str], citations: Mapping[str, str]
) -> str:
    """Everything the labeller may see about one answer, and nothing else.

    Deliberately does not take a judgement, a verdict, or a stability flag. There
    is no parameter here through which the judge's opinion could arrive, which is
    ADR-0011 decision 1 enforced by the signature rather than by discipline.
    """
    lines = [
        f"QUESTION  {one.question}",
        f"          ({one.municipality}, {one.authority_key})",
        "",
        "EXCERPTS the answerer was given:",
    ]
    for address in one.retrieved:
        body = bodies.get(address)
        if body is None:
            raise LabellingError(
                f"chunk {address} has no body in the corpus map, so the labeller would be "
                "judging support against a hole. Re-ingest the corpus."
            )
        lines.append(f"  [{address}] {citations.get(address, '')}")
        lines.append("    " + body.replace("\n", "\n    "))
    lines.append("")
    lines.append(f"ANSWER (citations: {', '.join(one.citations) if one.citations else 'none'}):")
    lines.append("  " + one.answer_text.replace("\n", "\n  "))
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class SessionResult:
    labelled: int
    skipped: int
    quit_early: bool
    remaining: int


@dataclass(frozen=True, slots=True)
class _Reply:
    """One answer to one yes/no prompt: a verdict, a deferral, or a quit.

    Three outcomes, so it is three fields rather than a sentinel value or an
    exception. The first version of this raised on skip and nothing caught it,
    which would have ended a labelling session with a traceback and the Owner
    wondering whether the labels were saved.
    """

    verdict: bool = False
    note: str = ""
    skip: bool = False
    stop: bool = False


def _ask(prompt: Callable[[str], str], emit: Callable[[str], None], question: str) -> _Reply:
    """Ask one yes/no until it gets an answer it understands."""
    while True:
        raw = prompt(f"{question} [y/n/s/q/?] ").strip()
        if not raw:
            continue
        head, _, tail = raw.partition(" ")
        head = head.lower()
        if head == "?":
            emit(HELP)
            continue
        if head == "q":
            return _Reply(stop=True)
        if head == "s":
            return _Reply(skip=True)
        if head in ("y", "n"):
            return _Reply(verdict=head == "y", note=tail.strip())
        emit(f"  '{raw}' is not one of y/n/s/q/?")


def run_session(
    *,
    questions: Sequence[QuestionToLabel],
    labels_path: Path,
    sample_path: Path,
    sample_commit: str,
    bodies: Mapping[str, str],
    citations: Mapping[str, str],
    prompt: Callable[[str], str],
    emit: Callable[[str], None],
) -> SessionResult:
    """Drive one labelling session. Resumable, blind, one unit at a time.

    `prompt` and `emit` are injected so the whole loop is exercisable without a
    terminal -- the interactive shell in `cli.py` is the only part that touches
    stdin, and it holds no logic.
    """
    labels = list(load_labels(labels_path))
    queue = pending(questions, labels)
    total = sum(one.units for one in informative(questions))
    forced = forced_units(questions)
    emit(
        f"{total} units to label across {len(informative(questions))} answers "
        f"({len(labels)} already done, {len(queue)} to go).\n"
        f"{forced} further units sit under refused answers and are NOT labelled: both the "
        f"judge and you are forced to the same verdict there, so they measure nothing.\n"
        f"You will not be shown anything the judge produced (ADR-0011). `?` for help.\n"
    )
    labelled = skipped = 0
    stopped = False
    shown: str | None = None
    for one, unit, index in queue:
        if shown != one.question_id:
            emit("\n" + "=" * 78)
            emit(format_context(one, bodies, citations))
            emit("=" * 78)
            shown = one.question_id
        count = len(one.branches) if unit == BRANCH else len(one.forbidden)
        claim = one.branches[index - 1] if unit == BRANCH else one.forbidden[index - 1]
        emit(f"\n  {one.question_id}  {unit} {index} of {count}")

        if unit == BRANCH:
            emit(f"  CLAIM     {claim}")
            first = _ask(prompt, emit, "  Does the ANSWER state this claim?")
            if first.stop:
                stopped = True
                break
            if first.skip:
                skipped += 1
                continue
            supported: bool | None = None
            note = first.note
            if first.verdict:
                second = _ask(
                    prompt, emit, "  Is it supported by the excerpt the ANSWER cites for it?"
                )
                if second.stop:
                    stopped = True
                    break
                if second.skip:
                    # Deferring the second half defers the unit: a branch with
                    # `stated` and no `supported` cannot enter groundedness.
                    skipped += 1
                    continue
                supported = second.verdict
                note = " / ".join(part for part in (note, second.note) if part)
            label = HumanLabel(
                question_id=one.question_id,
                unit=BRANCH,
                index=index,
                stated=first.verdict,
                supported=supported,
                note=note,
            )
        else:
            emit(f"  MUST NOT  {claim}")
            reply = _ask(prompt, emit, "  Does the ANSWER make this claim?")
            if reply.stop:
                stopped = True
                break
            if reply.skip:
                skipped += 1
                continue
            label = HumanLabel(
                question_id=one.question_id,
                unit=FORBIDDEN,
                index=index,
                asserted=reply.verdict,
                note=reply.note,
            )

        labels.append(label)
        labelled += 1
        # Written after EVERY unit. An hour of labelling lost to a closed terminal
        # is an hour that does not get spent a second time.
        write_labels(labels_path, labels, sample=sample_path, commit=sample_commit)

    write_labels(labels_path, labels, sample=sample_path, commit=sample_commit)
    remaining = len(pending(questions, labels))
    emit(
        f"\n{labelled} labelled this session"
        + (f", {skipped} deferred" if skipped else "")
        + f", {len(labels)} in total, {remaining} to go. Saved to {labels_path}."
    )
    if remaining:
        emit("Run the same command again to continue where you stopped.")
    return SessionResult(
        labelled=labelled, skipped=skipped, quit_early=stopped, remaining=remaining
    )


def every_informative_label(questions: Sequence[QuestionToLabel]) -> tuple[HumanLabel, ...]:
    """Placeholder labels covering every informative unit, for self-consistency.

    Judge self-consistency compares the judge against itself, so it needs no human
    -- but `judge_unit_labels` is driven by a label set, because that is what makes
    the compared unit sets identical by construction. This supplies the *shape*
    with `stated: True` throughout, which is exactly the right choice and worth
    saying why: `stated: True` puts every branch's `supported` field in scope, so
    self-consistency is measured over the widest unit set available rather than
    over whichever subset one run happened to call stated.

    It is not a label and nothing here is a judgement. Kept in this module rather
    than the CLI so the reason travels with it.
    """
    out: list[HumanLabel] = []
    for one in informative(questions):
        for index in range(1, len(one.branches) + 1):
            out.append(
                HumanLabel(
                    question_id=one.question_id,
                    unit=BRANCH,
                    index=index,
                    stated=True,
                    supported=True,
                )
            )
        for index in range(1, len(one.forbidden) + 1):
            out.append(
                HumanLabel(question_id=one.question_id, unit=FORBIDDEN, index=index, asserted=False)
            )
    return tuple(out)

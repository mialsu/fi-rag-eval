"""The eval run: golden set + corpus -> outcomes -> metrics.

There is deliberately no skip path. Every question in the golden set produces an
outcome or the run fails, because a metric averaged over a silently reduced N is
the worst output this harness could produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg

from fi_rag_eval import db
from fi_rag_eval.golden import GoldenSet, Question
from fi_rag_eval.manifest import Manifest
from fi_rag_eval.metrics import Metrics, Miss, MissKind, QuestionOutcome, compute

DEFAULT_K = 5


class EvaluationError(RuntimeError):
    """The run could not be completed honestly, so it was not completed at all."""


@dataclass(frozen=True, slots=True)
class QuestionRun:
    """One question's full trace, kept so the table can be read, not just believed."""

    question: Question
    authority_key: str
    effective_date: date
    lexemes: tuple[str, ...]
    hits: tuple[db.Hit, ...]
    outcome: QuestionOutcome


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    k: int
    runs: tuple[QuestionRun, ...]
    metrics: Metrics


def _resolve_labels(conn: psycopg.Connection[tuple[object, ...]], golden: GoldenSet) -> None:
    """Every label must point at a chunk that exists. No exceptions, no skips."""
    wanted = [address for q in golden.questions for address in q.required_addresses]
    present = db.resolve_addresses(conn, wanted)
    missing = sorted(set(wanted) - present)
    if missing:
        detail = "\n".join(
            f"  {q.id}: {address}"
            for q in golden.questions
            for address in q.required_addresses
            if address in set(missing)
        )
        raise EvaluationError(
            "these golden labels do not resolve to a chunk in the corpus:\n"
            f"{detail}\n"
            "An unresolvable label is a hard error, never a skipped question: the "
            "alternative is a metric computed over a smaller N than the table claims."
        )


def evaluate(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    manifest: Manifest,
    golden: GoldenSet,
    k: int = DEFAULT_K,
) -> EvaluationRun:
    if k < 1:
        raise EvaluationError(f"k must be at least 1, got {k}")
    _resolve_labels(conn, golden)

    runs: list[QuestionRun] = []
    for question in golden.questions:
        authority = manifest.resolve_municipality(question.municipality)
        # Slice 1 ingests one document version per authority; when a second
        # arrives the golden entry will have to name which one it labels.
        if len(authority.sources) != 1:
            raise EvaluationError(
                f"{question.id}: authority {authority.key!r} has "
                f"{len(authority.sources)} document versions, so the question must "
                "say which one it is labelled against."
            )
        effective_date = authority.sources[0].effective_date

        lexemes = db.query_lexemes(conn, question.question)
        if not lexemes:
            raise EvaluationError(
                f"{question.id}: the question stems to zero lexemes under the "
                f"{db.TEXT_SEARCH_CONFIG!r} configuration, so it cannot be retrieved "
                "for at all. Fix the question rather than scoring it as a miss."
            )
        tsquery = db.or_tsquery(lexemes)
        hits = db.search(
            conn,
            tsquery=tsquery,
            authority_key=authority.key,
            effective_date=effective_date,
            limit=k,
        )
        retrieved = tuple(hit.address for hit in hits)
        required = set(question.required_addresses)
        missed = sorted(required - set(retrieved))
        reachable = db.addresses_matching(conn, addresses=missed, tsquery=tsquery)
        misses = tuple(
            Miss(
                address=address,
                kind=MissKind.RANKED_OUT if address in reachable else MissKind.ZERO_OVERLAP,
            )
            for address in missed
        )
        runs.append(
            QuestionRun(
                question=question,
                authority_key=authority.key,
                effective_date=effective_date,
                lexemes=tuple(lexemes),
                hits=tuple(hits),
                outcome=QuestionOutcome(
                    question_id=question.id,
                    required=question.required_addresses,
                    retrieved=retrieved,
                    misses=misses,
                ),
            )
        )

    if len(runs) != len(golden.questions):  # pragma: no cover - the loop cannot skip
        raise EvaluationError(
            f"scored {len(runs)} of {len(golden.questions)} questions; refusing to "
            "report a table over a reduced N"
        )
    return EvaluationRun(
        k=k,
        runs=tuple(runs),
        metrics=compute([run.outcome for run in runs], k=k),
    )

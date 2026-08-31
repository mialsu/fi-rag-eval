"""One arbitrary question, answered from the retrieval the harness measures.

Everything else in this package answers a question the golden set already knows.
This module is the first place a question arrives that nobody labelled -- which is
what a *product* is, and until 31 Aug 2026 there was no path to it: `fi-rag-eval
answer` takes a golden question **id**.

Three properties are deliberate and each is asserted rather than intended.

**It reuses the harness's retrieval rather than re-implementing it.** The lexemes
come from `evaluate.cell_query_lexemes` and the search from `db.search`, in the
published cell, with the stopword decision asked of Postgres per word exactly as
`evaluate.question_stopwords` asks it for the whole golden set. A second
retrieval implementation behind a demo surface is the *"two implementations of one
behavior"* anti-pattern aimed at the one thing every published number describes:
the demo would drift from the measurement and both would still look fine.

**It refuses before it spends.** An unknown municipality, a question that
normalises to nothing, and a search that returns no chunk are all refusals that
cost zero -- no model call is made. On a public endpoint that is a spend control,
not a nicety.

**The authority filter is re-asserted after the search.** `db.search` filters in
the WHERE clause, before ranking, so a foreign chunk is never a candidate
(ADR-0002). `assert_one_authority` then checks the rows that actually came back.
Cross-municipality leakage is this project's #1 product failure mode
(`DESIGN.md:15,67`), and **a new surface is exactly where a guard regresses** --
the check costs nothing and the failure it prevents is a resident being told
another municipality's rules with a correct-looking citation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import psycopg

from fi_rag_eval import db
from fi_rag_eval.analyse import Morphology
from fi_rag_eval.answer import ANSWERER, Answer, TokenBudget, answer_question
from fi_rag_eval.evaluate import (
    DEFAULT_K,
    PUBLISHED,
    Cell,
    assert_one_authority,
    cell_query_lexemes,
)
from fi_rag_eval.manifest import Manifest, ManifestError

ASK_ID = "ask"
"""The question id used for an unlabelled question.

Not a hash of the text and not a counter. `answer_question` takes an id only to
put it in its error messages, and anything derived from the question text would
put a stranger's words into a log line -- which `CLAUDE.md`'s "no personal data,
ever" forbids and `DESIGN.md:35`'s structured logging would otherwise invite.
"""


class AskError(RuntimeError):
    """The question cannot be answered, and no model call was made.

    Carries **two** texts, and both are required. `str(exc)` is English and is
    what the CLI prints and what the test suite matches on -- a maintainer's
    message, naming the design decision behind the refusal. `finnish` is the
    sentence a resident reads on the demo page, because `CLAUDE.md`'s definition of
    done requires the copy to be in the user's language and the whole surface is
    otherwise Finnish.

    Required rather than defaulted, so a new raise site cannot forget the half a
    stranger will actually see: mypy names the omission. They sit together at each
    raise site rather than being mapped from a reason code, and nothing has to
    recover a reason by matching on a message -- which this project has already
    confessed once as a defect (`REVIEW-DEBT.md`, the gateway budget).
    """

    def __init__(self, message: str, *, finnish: str) -> None:
        super().__init__(message)
        self.finnish = finnish


class Answerer(Protocol):
    """The one call in this module that costs money, injected so it can be absent.

    Every refusal path here is meant to spend nothing, and "meant to" is not a
    property a test can check while the only implementation reaches the network.
    With the answerer injected, a test passes one that RAISES if called and the
    zero-cost claim becomes an assertion -- which matters more here than anywhere
    else in the package, because this is the surface a stranger can reach.
    """

    def __call__(
        self,
        *,
        question_id: str,
        question: str,
        hits: Sequence[db.Hit],
        bodies: Mapping[str, str],
        budget: TokenBudget,
        model: str = ...,
        reasoning: bool = ...,
    ) -> Answer: ...


@dataclass(frozen=True, slots=True)
class Asked:
    """One answered question, with everything needed to render or audit it."""

    question: str
    municipality: str
    authority_key: str
    authority_name: str
    cell: str
    hits: tuple[db.Hit, ...]
    answer: Answer

    @property
    def refused(self) -> bool:
        return self.answer.refused

    @property
    def cost_usd(self) -> float:
        return self.answer.usage.cost_usd


def municipalities(manifest: Manifest) -> tuple[str, ...]:
    """Every municipality the corpus can answer for, sorted.

    The surface offers a choice from this rather than a free-text field. An
    unknown municipality must refuse (AC14), but a demo whose only failure mode is
    a typo demonstrates the typo.
    """
    return tuple(
        sorted({name for authority in manifest.authorities for name in authority.municipalities})
    )


def ask(
    conn: psycopg.Connection[tuple[object, ...]],
    *,
    manifest: Manifest,
    question: str,
    municipality: str,
    k: int = DEFAULT_K,
    cell: Cell = PUBLISHED,
    morphology: Morphology | None = None,
    model: str = ANSWERER,
    reasoning: bool = True,
    budget: TokenBudget | None = None,
    answerer: Answerer = answer_question,
) -> Asked:
    """Answer one unlabelled question inside one municipality's jurisdiction."""
    text = question.strip()
    if not text:
        raise AskError(
            "no question was asked",
            finnish="Kysymys puuttuu. Kirjoita kysymys omin sanoin.",
        )

    # Resolved FIRST, so an unknown or absent municipality costs nothing. The
    # harness must never pick one on the asker's behalf: with no jurisdiction
    # there is no authority whose rules an answer could come from.
    try:
        authority = manifest.resolve_municipality(municipality)
    except ManifestError as exc:
        # `resolve_municipality` supplies its own Finnish for all four of its
        # refusals; the fallback covers a manifest error that is really a
        # maintainer's problem and should never reach a resident at all.
        raise AskError(
            str(exc),
            finnish=exc.finnish or "Kuntaa ei voitu ratkaista, joten vastausta ei haettu.",
        ) from exc
    if len(authority.sources) != 1:
        raise AskError(
            f"authority {authority.key!r} has {len(authority.sources)} document versions, "
            "so a question must say which edition it is asked against.",
            finnish=(
                "Tämän viranomaisen määräyksistä on aineistossa useampi voimassa ollut "
                "versio, joten kysymyksessä olisi kerrottava, mitä versiota se koskee."
            ),
        )
    effective_date = authority.sources[0].effective_date

    if cell.analyser.lemmatising and morphology is None:
        morphology = Morphology.open()
    stopwords = (
        db.snowball_stopwords(conn, morphology.words(text))
        if cell.analyser.lemmatising and morphology is not None
        else frozenset()
    )
    lexemes = cell_query_lexemes(conn, text, cell, morphology=morphology, stopwords=stopwords)
    if not lexemes:
        raise AskError(
            "that question normalises to no searchable words, so there is nothing to "
            "retrieve. Try naming the thing you are asking about.",
            finnish=(
                "Kysymyksestä ei löytynyt yhtään hakusanaa, joten haettavaa ei ole. "
                "Nimeä se asia, jota kysymys koskee -- esimerkiksi jäteastia, "
                "biojäte tai tyhjennysväli."
            ),
        )

    hits = db.search(
        conn,
        tsquery=db.or_tsquery(lexemes),
        authority_key=authority.key,
        effective_date=effective_date,
        limit=k,
        analyser=cell.analyser,
        normalisation=cell.normalisation,
    )
    if not hits:
        raise AskError(
            f"nothing in {authority.name}'s regulations matched that question, so there "
            "is no context to answer from. This is a refusal, not an error.",
            # The authority's name is NOT inflected. `f"{name}n"` produced
            # "jätehuoltolautakuntan" on the first live run -- the genitive of
            # `lautakunta` is `lautakunnan`, consonant gradation and all. Guessing
            # Finnish inflection is exactly what this project uses voikko for, and
            # a demo is not the place to hand-roll a second morphology. So the name
            # stays in the nominative, in parentheses.
            finnish=(
                "Näissä jätehuoltomääräyksissä ei ole kohtaa, joka vastaisi tätä "
                "kysymystä. Tämä on kieltäytyminen, ei virhe."
            ),
        )
    assert_one_authority(hits, authority.key, ASK_ID)

    addresses = {hit.address for hit in hits}
    bodies = {address: body for address, body in db.chunk_bodies(conn) if address in addresses}
    answer = answerer(
        question_id=ASK_ID,
        question=text,
        hits=hits,
        bodies=bodies,
        budget=budget if budget is not None else TokenBudget(),
        model=model,
        reasoning=reasoning,
    )
    return Asked(
        question=text,
        municipality=municipality,
        authority_key=authority.key,
        authority_name=authority.name,
        cell=cell.name,
        hits=tuple(hits),
        answer=answer,
    )

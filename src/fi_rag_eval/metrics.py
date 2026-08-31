"""Retrieval metrics. Arithmetic only -- no model is involved anywhere here.

That is deliberate and it is why these are the numbers to trust most: when the
retrieval layer and a later judge disagree, these win the argument.

The headline is **complete-set recall@k** (ADR-0003): binary per question, did
the top k contain *every* chunk the answer depends on. Per-chunk recall and MRR
are diagnostics. Per-chunk recall awards partial credit for a retrieval that
produces a confidently wrong answer -- missing the composting exemption scores
0.67 and reads as "mostly fine" while the system tells a composting household to
buy a bin -- so it must never be the headline.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class MetricsError(ValueError):
    """A metric was asked for over a question set that cannot support it."""


class MissKind(StrEnum):
    """Why a required chunk was not retrieved. This is what decides slice 3."""

    ZERO_OVERLAP = "zero-overlap"
    """Shares no stemmed token with the query: unreachable. Morphology failure."""

    RANKED_OUT = "ranked-out"
    """Matched the query but ranked below k. Ranking failure -- IDF territory."""


@dataclass(frozen=True, slots=True)
class Miss:
    address: str
    kind: MissKind


@dataclass(frozen=True, slots=True)
class QuestionOutcome:
    """One question's retrieval result, with every miss classified."""

    question_id: str
    required: tuple[str, ...]
    retrieved: tuple[str, ...]
    """Top-k addresses, in rank order."""
    misses: tuple[Miss, ...]
    query_lexemes: tuple[str, ...] = ()
    """The question's stemmed content words, as the index would see them."""
    leaked_lexemes: tuple[str, ...] = ()
    """The subset of those already present in the question's own target chunks."""

    def __post_init__(self) -> None:
        if not self.required:
            raise MetricsError(
                f"{self.question_id}: no required chunks. A question with nothing to "
                "retrieve would score a vacuous 1.0 and inflate the headline; refusal "
                "cases arrive with the answering slice, where they can be scored."
            )
        if not set(self.leaked_lexemes) <= set(self.query_lexemes):
            raise MetricsError(
                f"{self.question_id}: leaked lexemes must be a subset of the query's; "
                f"{sorted(set(self.leaked_lexemes) - set(self.query_lexemes))} is not."
            )
        missed = {miss.address for miss in self.misses}
        found = set(self.required) & set(self.retrieved)
        if missed | found != set(self.required):
            raise MetricsError(
                f"{self.question_id}: every required chunk must be either retrieved or "
                f"classified as a miss; {sorted(set(self.required) - (missed | found))} "
                "is neither."
            )

    @property
    def found(self) -> tuple[str, ...]:
        return tuple(a for a in self.retrieved if a in set(self.required))

    @property
    def complete(self) -> bool:
        return set(self.required) <= set(self.retrieved)

    @property
    def lexical_leakage(self) -> float | None:
        """Share of this question's stemmed words that its target chunks contain.

        ``None`` when the question stemmed to nothing measurable, so a missing
        value is never silently averaged in as a zero.
        """
        if not self.query_lexemes:
            return None
        return len(self.leaked_lexemes) / len(self.query_lexemes)

    @property
    def reciprocal_rank(self) -> float:
        for position, address in enumerate(self.retrieved, start=1):
            if address in set(self.required):
                return 1.0 / position
        return 0.0


@dataclass(frozen=True, slots=True)
class Metrics:
    k: int
    questions: int
    required_chunks: int
    complete_set_recall: float
    per_chunk_recall: float
    mean_reciprocal_rank: float
    misses_zero_overlap: int
    misses_ranked_out: int
    lexical_leakage: float
    """How much of the golden set's own vocabulary is handed to it by its targets.

    Not a retrieval metric -- a metric *of the golden set*, reported beside the
    others because the headline is uninterpretable without it. High leakage means
    the questions were written from the source text, so the harness is easier
    than the task and cannot see the vocabulary gap it exists to measure. It is
    a diagnostic, not a target to drive to zero: a resident asking about
    bio-waste will say "biojäte" because that is what it is called. The reference
    point is the leakage of real questions harvested from the authority's own
    resident-facing pages.
    """
    leakage_lexemes: int
    """Denominator for the above: total stemmed question words considered."""

    @property
    def misses(self) -> int:
        return self.misses_zero_overlap + self.misses_ranked_out


def compute(outcomes: Sequence[QuestionOutcome], *, k: int) -> Metrics:
    """Compute the metric set over every outcome. Never over a subset.

    A metric averaged over a silently reduced N is this harness's worst possible
    output, so the caller is required to hand over one outcome per golden-set
    question; there is no skip path.
    """
    if not outcomes:
        raise MetricsError("refusing to compute metrics over zero questions")
    if k < 1:
        raise MetricsError(f"k must be at least 1, got {k}")
    intruders = sorted({type(o).__name__ for o in outcomes if not isinstance(o, QuestionOutcome)})
    if intruders:
        raise MetricsError(
            f"refusing to compute retrieval metrics over {intruders}. "
            "Only the answerable population has required chunks; a refusal question "
            "pooled in here would contribute a vacuous 1.0 to complete-set recall and "
            "move the published headline for a reason nobody chose. The two populations "
            "are separate types precisely so this cannot happen by accident."
        )

    ids = [outcome.question_id for outcome in outcomes]
    if len(set(ids)) != len(ids):
        raise MetricsError("outcomes contain duplicate question ids")

    required_total = sum(len(outcome.required) for outcome in outcomes)
    found_total = sum(len(outcome.found) for outcome in outcomes)
    complete = sum(1 for outcome in outcomes if outcome.complete)
    misses = [miss for outcome in outcomes for miss in outcome.misses]

    lexemes_total = sum(len(outcome.query_lexemes) for outcome in outcomes)
    leaked_total = sum(len(outcome.leaked_lexemes) for outcome in outcomes)

    return Metrics(
        k=k,
        questions=len(outcomes),
        required_chunks=required_total,
        complete_set_recall=complete / len(outcomes),
        per_chunk_recall=found_total / required_total,
        mean_reciprocal_rank=sum(o.reciprocal_rank for o in outcomes) / len(outcomes),
        misses_zero_overlap=sum(1 for m in misses if m.kind is MissKind.ZERO_OVERLAP),
        misses_ranked_out=sum(1 for m in misses if m.kind is MissKind.RANKED_OUT),
        lexical_leakage=leaked_total / lexemes_total if lexemes_total else 0.0,
        leakage_lexemes=lexemes_total,
    )


@dataclass(frozen=True, slots=True)
class Discordance:
    """How two cells disagree question by question, and whether that can register.

    Two cells are scored on the **same** questions, so comparing them is a
    *paired* test and the absolute-difference interval is the wrong instrument.
    Only the questions where the two disagree carry information: `a_only` passed
    in the first cell and failed in the second, `b_only` the reverse. Questions
    both cells pass, or both fail, tell you nothing about which is better.

    This is why slice 4 exists. At N=21 the best cell has three failures, so
    fixing *every remaining miss* yields three discordant questions and p=0.25 --
    there was no result the vector layer could have produced that would register
    at all. Reported per run so a reader is never left to assume a small delta
    means something.
    """

    a_only: int
    """Passed in cell A, failed in cell B."""

    b_only: int
    """Failed in cell A, passed in cell B."""

    @property
    def discordant(self) -> int:
        """``d``: how many questions the two cells disagree about."""
        return self.a_only + self.b_only

    @property
    def p_value(self) -> float:
        """Exact two-sided McNemar p: a binomial sign test over the discordant pairs.

        Under the null the two cells are equally good, so each discordant question
        is a fair coin. No normal approximation and no continuity correction --
        both are unusable at this N, which is the whole point of reporting it.

        With every discordant question flipping the same way this reduces to
        ``2 x 0.5^d``: d=5 gives 0.062 and d=6 gives 0.031, so **six questions
        must flip for a paired win at p<0.05.**
        """
        n = self.discordant
        if n == 0:
            return 1.0
        tail = sum(math.comb(n, i) for i in range(min(self.a_only, self.b_only) + 1))
        return min(1.0, float(2.0 * tail / 2**n))


def discordance(a: Sequence[QuestionOutcome], b: Sequence[QuestionOutcome]) -> Discordance:
    """Compare two cells' outcomes over the same questions, in the same order.

    Requires the same question ids in the same order: a paired test over two
    different populations is not a paired test, and silently zipping mismatched
    lists is how that mistake would be made.
    """
    if len(a) != len(b):
        raise MetricsError(
            f"cannot pair {len(a)} outcomes against {len(b)}: a paired test needs the "
            "same questions on both sides"
        )
    mismatched = [
        (left.question_id, right.question_id)
        for left, right in zip(a, b, strict=True)
        if left.question_id != right.question_id
    ]
    if mismatched:
        raise MetricsError(
            f"outcomes are not in the same question order: {mismatched[:3]}. Pairing "
            "two cells on position requires they scored the same set, in order."
        )
    return Discordance(
        a_only=sum(1 for x, y in zip(a, b, strict=True) if x.complete and not y.complete),
        b_only=sum(1 for x, y in zip(a, b, strict=True) if y.complete and not x.complete),
    )


# ---------------------------------------------------------------------------
# The refusal population (slice 5, tracer 3)
#
# Kept in this module because it is arithmetic and no model is involved, which is
# what makes it trustworthy for the same reason recall@k is. The judge scores
# groundedness; nothing here needs one.
# ---------------------------------------------------------------------------


class RefusalKind(StrEnum):
    """Mirrors `golden.RefusalKind` so metrics never import the golden set.

    Two enums for one concept would normally be the "two formats for one artifact"
    anti-pattern. This one is deliberate and narrow: `metrics` is the layer with
    no dependencies -- it knows about outcomes, not about YAML, manifests or
    corpora -- and the boundary test pins the two vocabularies equal, so they
    cannot drift silently.
    """

    OUT_OF_CORPUS = "out-of-corpus"
    OUT_OF_JURISDICTION = "out-of-jurisdiction"


@dataclass(frozen=True, slots=True)
class RefusalOutcome:
    """What the answerer did with one question that should have been refused."""

    question_id: str
    kind: RefusalKind
    refused: bool
    """Read from the envelope's `refused` field, never string-matched from prose."""

    citations: tuple[str, ...] = ()
    """As emitted, unvalidated. Checked against `retrieved` below, never raised on."""

    retrieved: tuple[str, ...] = ()
    """The top-k addresses this question was actually given.

    Present so a refusal's citations can be checked against the context the
    refusal is a statement *about*. Without it the only available check is "did it
    cite anything", which ADR-0010 narrowed away for being the wrong question.
    """


@dataclass(frozen=True, slots=True)
class AnswerOutcome:
    """What the answerer did with one question that *was* answerable.

    Present in this module for exactly one reason: refusal **precision** cannot be
    computed without it. Its denominator is every refusal the system emitted, and
    the wrong ones are emitted over here.
    """

    question_id: str
    refused: bool


@dataclass(frozen=True, slots=True)
class Interval:
    """A Wilson score interval for a proportion, and the n it was computed at.

    Wilson rather than Wald because Wald is unusable at these counts: at 13
    questions it runs past 0 and 1, and at a perfect 13/13 it reports a width of
    zero, which would publish certainty this population cannot buy.

    **This corrects D5.** The spec quotes "±0.13" for refusal recall at R=14 -- the
    population was 14 when D5 was written and is 13 since 31 Aug 2026 -- which
    is one standard error (sqrt(0.25/14) = 0.134), not an interval. The 95%
    interval at 7/14 is roughly [0.25, 0.75]. This project has already been burned
    once by an interval that was the wrong statistic -- the ±0.18 slice 3 used --
    so the number is computed here and the spec is corrected rather than quoted.
    """

    point: float
    low: float
    high: float
    n: int

    def render(self) -> str:
        return f"{self.point:.3f} [{self.low:.2f}, {self.high:.2f}] n={self.n}"


def wilson(successes: int, n: int, *, z: float = 1.959963985) -> Interval:
    """The 95% Wilson score interval. Pure arithmetic, no approximation warnings."""
    if n <= 0:
        raise MetricsError("refusing to compute an interval over zero observations")
    if not 0 <= successes <= n:
        raise MetricsError(f"{successes} successes out of {n} is not a proportion")
    p = successes / n
    denominator = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denominator
    spread = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominator
    return Interval(
        point=p,
        low=max(0.0, centre - spread),
        high=min(1.0, centre + spread),
        n=n,
    )


@dataclass(frozen=True, slots=True)
class RefusalMetrics:
    """Refusal behaviour, computed with no judge and no network.

    Recall is reported **with its interval inline and never as a headline** (D5).
    Fourteen questions cannot support a published figure; what they can support is
    a floor and a direction, and the per-kind split is the part that carries the
    information -- out-of-corpus is the easy refusal and out-of-jurisdiction is the
    one the hard filter's debt turns on.
    """

    recall: Interval
    """Correct refusals over the refusal population. The diagnostic."""

    precision: Interval
    """Correct refusals over every refusal the system emitted, both populations.

    This is the metric that punishes cowardice at the population level: an
    answerer that refuses everything scores a perfect recall and a precision of
    14/64. Branch coverage does the same job question by question.
    """

    by_kind: tuple[tuple[RefusalKind, Interval], ...]
    """Prediction 3 lives here: out-of-corpus >= 7/8 against out-of-jurisdiction <= 4/6."""

    wrongly_refused: tuple[str, ...]
    """Answerable questions the system declined. Named, not just counted."""

    missed: tuple[str, ...]
    """Refusal questions the system answered anyway. Named, not just counted."""

    refusals_citing_context: tuple[str, ...]
    """Refusals that cited a chunk they were actually given. **Not a defect.**

    This replaces `refusals_with_citations`, and the replacement is ADR-0010's,
    made on measured evidence rather than taste. The old rule -- *any* citation on
    a refusal is a defect -- fired twice in tracer slice 3, and both times the
    citation was used for *"here is what the excerpts do say instead"*: Pirkanmaa
    `7 §` on when kerbside collection is possible, Lounais-Suomi `1 §` on scope.
    Under this project's own definition of Citation (`CONTEXT.md:40`, "a pointer
    from a claim in the answer to the chunk that supports it") both are **correct**
    -- the claims they support are simply not answers to the question.

    So the rule punished the better refusal. *"The excerpts only cover X `[#7]`,
    not your question"* is more useful **and more auditable** than a bare "I do not
    know", and labelling it a defect pressures the answerer toward output nobody
    can check. Counted and named here because the count is worth watching; neither
    direction is wrong.
    """

    refusals_citing_outside: tuple[str, ...]
    """Refusals that cited an address they were **not** given. A defect.

    What survives of the old rule, and the half that was always unambiguous: a
    refusal asserts that the retrieved context does not answer the question, so
    pointing outside that context while saying so is wrong however the address got
    there -- hallucinated, or belonging to another authority.

    Membership is string equality against `RefusalOutcome.retrieved`, which is why
    this module still imports nothing: a hallucinated address and a foreign one are
    both simply "not in the set", and parsing would add no verdict.
    """


def refusal_metrics(
    *,
    refusals: Sequence[RefusalOutcome],
    answerable: Sequence[AnswerOutcome],
) -> RefusalMetrics:
    """Score the refusal population against the answerable one.

    Two separately-typed arguments rather than one pooled sequence, and that is
    the enforcement `metrics.py` was asked for: there is no argument you can pass
    that mixes them, because the wrong type in either slot is rejected here and by
    mypy before that. Precision genuinely needs both populations -- refusals are
    emitted over all 64 questions -- so the two are *used* together and never
    *merged*.
    """
    if not refusals:
        raise MetricsError("refusing to compute refusal metrics over zero refusal questions")
    if not answerable:
        raise MetricsError(
            "refusal precision needs the answerable population too: its denominator is "
            "every refusal the system emitted, and the wrong ones are emitted there. "
            "Computing it over the refusal population alone would report a vacuous 1.0."
        )
    misplaced = [o for o in refusals if not isinstance(o, RefusalOutcome)]
    misplaced += [o for o in answerable if not isinstance(o, AnswerOutcome)]  # type: ignore[misc]
    if misplaced:
        raise MetricsError(
            f"refusing to pool populations: {sorted({type(o).__name__ for o in misplaced})} "
            "was passed where the other population was expected. A question is either "
            "answerable or a refusal case, and one scored as the other silently changes "
            "both metrics."
        )
    ids = [o.question_id for o in refusals] + [o.question_id for o in answerable]
    if len(set(ids)) != len(ids):
        raise MetricsError(
            "the same question id appears in both populations, or twice in one. An id is "
            "how a verdict is attached to a question; a collision attaches it to two."
        )

    correct = [o for o in refusals if o.refused]
    wrongly_refused = tuple(o.question_id for o in answerable if o.refused)
    emitted = len(correct) + len(wrongly_refused)

    by_kind: list[tuple[RefusalKind, Interval]] = []
    for kind in RefusalKind:
        population = [o for o in refusals if o.kind is kind]
        if population:
            by_kind.append((kind, wilson(sum(1 for o in population if o.refused), len(population))))

    return RefusalMetrics(
        recall=wilson(len(correct), len(refusals)),
        # An answerer that never refuses has no precision rather than a zero: 0/0
        # is undefined, and reporting it as 0.0 would read as "every refusal it
        # emitted was wrong" when it emitted none.
        precision=wilson(len(correct), emitted) if emitted else Interval(0.0, 0.0, 1.0, 0),
        by_kind=tuple(by_kind),
        wrongly_refused=wrongly_refused,
        missed=tuple(o.question_id for o in refusals if not o.refused),
        refusals_citing_context=tuple(
            o.question_id for o in correct if set(o.citations) & set(o.retrieved)
        ),
        refusals_citing_outside=tuple(
            o.question_id for o in correct if set(o.citations) - set(o.retrieved)
        ),
    )


# ---------------------------------------------------------------------------
# The judged metrics (slice 5, tracer 4)
#
# Still arithmetic, and still no model in this module: the judge's per-unit
# verdicts arrive as data from `judge.py` and are counted here. That separation is
# the point. Groundedness is a ratio of two integers; what is judge-dependent is
# where those integers came from, and keeping the arithmetic here means it can be
# tested exhaustively with no network and no spend.
#
# The denominators are `CONTEXT.md:44,46,47` and were settled on 27 Aug 2026 after
# that file contradicted itself for a day. They are not re-litigated here:
#   groundedness   = supported / branches STATED
#   branch coverage = stated    / branches REQUIRED
#   over-claim      = answers asserting a forbidden claim / answers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BranchVerdict:
    """The judge's reading of one required branch. One of the 125."""

    index: int
    """Which branch of this question's `required_branches`, 1-based."""

    stated: bool
    """Does the answer assert this branch at all? Feeds branch coverage."""

    supported: bool
    """Is the branch, as stated, carried by the chunk the answer attached to it?

    Only meaningful when `stated`. A branch the answer never made cannot be
    supported or unsupported, which is enforced below rather than documented.
    """

    quote: str
    """The words from the answer the judge says state this branch.

    Required when `stated`, and **verified as a substring of the answer text** by
    `judge.py` before it reaches here. A judge that claims a branch is stated and
    cannot quote the text saying so is caught by arithmetic, with no human in the
    loop -- which is the cheapest validation this project gets and it is worth
    more than it costs.
    """

    quote_found: bool
    """Whether the quote appears in the answer as a contiguous span."""

    quote_words_present: float = 1.0
    """Share of the quote's words that appear in the answer at all.

    **This exists because the contiguity check alone overstates the problem, and
    that was measured rather than reasoned about.** The first full run flagged 9 of
    50 answers, and the first one inspected turned out to be a *splice*: the judge
    had joined `- Biojäte:` from the head of a bullet to a sentence three clauses
    later, so every word was in the answer and the claim genuinely was stated. That
    is sloppy quoting, not invention.

    At 1.0 the judge only re-assembled words the answer contains -- the claim is
    there and the citation of it is untidy. Below 1.0 the judge used words the
    answer does not have, which is the failure that matters: agreeing a claim is
    present because it ought to be. Reported apart, because one count for both
    would be a number that overstates.
    """

    def __post_init__(self) -> None:
        if self.index < 1:
            raise MetricsError(f"branch index is 1-based, got {self.index}")
        if not 0.0 <= self.quote_words_present <= 1.0:
            raise MetricsError(
                f"branch {self.index}: quote_words_present is a share, got "
                f"{self.quote_words_present}"
            )
        if self.supported and not self.stated:
            raise MetricsError(
                f"branch {self.index}: supported={self.supported} with stated=False. A "
                "branch the answer never made cannot be supported; groundedness' "
                "denominator is branches STATED, so this would inflate it above 1.0."
            )
        if self.stated and not self.quote:
            raise MetricsError(
                f"branch {self.index}: stated with no quote. The quote is what makes "
                "`stated` checkable without re-reading the answer, and its absence is "
                "how a judge asserts a branch it cannot point at."
            )


@dataclass(frozen=True, slots=True)
class ForbiddenVerdict:
    """The judge's reading of one forbidden claim. One of the 74."""

    index: int
    asserted: bool
    """Did the answer make the claim it must not make?"""

    quote: str
    quote_found: bool
    quote_words_present: float = 1.0
    """See `BranchVerdict.quote_words_present`. Splice against invention."""

    def __post_init__(self) -> None:
        if self.index < 1:
            raise MetricsError(f"forbidden index is 1-based, got {self.index}")
        if not 0.0 <= self.quote_words_present <= 1.0:
            raise MetricsError(
                f"forbidden {self.index}: quote_words_present is a share, got "
                f"{self.quote_words_present}"
            )
        if self.asserted and not self.quote:
            raise MetricsError(
                f"forbidden {self.index}: asserted with no quote. An over-claim nobody "
                "can point at is the judge's opinion, not a measurement."
            )


@dataclass(frozen=True, slots=True)
class JudgedAnswer:
    """One answer, judged unit by unit.

    Carries `refused` because a refused answerable question is not an absence of
    data: it states nothing, so it scores **0 on branch coverage** and drops out
    of groundedness' denominator entirely. That asymmetry is deliberate (D11) --
    cowardice is punished by branch coverage, not by distorting groundedness into
    something it cannot compute.
    """

    question_id: str
    refused: bool
    required_branches: int
    """How many branches the golden entry requires. The coverage denominator."""

    branches: tuple[BranchVerdict, ...]
    forbidden: tuple[ForbiddenVerdict, ...]

    def __post_init__(self) -> None:
        if len(self.branches) != self.required_branches:
            raise MetricsError(
                f"{self.question_id}: {len(self.branches)} branch verdicts for "
                f"{self.required_branches} required branches. Every unit is judged or "
                "the metric is computed over a silently reduced N, which is the one "
                "output this project says destroys it."
            )
        indexes = [b.index for b in self.branches]
        if sorted(indexes) != list(range(1, len(indexes) + 1)):
            raise MetricsError(
                f"{self.question_id}: branch verdicts are indexed {sorted(indexes)}, "
                f"expected 1..{len(indexes)}. An index is how a verdict is attached to a "
                "hand-written claim; a gap attaches it to the wrong one."
            )
        forbidden_indexes = [f.index for f in self.forbidden]
        if sorted(forbidden_indexes) != list(range(1, len(forbidden_indexes) + 1)):
            raise MetricsError(
                f"{self.question_id}: forbidden verdicts are indexed "
                f"{sorted(forbidden_indexes)}, expected 1..{len(forbidden_indexes)}"
            )
        if self.refused and any(b.stated for b in self.branches):
            raise MetricsError(
                f"{self.question_id}: refused, yet the judge says a branch is stated. "
                "One of the two is wrong and neither is safe to average."
            )

    @property
    def stated(self) -> int:
        return sum(1 for b in self.branches if b.stated)

    @property
    def supported(self) -> int:
        return sum(1 for b in self.branches if b.supported)

    @property
    def over_claims(self) -> int:
        return sum(1 for f in self.forbidden if f.asserted)

    @property
    def units(self) -> int:
        """Judged units this answer contributes to the 199."""
        return len(self.branches) + len(self.forbidden)


@dataclass(frozen=True, slots=True)
class JudgedMetrics:
    """The answer layer's judged numbers. **Publishable only with agreement.**

    Nothing in this dataclass knows whether it may be published; that is D11's
    rule and it is enforced where the table is rendered, because a metric object
    that silently withholds its own value is harder to test than one that carries
    it and is refused a headline.
    """

    answers: int
    refused: int
    units: int
    """Branch + forbidden verdicts. 199 over the full golden set."""

    branches_required: int
    branches_stated: int
    branches_supported: int
    forbidden_items: int
    forbidden_asserted: int
    answers_over_claiming: tuple[str, ...]
    judge_fabrications: tuple[str, ...]
    """Answers where the judge's quote uses words the answer does not contain.

    A fact about the **judge**, not the answerer, and the only self-check this
    layer has before judge-human agreement exists. Kept strictly separate from
    `judge_splices`: this is the judge asserting a claim it cannot point at, which
    is the failure that would corrupt a metric.
    """

    judge_splices: tuple[str, ...]
    """Answers where the quote is not contiguous but every word of it is present.

    Untidy, not wrong. The judge joined fragments from different parts of the
    answer; the claim really is stated. Counted because a rising splice rate would
    say the quote instruction is being read loosely, and reported apart because
    pooling it with a fabrication would inflate the number that matters.
    """

    @property
    def groundedness(self) -> float | None:
        """Supported / branches STATED. `None` when the answer set stated nothing.

        Gameable by saying less -- an answer stating one well-supported branch of
        five scores 1.0 -- which is why `CONTEXT.md:47` forbids it appearing
        without branch coverage beside it.
        """
        if not self.branches_stated:
            return None
        return self.branches_supported / self.branches_stated

    @property
    def branch_coverage(self) -> float:
        """Stated / branches REQUIRED. The companion that punishes saying less."""
        if not self.branches_required:
            raise MetricsError("no required branches, so there is no coverage to compute")
        return self.branches_stated / self.branches_required

    @property
    def over_claim_rate(self) -> float:
        """Share of ANSWERS asserting at least one forbidden claim (`CONTEXT.md:46`).

        Per answer rather than per item, because the definition is per answer. The
        per-item figure is carried above as a diagnostic: one answer flattening
        three conditionals and three answers flattening one each are the same
        item count and different defects.
        """
        if not self.answers:
            raise MetricsError("no answers, so there is no over-claim rate to compute")
        return len(self.answers_over_claiming) / self.answers


def judged_metrics(judged: Sequence[JudgedAnswer]) -> JudgedMetrics:
    """Count the judge's verdicts. No model, no network, no floor.

    Pooled over **units** rather than averaged over answers, matching D3's power
    arithmetic. The honesty cost is stated in D3 and not hidden here: units
    cluster within an answer, so the effective N is below the unit count and any
    interval over these numbers must be cluster-aware. This function deliberately
    computes no interval, so that nobody gets a naive binomial one for free.
    """
    if not judged:
        raise MetricsError("refusing to compute judged metrics over zero answers")
    ids = [one.question_id for one in judged]
    if len(set(ids)) != len(ids):
        raise MetricsError(
            f"the same question is judged twice: {sorted({i for i in ids if ids.count(i) > 1})}"
        )
    return JudgedMetrics(
        answers=len(judged),
        refused=sum(1 for one in judged if one.refused),
        units=sum(one.units for one in judged),
        branches_required=sum(one.required_branches for one in judged),
        branches_stated=sum(one.stated for one in judged),
        branches_supported=sum(one.supported for one in judged),
        forbidden_items=sum(len(one.forbidden) for one in judged),
        forbidden_asserted=sum(one.over_claims for one in judged),
        answers_over_claiming=tuple(one.question_id for one in judged if one.over_claims),
        judge_fabrications=tuple(
            one.question_id
            for one in judged
            if any(
                not v.quote_found and v.quote_words_present < 1.0 for v in one.branches if v.stated
            )
            or any(
                not v.quote_found and v.quote_words_present < 1.0
                for v in one.forbidden
                if v.asserted
            )
        ),
        judge_splices=tuple(
            one.question_id
            for one in judged
            if any(
                not v.quote_found and v.quote_words_present >= 1.0 for v in one.branches if v.stated
            )
            or any(
                not v.quote_found and v.quote_words_present >= 1.0
                for v in one.forbidden
                if v.asserted
            )
        ),
    )


# ---------------------------------------------------------------------------
# Unit-level agreement, and the cluster-aware interval D3 demands
#
# Written for judge-human agreement (tracer slice 5) and used first for judge
# SELF-consistency (tracer slice 4), because the arithmetic is identical: two sets
# of per-unit labels over the same questions, counted where they differ. Building
# it twice would be "rebuilding what you already have" aimed at the statistics.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnitLabel:
    """One verdict about one unit, by whoever made it -- a judge or a human."""

    question_id: str
    unit: str
    """`branch` or `forbidden`. Kept as a string so this module still imports nothing."""

    index: int
    field: str
    """`stated`, `supported` or `asserted`."""

    value: bool

    @property
    def key(self) -> tuple[str, str, int, str]:
        return (self.question_id, self.unit, self.index, self.field)


@dataclass(frozen=True, slots=True)
class Agreement:
    """How often two label sets say the same thing, with a cluster-aware interval.

    **The interval is clustered by question, and D3 requires that rather than
    preferring it.** Units are not independent: one bad answer fails several
    branches at once, so a naive binomial interval over ~199 units would report a
    precision the data cannot support -- the same class of error as the +/-0.18
    that slice 3 retracted and the +/-0.13 that D5 got wrong.
    """

    units: int
    agreed: int
    clusters: int
    """Questions contributing at least one unit. The effective sample size is nearer this."""

    low: float
    high: float
    interval_kind: str
    """`cluster-robust`, or `wilson-over-clusters` at a degenerate boundary."""

    disagreements: tuple[UnitLabel, ...]
    """The first set's label wherever the two differ. Named, not just counted."""

    by_field: tuple[tuple[str, int, int], ...]
    """`(field, agreed, units)` -- prediction 2 lives here.

    D5's prediction 2 is that agreement on `forbidden` items is *lower* than on
    required claims, and that if over-claim agreement is the *higher* of the two
    the judge prompt is probably collapsing the two questions into one. That
    comparison needs the split, so the split is computed rather than left to a
    later ad-hoc script.
    """

    @property
    def rate(self) -> float:
        return self.agreed / self.units

    def render(self) -> str:
        return (
            f"{self.rate:.3f} [{self.low:.2f}, {self.high:.2f}] "
            f"{self.units} units in {self.clusters} questions ({self.interval_kind})"
        )


def cluster_robust_interval(
    per_cluster: Sequence[tuple[int, int]], *, z: float = 1.959963985
) -> tuple[float, float, str]:
    """A 95% interval for a proportion whose observations cluster.

    `per_cluster` is `(agreed, units)` per cluster. Taylor-linearised ratio
    estimator, which is the standard cluster-robust variance for exactly this
    shape:

        Var(p) = m / ((m - 1) * N^2) * SUM_i (a_i - p * n_i)^2

    **The one thing this estimator cannot do is the boundary**, and saying so is
    the point of the `interval_kind` it returns. When every cluster agrees
    perfectly the variance is exactly zero and the interval collapses to
    `[1, 1]` -- certainty that a few dozen questions cannot buy, which is the
    failure Wilson was adopted to avoid in `wilson()` above. So at zero variance
    this falls back to a Wilson interval over the **cluster count**, the most
    conservative honest reading: m independent questions that all agreed.
    """
    if len(per_cluster) < 2:
        raise MetricsError(
            "a cluster-robust interval needs at least two clusters; with one question "
            "there is nothing to estimate between-question variance from"
        )
    total = sum(units for _, units in per_cluster)
    if total <= 0:
        raise MetricsError("refusing to compute an interval over zero units")
    agreed = sum(count for count, _ in per_cluster)
    point = agreed / total
    m = len(per_cluster)
    residuals = sum((count - point * units) ** 2 for count, units in per_cluster)
    variance = m / ((m - 1) * total**2) * residuals
    if variance <= 0:
        fallback = wilson(sum(1 for count, units in per_cluster if count == units), m, z=z)
        return fallback.low, fallback.high, "wilson-over-clusters"
    spread = z * math.sqrt(variance)
    return max(0.0, point - spread), min(1.0, point + spread), "cluster-robust"


def unit_agreement(first: Sequence[UnitLabel], second: Sequence[UnitLabel]) -> Agreement:
    """Compare two per-unit label sets over the same units.

    Both sets must cover exactly the same units. That is a hard requirement rather
    than an intersection: silently comparing the overlap would compute agreement
    over whichever units both happened to cover, which is a reduced N arrived at
    by accident.
    """
    if not first or not second:
        raise MetricsError("refusing to compute agreement over an empty label set")
    left = {label.key: label for label in first}
    right = {label.key: label for label in second}
    if len(left) != len(first) or len(right) != len(second):
        raise MetricsError("a label set contains the same unit twice")
    only_left = sorted(left.keys() - right.keys())
    only_right = sorted(right.keys() - left.keys())
    if only_left or only_right:
        raise MetricsError(
            f"the two label sets do not cover the same units: {len(only_left)} only in the "
            f"first (e.g. {only_left[:2]}), {len(only_right)} only in the second (e.g. "
            f"{only_right[:2]}). Comparing the overlap would compute agreement over a "
            "reduced N nobody chose."
        )

    clusters: dict[str, list[int]] = {}
    disagreements: list[UnitLabel] = []
    fields: dict[str, list[int]] = {}
    for key, label in left.items():
        same = int(label.value == right[key].value)
        clusters.setdefault(label.question_id, []).append(same)
        fields.setdefault(label.field, []).append(same)
        if not same:
            disagreements.append(label)

    per_cluster = [(sum(marks), len(marks)) for marks in clusters.values()]
    low, high, kind = cluster_robust_interval(per_cluster)
    return Agreement(
        units=len(left),
        agreed=sum(count for count, _ in per_cluster),
        clusters=len(clusters),
        low=low,
        high=high,
        interval_kind=kind,
        disagreements=tuple(sorted(disagreements, key=lambda one: one.key)),
        by_field=tuple((field, sum(marks), len(marks)) for field, marks in sorted(fields.items())),
    )

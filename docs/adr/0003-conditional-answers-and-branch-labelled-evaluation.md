# ADR-0003 — Conditional answers, branch-labelled golden entries, complete-set recall

- **Date:** 2026-08-26
- **Status:** accepted

## Context

`README.md:20-21` offers the flagship question: *"how often does a two-person household in Turku
need the bio-waste bin emptied?"* Read against the actual regulations (Lounais-Suomi, in force
1.8.2024), that question has no single answer:

- **15 §** — the bio-waste duty binds properties of *1 or more dwellings* **in a taajama of over
  10,000 inhabitants**. "Two-person household" is the wrong variable: the rule counts
  `huoneistojen lukumäärä`, not residents.
- **17 §** — composting exempts the property outright.
- **26 §** — the interval is 2 weeks; 4 weeks in winter **only outside a taajama**; 4 weeks for a
  ventilated, deep-collection or cooled bin.

Two structural facts follow. First, **the corpus is not self-contained by design**: 15 § delegates
taajama boundaries to an external map service and states that the national delineation is deviated
from per property. "Which zone am I in" is unanswerable from the documents. Second, **answers span
clauses** — 15 § + 26 § at minimum — so retrieving a subset yields a confident wrong answer rather
than a partial one.

## Decision

Three coupled decisions, recorded together because each only makes sense given the others.

1. **Output shape: conditional answers.** Reproduce the regulation's own branch structure with a
   citation per branch, and surface unresolved determining variables instead of picking one.
2. **Golden entry shape: chunk set + branch checklist.** Each entry labels a `required_chunks` set,
   a list of `required_branches` (each tied to its supporting chunk), and `forbidden` over-claims.
   A **"claim" is one branch**, so the groundedness denominator is set by hand rather than inferred
   from the answer text.
3. **Headline retrieval metric: complete-set recall@k** — binary per question, did top-k contain
   every required chunk. Per-chunk recall@k and MRR are reported as diagnostics only.

## Rejected alternatives

- **Asking a clarifying question** instead of answering conditionally — rejected because it needs
  multi-turn state, which `DESIGN.md:42` puts out of scope, and because the clarifying question is
  often unanswerable by the person being asked: a resident does not know whether their property
  falls inside a >10,000-inhabitant taajama under a delineation the authority adjusts per property.
- **Refusing when a determining variable is missing** — rejected because it would refuse most of the
  corpus (nearly every obligation is conditioned on area, dwelling count, bin type or property
  type) while the regulations *do* answer conditionally. Refusal precision would look excellent as
  the product became useless.
- **Integrating the authority's map service** to answer definitively — rejected as a scope
  explosion (geospatial dependency, per-authority integrations, address handling against a
  no-personal-data hard limit) that still would not be authoritative, since 15 § says the
  delineation is overridden per property by the authority's judgement.
- **A prose reference answer judged holistically** — rejected because it makes the judge grade an
  essay against an essay on a multi-branch conditional, the hardest possible judgement. Agreement
  with hand labels would be low and unstable, and that agreement figure is exactly what
  `DESIGN.md:99` commits to publishing. It also cannot localise *which* branch was dropped.
- **A retrieval-only golden set, no judge at all** — genuinely tempting given that measurement wins
  ties, and fully arithmetic. Rejected because it abandons groundedness, citation accuracy and
  refusal quality, four of the six rows in the README table, reducing the project to a retrieval
  benchmark.
- **Per-chunk recall@k as the headline** — the literature standard, comparable to published
  benchmarks, smoother to tune against. Rejected because it awards partial credit for retrievals
  that produce wrong answers: missing 17 § scores 0.67 and reads as "mostly fine" while the system
  tells a composting household to get a bin. A headline number must predict correctness.

## Consequences

**Easy.** Judging becomes a set of narrow yes/no calls, which is where judge–human agreement is
highest. Failures localise to a named branch. Two new metrics fall out for free: **branch coverage**
and **over-claim rate**, the latter aimed squarely at confident wrongness.

**Hard.** Golden entries are markedly more expensive to hand-author, and `DESIGN.md:81` asks for
~50 of them. Complete-set recall produces harsher, lower headline numbers than any published
benchmark, so the README table will not be flattering and must not be made so.

**Living with.** The README and `DESIGN.md §6` metric tables both need new headline rows, and the
flagship example question needs restating — it currently asks with the wrong variable.

# ADR-0001 — Domain profile: `cli-tools` base, with a deploy graft and an eval-integrity gate

- **Date:** 2026-08-26
- **Status:** accepted

## Context

`/new-project` requires picking one devkit domain profile; it sets the gate set, the meaning of
"verify like a user", and the definition of done. None of the five profiles (`web`,
`mobile-fullstack`, `game`, `cli-tools`, `library`) was written for a project whose deliverable is
a *measurement*.

Facts, verified against the committed docs rather than assumed:

- `README.md:13-14` — "treats the evaluation harness as the product and the RAG pipeline as the
  thing being measured."
- `DESIGN.md:125` — done means "`make eval` reproduces that table from a clean clone."
- `DESIGN.md:102` — the regression gate is `make eval` in CI failing past a threshold, i.e. an
  exit code.
- `DESIGN.md:41-42` — a polished chat UI, auth, accounts and conversation memory are out of scope.
- `DESIGN.md:111,127` — Cloud Run deploy and a public URL are nonetheless in scope at M3.
- `DESIGN.md:117` — "the golden set is the project; a lazy one makes every number meaningless" is
  listed as a *risk*, with no gate attached.

## Decision

Base profile **`cli-tools`**. Its verify recipe — run the built thing on real input, check the
bad-input path and exit code, install from clean into a fresh environment, paste the actual
terminal output as evidence — is `DESIGN.md`'s definition of done restated.

Two documented grafts on top:

1. **The deployed-URL check from the `web` profile, scoped to `/ship` only.** Confirm the served
   version matches the merged commit and run one real query plus one refusal against the public
   URL. Explicitly *not* adopted: the browser-persona walk, restricted-user login, and
   empty/error-state screenshots, which presuppose the UI and auth this project excludes.
2. **A project-specific "eval integrity" layer, which no profile supplies.** Every profile assumes
   the *code* is what can be wrong. Here the *measurement* can be wrong while every test is green,
   and a harness that reports a confidently wrong number is worse than no harness — it is the
   instrument the rest of the project is trusted against. This promotes `DESIGN.md:117` from a
   risk to a gate.

## Rejected alternatives

- **`web`** — rejected because its gate set (`tsc --noEmit`, `eslint`, `vite build`) has no
  referent in a Python project, and its verify recipe centres on a real-browser walk as a
  restricted non-admin persona. `DESIGN.md:41-42` puts the UI and all auth out of scope, so the
  most valuable half of the profile would be inapplicable ceremony while the actual deliverable
  (`make eval`) would go ungated.
- **`library`** — rejected because it has the right instinct (the harness is the product) but the
  wrong user. Its central gate is packing an artifact, installing it into a fresh venv, and running
  the README examples verbatim as an outside installer. Nothing here is published to an index or
  imported by an external caller, so there is no installer to satisfy; the semver/public-API
  machinery would be dead weight. Worth revisiting only if the harness is ever extracted for reuse.
- **Pure `cli-tools`, no grafts** — rejected because it would leave the M3 Cloud Run deploy
  ungated, and because "paste the terminal output" treats a printed number as evidence. The number
  *is* the thing under suspicion here.
- **Writing a sixth profile in the devkit repo** — rejected for now: one project is not enough
  evidence to generalise a profile from, and devkit is shared across every personal project. If a
  second measurement-shaped project appears, promote graft 2 into `profiles/eval-harness/`.

## Consequences

**Easy.** The gate set is honest Python tooling that already runs green on this machine, and every
gate has been proven capable of going red. The definition of done needs no translation — it is
`DESIGN.md:122-128` almost verbatim.

**Hard.** Graft 2 is not mechanisable the way a linter is. Checking that golden-set labels were not
derived from the retriever's own output, that the judge fails a known-bad control set, and that the
regression gate genuinely goes red are each partly a human judgement performed per run. That cost
is deliberate; it is the project's entire value proposition.

**Living with.** This project's `CLAUDE.md` diverges from any single devkit profile, so a reader
must consult it rather than assuming the profile. Hence this ADR. `make docker-build` and `make
eval` are stubs that exit non-zero until M1/M3 — recorded in `REVIEW-DEBT.md`.

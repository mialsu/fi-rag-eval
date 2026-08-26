# REVIEW-DEBT.md — fi-rag-eval

The standing ledger of everything the green tests do NOT prove. Written at the moment a corner
is cut (`/confess`), read first by any architecture or review session, dispositioned by the
Owner (fixed / accepted-with-reason / promoted-to-issue). A stale or empty-but-should-not-be
ledger is worse than none, because sessions trust it.

<!-- Newest first. Template for an entry: -->
<!--
## YYYY-MM-DD — <one-line title>
- **What:** <what is stubbed / faked / deferred / weaker than spec>
- **Where:** <file:line anchors>
- **What green tests do NOT prove here:** <the specific gap>
- **Disposition:** open
-->

## 2026-08-26 — `make eval` is a stub that exits non-zero

- **What:** The project's headline command, and its definition of done, does not exist. `make eval`
  prints an explanation to stderr and exits 1. Chosen over omitting the target so the contract is
  visible, and over a passing no-op so it can never be mistaken for a green run.
- **Where:** `Makefile:36-42`
- **What green tests do NOT prove here:** `make gate` is green while the product does not exist.
  The gate proves the toolchain, not the pipeline. Nothing in CI yet computes a metric, so nothing
  yet defends against the regression this project was built to catch.
- **Disposition:** open — closes at M1 (retrieval metrics computable, 6 Sep 2026).

## 2026-08-26 — `make docker-build` is a stub; no Dockerfile exists

- **What:** No container image, so the Cloud Run deploy in the design is unreachable. The target
  exits non-zero rather than pretending.
- **Where:** `Makefile:44-46`
- **What green tests do NOT prove here:** The build gate proves a clean `uv sync --locked` and an
  import — it says nothing about whether this runs in a container or on Cloud Run.
- **Disposition:** open — closes at M3 (20 Sep 2026).

## 2026-08-26 — the only test asserts an import

- **What:** `tests/test_smoke.py` asserts the package imports and reports a version. That is all
  the test suite does. The gate's `test` step is therefore near-vacuous today.
- **Where:** `tests/test_smoke.py:9-11`
- **What green tests do NOT prove here:** Literally everything. "1 passed" here means the venv
  works. It must not be read as evidence about retrieval, answering, or metrics.
- **Disposition:** open — closes progressively from M1.

## 2026-08-26 — no CI workflow exists

- **What:** The regression gate described in the design (`make eval` on every pull request, metric
  table posted as a PR comment, fail on a drop past threshold) is not wired. There is no
  `.github/workflows/`.
- **Where:** repo root — absent by omission.
- **What green tests do NOT prove here:** Gates proven on this machine are not proven in CI. Until
  a workflow exists and has been seen to go red on a real regression, the central claim of this
  project is untested.
- **Disposition:** open — closes at M3.

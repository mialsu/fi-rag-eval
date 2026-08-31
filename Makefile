# fi-rag-eval — gate commands. Profile: cli-tools (+ web deploy graft at /ship).
# Every target here is meant to be run by a human or by CI, with a real exit code.

.DEFAULT_GOAL := help
.PHONY: help dev gate lint fmt fmt-check typecheck test build eval eval-baseline \
        ingest label agreement refusals serve token db-up db-down services-up services-down \
        docker-build clean

help: ## Show the available targets
	@grep -hE '^[a-z][a-z-]*:.*## ' $(MAKEFILE_LIST) \
	    | awk 'BEGIN{FS=":.*## "}{printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'

dev: ## Create or refresh the local dev environment (writes uv.lock)
	uv sync

gate: lint fmt-check typecheck test build ## THE commit gate: everything green or no commit
	@echo "gates: green"

lint: ## Lint
	uv run ruff check .

fmt: ## Format in place
	uv run ruff format .

fmt-check: ## Check formatting without writing
	uv run ruff format --check .

typecheck: ## Static types, strict
	uv run mypy

test: ## Unit + harness integration tests
	uv run pytest

build: ## Prove a clean clone reproduces this environment, and the package imports
	uv sync --locked
	uv run python -c "import fi_rag_eval; print(fi_rag_eval.__version__)"

db-up: ## Start the local Postgres the harness measures against
	docker compose up -d --wait postgres

db-down: ## Stop everything (the corpus volume is tmpfs, so the corpus is discarded)
	docker compose down

services-up: ## Start Postgres AND the LiteLLM gateway (needed by anything that answers)
	docker compose up -d --wait

services-down: ## Stop them. The gateway's spend ledger is a named volume and survives.
	docker compose down

ingest: db-up ## Fetch, chunk and load the corpus described by corpus/manifest.yaml
	uv run fi-rag-eval ingest

eval: ingest ## THE product: compute the metric table and gate against the baseline
	uv run fi-rag-eval eval

eval-baseline: ingest ## Record this run as the baseline the gate compares against
	uv run fi-rag-eval eval --write-baseline

label: ingest ## Hand-label the frozen sample's claims (168 units, blind, resumable)
	@echo "168 units, ~1.5-2h. Stop any time with q -- every label is written as you make it."
	uv run fi-rag-eval label

refusals: ## Recompute refusal recall/precision from the frozen sample. No model, no spend.
	uv run fi-rag-eval refusals

agreement: ## Judge-human agreement over the hand labels. VERDICTS=<judge --out file>
	@test -n "$(VERDICTS)" || { \
	  echo "agreement: set VERDICTS to a judge verdict file, e.g." >&2; \
	  echo "  make agreement VERDICTS=eval/runs/verdicts-A.json" >&2; \
	  echo "Produce one with: uv run fi-rag-eval judge <run.json> --out <file>" >&2; \
	  exit 1; }
	uv run fi-rag-eval agreement $(VERDICTS)

serve: ingest ## Serve the gated demo on http://127.0.0.1:8080. SPENDS per answered question.
	@echo "serve: loopback only. Gated: 10 questions per link, 24h, 200/day, \$$10/month."
	@echo "       Each answered question costs ~\$$0.01-0.02 at the gateway. Ctrl-C to stop."
	@echo "       Issue a link with: make token"
	uv run fi-rag-eval serve

token: ## Issue a demo access link. ARGS='--list' / '--revoke AB23-CD45'. No spend.
	uv run fi-rag-eval token $(or $(ARGS),--issue)

docker-build: ## Container image (a /ship-time gate, not a per-commit one)
	@echo "docker-build: NOT IMPLEMENTED -- no Dockerfile until the service exists (M3)." >&2
	@exit 1

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

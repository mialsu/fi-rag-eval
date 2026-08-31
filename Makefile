# fi-rag-eval — gate commands. Profile: cli-tools (+ web deploy graft at /ship).
# Every target here is meant to be run by a human or by CI, with a real exit code.

.DEFAULT_GOAL := help
.PHONY: help dev gate lint fmt fmt-check typecheck test build eval eval-baseline \
        ingest label agreement refusals serve token demo-up demo-token demo-down db-up db-down services-up services-down \
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
	# Named explicitly rather than `up --wait`: since tracer 4, plain `up` also
	# builds the image and runs the containerised demo, and the answer/judge
	# workflow wants neither.
	docker compose up -d --wait postgres litellm

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

docker-build: ## Build the one image (a /ship-time gate, not a per-commit one)
	# --network=host because the build FETCHES the corpus PDFs and verifies them
	# against the manifest's sha256 (ADR-0014). Measured on this machine: a
	# container on Docker's bridge cannot open a TCP connection to
	# lsjatehuoltolautakunta.fi at all (connect 0.000s, timeout at 90s) while the
	# host connects in 0.25s. DNS and MTU are fine; the bridge's egress is not.
	# Reproducibility is unaffected -- every download is checked against the hash.
	docker build --network=host -t fi-rag-eval:local .
	docker run --rm fi-rag-eval:local ingest --fetch-only --raw-dir /app/data/raw

demo-up: docker-build ## Run the WHOLE demo in containers: no host Python, no host voikko
	docker compose up -d --wait postgres litellm
	docker compose up -d --wait demo
	@echo "demo: http://127.0.0.1:8080  -- issue a link with: make demo-token"

demo-token: ## Issue a demo link from INSIDE the container
	docker compose run --rm --no-deps -e FI_RAG_EVAL_DEMO_DATABASE_URL=postgresql://litellm:litellm@litellm-postgres:5432/demo \
	  demo token --issue --base-url http://127.0.0.1:8080

demo-down: ## Stop the containerised demo (the corpus is tmpfs and is discarded)
	docker compose down

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

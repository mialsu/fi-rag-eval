# fi-rag-eval — gate commands. Profile: cli-tools (+ web deploy graft at /ship).
# Every target here is meant to be run by a human or by CI, with a real exit code.

.DEFAULT_GOAL := help
.PHONY: help dev gate lint fmt fmt-check typecheck test build eval docker-build clean

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

eval: ## THE product: compute the metric table against the golden set
	@echo "make eval: NOT IMPLEMENTED. No retrieval pipeline and no golden set exist yet." >&2
	@echo "" >&2
	@echo "This target exits non-zero by design. It must never print a metric table that was" >&2
	@echo "not actually computed -- a harness that reports a fabricated number is worse than" >&2
	@echo "no harness. See DESIGN.md milestones M1-M3 and REVIEW-DEBT.md." >&2
	@exit 1

docker-build: ## Container image (a /ship-time gate, not a per-commit one)
	@echo "docker-build: NOT IMPLEMENTED -- no Dockerfile until the service exists (M3)." >&2
	@exit 1

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

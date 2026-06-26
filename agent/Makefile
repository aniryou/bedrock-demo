# Order-triage agent — common tasks. Uses uv (Python pinned to 3.12).

.DEFAULT_GOAL := help
PY := uv run

.PHONY: help setup skills test lint clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: ## Create the venv and install deps (incl. dev)
	uv sync --extra dev

skills: ## Fetch skill manifests from the order-triage-knowledge repo into ./skills
	./scripts/fetch_skills.sh

test: ## Run hermetic unit tests (no network, no model)
	$(PY) pytest tests -q

lint: ## Ruff lint
	$(PY) ruff check .

clean: ## Remove caches + fetched skills
	rm -rf .pytest_cache .ruff_cache skills

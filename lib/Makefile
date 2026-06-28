# agent_kit — common tasks. Uses uv (Python pinned to 3.12).

.DEFAULT_GOAL := help
PY := uv run

.PHONY: help setup test lint clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: ## Create the venv and install deps (incl. dev)
	uv sync --extra dev

test: ## Run unit tests (no network, no model)
	$(PY) pytest tests -q

lint: ## Ruff lint
	$(PY) ruff check .

clean: ## Remove caches
	rm -rf .pytest_cache .ruff_cache

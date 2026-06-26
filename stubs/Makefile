# Back-office stub services — common tasks.

.DEFAULT_GOAL := help
PY := uv run

.PHONY: help setup test lint sap order-actions snowflake lambdas clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## venv + deps
	uv sync --extra dev

test: ## Run the stub tests (FastAPI TestClient)
	$(PY) pytest -q

lint: ## Ruff lint
	$(PY) ruff check .

sap: ## Run the dummy SAP API locally on :8088
	$(PY) uvicorn sap_stub.app:app --host 127.0.0.1 --port 8088 --reload

order-actions: ## Run the dummy order-actions API locally on :8089
	$(PY) uvicorn order_actions_stub.app:app --host 127.0.0.1 --port 8089 --reload

snowflake: ## Run the Snowflake stub on :8090 (needs AWS creds + SNOWFLAKE_SECRET_NAME)
	$(PY) uvicorn snowflake_stub.app:app --host 127.0.0.1 --port 8090 --reload

lambdas: ## Build all three Lambda zips (arm64) into ./build
	./build_lambdas.sh

clean: ## Remove build + caches
	rm -rf build .pytest_cache .ruff_cache

# bedrock-demo-infra — Terraform + registry/preflight for the AgentCore deployment.

.DEFAULT_GOAL := help
# Override with `make ... TERRAFORM=/path/to/terraform`, or `export TERRAFORM=...`.
# Configs require >= 1.10 (see */versions.tf); a stale PATH terraform fails the check.
TERRAFORM ?= terraform
PY := uv run
TF := $(TERRAFORM) -chdir=terraform
BTF := $(TERRAFORM) -chdir=bootstrap

.PHONY: help setup prereqs preflight tf-validate bootstrap plan deploy register ingest status destroy destroy-full clean snowflake-setup apply-sql bootstrap-admin entra-setup seed-entra-secret seed-graph-secret entra-tf-plan entra-tf snowflake-obo

help: ## Show this help, grouped by section
	@awk 'BEGIN {FS = ":.*?## "} \
	  /^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next} \
	  /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

##@ Setup & checks
prereqs: ## Install terraform (>=1.10) + uv + aws CLI without Homebrew (arm64 macOS friendly)
	bash scripts/prereqs.sh

setup: ## venv + deps (for preflight/register)
	uv sync --extra dev

preflight: ## Read-only AWS access check — confirms the deploy role can reach bedrock / bedrock-agentcore
	$(PY) python -m infra.preflight

tf-validate: ## terraform fmt -check + validate (offline; bootstrap + main)
	$(TERRAFORM) fmt -check -recursive
	$(BTF) init -backend=false -input=false >/dev/null && $(BTF) validate
	$(TF) init -backend=false -input=false >/dev/null && $(TF) validate

##@ Deploy & operate
bootstrap: ## Create ECR + artifacts bucket + secret container FIRST (component CIs publish into these)
	TERRAFORM="$(TERRAFORM)" bash scripts/tf.sh bootstrap apply

plan: ## terraform plan of the main stack (TF_VARs + bootstrap outputs resolved from ../.env)
	TERRAFORM="$(TERRAFORM)" bash scripts/tf.sh main plan

deploy: ## Provision + deploy the main stack (after bootstrap + the agent/stubs CIs have published)
	TERRAFORM="$(TERRAFORM)" bash scripts/tf.sh main apply

register: ## Register agent/tools/skills in the AgentCore Registry (post-deploy)
	$(PY) python -m infra.register

ingest: ## (Re)run Knowledge Base ingestion — required after every fresh apply (CI does NOT run it)
	TERRAFORM="$(TERRAFORM)" bash scripts/ingest_kb.sh

status: ## Runtime/endpoint health + one live triage invocation as the ROPC test user (end-to-end smoke test)
	TERRAFORM="$(TERRAFORM)" bash scripts/status.sh

##@ Teardown
destroy: ## Tear down the MAIN stack (keeps ECR image + S3 artifacts; `make deploy` brings it back)
	TERRAFORM="$(TERRAFORM)" bash scripts/destroy.sh

destroy-full: ## Tear down EVERYTHING incl. bootstrap (ECR + S3 + secret container) + legacy CodeBuild
	TERRAFORM="$(TERRAFORM)" bash scripts/destroy.sh --full

clean: ## Remove terraform working dirs + caches
	rm -rf terraform/.terraform bootstrap/.terraform .ruff_cache

##@ Snowflake data backend
snowflake-setup: ## Seed Snowflake (warehouse/DB/tables/data) + key-pair + Secrets Manager. ARGS=--verify to check only
	set -a; [ -f ../.env ] && . ../.env; set +a; \
	$(PY) --extra bootstrap python scripts/snowflake_bootstrap.py $(ARGS)

apply-sql: ## Apply ad-hoc SQL to Snowflake as the bootstrap admin. FILES="snowflake/rls.sql snowflake/test_user.sql"
	set -a; [ -f ../.env ] && . ../.env; set +a; \
	$(PY) --extra bootstrap python scripts/apply_sql.py $(FILES)

bootstrap-admin: ## One-time: generate a headless bootstrap-admin key-pair + print the Snowsight SQL & .env lines (no browser thereafter)
	bash scripts/gen_bootstrap_admin.sh

##@ Entra identity / OBO
entra-setup: ## Provision the Entra OBO apps via az CLI (idempotent). Needs `az login` as an admin. ARGS=--dry-run|--write-env
	python3 scripts/entra_provision.py $(ARGS)

seed-entra-secret: ## Seed/rotate the Entra OBO client secret into Secrets Manager (value stays out of TF state)
	TERRAFORM="$(TERRAFORM)" bash scripts/seed_entra_secret.sh

seed-graph-secret: ## Seed/rotate the Graph resolver app creds into Secrets Manager (dashboard actor resolution; run after entra-tf)
	bash scripts/seed_graph_secret.sh

snowflake-obo: ## Create the Snowflake EXTERNAL_OAUTH (AZURE) integration for the Entra OBO chain (reads ENTRA_* from ../.env)
	set -a; [ -f ../.env ] && . ../.env; set +a; \
	AZURE_TENANT_ID="$$ENTRA_TENANT_ID" \
	AZURE_AUDIENCE="$${ENTRA_RESOURCE_AUDIENCE:-api://$$ENTRA_RESOURCE_APP_ID}" \
	AZURE_USER_MAPPING_CLAIM="$${ENTRA_USER_MAPPING_CLAIM:-upn,email}" \
	$(PY) --extra bootstrap python scripts/extoauth_spike.py create-azure-integration

entra-tf-plan: ## (alt) Plan the azuread Terraform module for the Entra apps (read-only; needs `az login`)
	$(TERRAFORM) -chdir=entra init -input=false
	$(TERRAFORM) -chdir=entra plan

entra-tf: ## (alt) Apply the azuread Terraform module — creates apps in the logged-in tenant; use a FRESH tenant
	$(TERRAFORM) -chdir=entra init -input=false
	$(TERRAFORM) -chdir=entra apply

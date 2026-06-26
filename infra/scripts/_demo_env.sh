#!/usr/bin/env bash
# Shared environment + helpers for the infra repo's post-deploy ops scripts
# (status.sh, ingest_kb.sh). Sourced, not executed.
#
# Holds the deploy + validate loop: KB ingestion and the ROPC end-to-end smoke
# test. Build/publish happens in each component repo's CI; `terraform apply` is
# `make deploy` here.
set -euo pipefail

# Repo root = parent of scripts/. Works regardless of the caller's CWD.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Put non-Homebrew tool installs on PATH. Also makes a user's ~/bin/terraform
# (>= 1.10, as these configs require) win over a stale Homebrew terraform.
# `make … TERRAFORM=/path` still overrides the binary.
export PATH="$HOME/bin:$HOME/.local/bin:$HOME/Library/Python/3.9/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# Single config file for all deploy/ops: bedrock-demo/.env (the repos' parent
# dir). Same file `make snowflake-setup` etc. read as ../.env. `set -a` so the
# sourced KEY=val lines are exported into the AWS/curl/python child processes.
if [ -f "$REPO_DIR/../.env" ]; then set -a; . "$REPO_DIR/../.env"; set +a; fi

# Config (override via .env or the environment).
export AWS_REGION="${AWS_REGION:-us-west-2}"
export AWS_DEFAULT_REGION="$AWS_REGION"
# Provider region for BOTH stacks must track AWS_REGION (the backend init uses it too).
# Set it here, ALWAYS — not only in deploy_env — so `make bootstrap` (which skips deploy_env)
# can't create ECR/S3/secret in the var.region default while the backend points elsewhere.
export TF_VAR_region="$AWS_REGION"
export NAME_PREFIX="${NAME_PREFIX:-order-triage}"
# Honour `make ... TERRAFORM=/path/to/terraform` (configs require >= 1.10).
TF_BIN="${TERRAFORM:-terraform}"

log() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

require_tools() {
  for t in "$TF_BIN" aws curl python3; do
    command -v "$t" >/dev/null || die "missing '$t' on PATH"
  done
  aws sts get-caller-identity >/dev/null 2>&1 || die "AWS credentials not working — set them in ../.env"
}

# Initialise the remote S3 backend for a stack dir ($1: "terraform" (default) or
# "bootstrap"). The bucket name is account-scoped, so the partial backend block in
# */versions.tf must be given bucket + region at init — derived exactly as
# deploy.yml does (NAME_PREFIX + account id). Locking is S3-native
# (use_lockfile). `init -reconfigure` is idempotent. Errors are fatal (and visible
# — only stdout is hushed) so a creds/backend failure isn't masked as "no deployment".
tf_backend_init() {
  local dir="${1:-terraform}" account bucket
  account="$(aws sts get-caller-identity --query Account --output text)" \
    || die "could not resolve AWS account id — check credentials in ../.env"
  bucket="${TFSTATE_BUCKET:-${NAME_PREFIX}-tfstate-${account}}"
  "$TF_BIN" -chdir="$REPO_DIR/$dir" init -input=false -reconfigure \
    -backend-config="bucket=$bucket" \
    -backend-config="region=$AWS_REGION" >/dev/null \
    || die "terraform init ($dir) against remote state (s3://$bucket) failed"
}

# Read a terraform output from the main stack. ALWAYS re-points .terraform at the
# remote backend first (cheap, -reconfigure, idempotent) so a stale local init —
# from `make tf-validate`'s -backend=false, an account switch, or a colleague's
# clone — can never make us read a non-empty WRONG value. An empty result then
# genuinely means "output missing / not deployed", which the callers turn into a
# clear "run make deploy".
tf_output() {
  tf_backend_init terraform
  "$TF_BIN" -chdir="$REPO_DIR/terraform" output -raw "$1" 2>/dev/null || true
}

# Export the deploy-time TF_VARs the MAIN stack needs from .env. Required vars
# (snowflake_api_key, entra_*) are exported only when present, so a missing one
# makes terraform fail fast with "No value for required variable" rather than
# silently applying an empty string.
export_deploy_tfvars() {
  # TF_VAR_region is exported globally above (bootstrap needs it too); here = main-stack vars.
  export TF_VAR_bedrock_model_id="${BEDROCK_MODEL_ID:-amazon.nova-lite-v1:0}"
  [ -n "${SNOWFLAKE_API_KEY:-}" ] && export TF_VAR_snowflake_api_key="$SNOWFLAKE_API_KEY"
  [ -n "${ENTRA_TENANT_ID:-}" ]    && export TF_VAR_entra_tenant_id="$ENTRA_TENANT_ID"
  [ -n "${ENTRA_AGENT_APP_ID:-}" ] && export TF_VAR_entra_agent_app_id="$ENTRA_AGENT_APP_ID"
  [ -n "${ENTRA_OBO_SCOPE:-}" ]    && export TF_VAR_entra_obo_scope="$ENTRA_OBO_SCOPE"
  # Phase 3 observability (monitoring.tf / evaluations.tf): optional, kept out of git.
  [ -n "${ALERT_EMAIL:-}" ]               && export TF_VAR_alert_email="$ALERT_EMAIL"
  [ -n "${ENABLE_ONLINE_EVALUATIONS:-}" ] && export TF_VAR_enable_online_evaluations="$ENABLE_ONLINE_EVALUATIONS"
  return 0
}

# Read the bootstrap stack's outputs (ECR repo + artifacts bucket) into the two
# TF_VARs the main stack consumes. Requires `make bootstrap` to have run.
load_bootstrap_outputs() {
  tf_backend_init bootstrap
  local ecr bucket
  ecr="$("$TF_BIN" -chdir="$REPO_DIR/bootstrap" output -raw ecr_repository_url 2>/dev/null || true)"
  bucket="$("$TF_BIN" -chdir="$REPO_DIR/bootstrap" output -raw artifacts_bucket 2>/dev/null || true)"
  [ -n "$ecr" ] && [ -n "$bucket" ] || die "bootstrap outputs missing — run 'make bootstrap' first"
  # Braces matter: a bare $ecr:latest triggers zsh's ':l' modifier; harmless under
  # bash but keep the habit.
  export TF_VAR_agent_image_uri="${ecr}:latest"
  export TF_VAR_artifacts_bucket="$bucket"
}

# Full deploy-time env for plan / apply / destroy of the MAIN stack.
deploy_env() {
  export_deploy_tfvars
  load_bootstrap_outputs
}

# Inject the Entra OBO client secret VALUE into the Secrets Manager container the
# bootstrap stack created. The value never enters Terraform state (identity.tf
# references the secret by ARN, clientSecretSource=EXTERNAL). Read tilde-safely
# from ../.env via grep/cut (a sourced var would be tilde-expanded/emptied), then
# handed to the AWS CLI through a 0600 temp file — never argv. Run after Entra
# provisioning and on every secret rotation. Requires bootstrap applied.
seed_entra_secret() {
  [ -f "$REPO_DIR/../.env" ] || die "no ../.env — nothing to seed"
  local secret tmp
  secret="$(grep -E '^ENTRA_AGENT_CLIENT_SECRET=' "$REPO_DIR/../.env" | head -1 | cut -d= -f2-)"
  [ -n "$secret" ] || die "ENTRA_AGENT_CLIENT_SECRET not in ../.env"
  tmp="$(mktemp)"; trap 'rm -f "$tmp"' RETURN
  ENTRA_SECRET="$secret" python3 -c 'import json,os; print(json.dumps({"client_secret": os.environ["ENTRA_SECRET"]}))' > "$tmp"
  aws secretsmanager put-secret-value \
    --secret-id "order-triage/entra-agent-client-secret" \
    --secret-string "file://$tmp" >/dev/null \
    && log "Seeded Entra client secret into Secrets Manager (order-triage/entra-agent-client-secret)" \
    || die "failed to put the Entra client secret into Secrets Manager"
}

# Mint an Entra USER access token (ROPC) for the CUSTOM_JWT runtime's inbound auth.
# Gateway-only: every invocation needs a user JWT. Uses a dedicated TEST user's creds
# (ENTRA_TEST_USER / ENTRA_TEST_PASSWORD in .env) against the agent app's delegated scope,
# so `make status` can self-test headlessly. ROPC is for the demo test identity ONLY — never
# real users. Echoes the access_token to stdout.
# The scope api://<app>/access_as_user must yield aud=api://<app> + a v1 token
# (iss=sts.windows.net) to match the runtime's allowed_audience + v1 discovery.
mint_user_token() {
  : "${ENTRA_TENANT_ID:?ENTRA_TENANT_ID required}" "${ENTRA_AGENT_APP_ID:?ENTRA_AGENT_APP_ID required}"
  : "${ENTRA_TEST_USER:?ENTRA_TEST_USER required (ROPC test identity)}"
  : "${ENTRA_TEST_PASSWORD:?ENTRA_TEST_PASSWORD required (ROPC test identity)}"
  local secret
  secret="$(aws secretsmanager get-secret-value --secret-id order-triage/entra-agent-client-secret \
              --query SecretString --output text \
            | python3 -c 'import json,sys; print(json.load(sys.stdin)["client_secret"])')"
  # Build the url-encoded form in python — every secret (client_secret, ROPC
  # password) is read from the ENVIRONMENT, never argv — then stream it to curl
  # via stdin so nothing sensitive lands on the host process list. Equivalent to
  # the per-field --data-urlencode form curl would otherwise build on argv.
  ENTRA_SECRET="$secret" python3 -c '
import os, sys, urllib.parse
app = os.environ["ENTRA_AGENT_APP_ID"]
sys.stdout.write(urllib.parse.urlencode({
    "grant_type": "password",
    "client_id": app,
    "client_secret": os.environ["ENTRA_SECRET"],
    "scope": "api://%s/access_as_user" % app,
    "username": os.environ["ENTRA_TEST_USER"],
    "password": os.environ["ENTRA_TEST_PASSWORD"],
}))' \
  | curl -sS -X POST "https://login.microsoftonline.com/${ENTRA_TENANT_ID}/oauth2/v2.0/token" \
      --data-binary @- \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("access_token") or sys.exit("token mint failed: "+json.dumps(d)))'
}

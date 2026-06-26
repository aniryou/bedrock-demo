#!/usr/bin/env bash
# Seed / rotate the Graph resolver app creds (tenant_id, client_id, client_secret) into Secrets
# Manager for the dashboard actor-resolution Lambda (ADR-0007). Values come from the entra/
# Terraform outputs (separate local state) and never enter the main stack's state. Run after
# `make entra-tf` has created the graph_resolver app, then set enable_actor_resolution = true.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

set -a; . "$ROOT/../.env" >/dev/null 2>&1 || true; set +a
: "${AWS_REGION:=us-west-2}"
SECRET_NAME="${TF_VAR_graph_resolver_secret_name:-${GRAPH_RESOLVER_SECRET_NAME:-order-triage-graph-resolver}}"

TF="terraform -chdir=$ROOT/entra"
# tenant_id may be absent from a targeted apply (its data source wasn't in the target set);
# fall back to .env then the az CLI session.
TENANT="$($TF output -raw tenant_id 2>/dev/null || true)"
[ -n "$TENANT" ] || TENANT="${ENTRA_TENANT_ID:-}"
[ -n "$TENANT" ] || TENANT="$(az account show --query tenantId -o tsv 2>/dev/null || true)"
[ -n "$TENANT" ] || { echo "could not resolve tenant_id (set ENTRA_TENANT_ID in .env or run az login)"; exit 1; }
CLIENT_ID="$($TF output -raw graph_resolver_client_id)"
CLIENT_SECRET="$($TF output -raw graph_resolver_client_secret)"
PAYLOAD="$(printf '{"tenant_id":"%s","client_id":"%s","client_secret":"%s"}' \
  "$TENANT" "$CLIENT_ID" "$CLIENT_SECRET")"

if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
  aws secretsmanager put-secret-value --secret-id "$SECRET_NAME" \
    --secret-string "$PAYLOAD" --region "$AWS_REGION" >/dev/null
  echo "updated Graph resolver secret: $SECRET_NAME"
else
  aws secretsmanager create-secret --name "$SECRET_NAME" \
    --description "Graph app creds for dashboard actor resolution (ADR-0007)" \
    --secret-string "$PAYLOAD" --region "$AWS_REGION" >/dev/null
  echo "created Graph resolver secret: $SECRET_NAME"
fi

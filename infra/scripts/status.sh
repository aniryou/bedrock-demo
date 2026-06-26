#!/usr/bin/env bash
# Show runtime/endpoint health, then run one sample triage invocation as the
# ROPC test user. This is the end-to-end smoke test for a live deployment.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/_demo_env.sh"
require_tools

ARN="$(tf_output agent_runtime_arn)"
[ -n "$ARN" ] || die "no deployment found (agent_runtime_arn output missing) — run 'make deploy'"
RID="${ARN##*/}"

log "Runtime"
aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$RID" \
  --query '{version:agentRuntimeVersion,model:environmentVariables.BEDROCK_MODEL_ID,status:status}' --output table
log "Endpoints"
aws bedrock-agentcore-control list-agent-runtime-endpoints --agent-runtime-id "$RID" \
  --query 'runtimeEndpoints[].{name:name,liveVersion:liveVersion,status:status}' --output table

log "Sample invocation (Triage order O-1003) — as the ROPC test user"
# Gateway-only: the runtime is CUSTOM_JWT, so a SigV4 `invoke-agent-runtime` is rejected.
# Mint an Entra user token (ROPC test identity) and POST to the runtime's HTTPS invocation
# endpoint with `Authorization: Bearer`.
TOKEN="$(mint_user_token)" || die "could not mint a user token (set ENTRA_TEST_USER/ENTRA_TEST_PASSWORD in ../.env)"
SID="status-check-$(date +%s)-padpadpadpadpadpadpadpadpad"
# mktemp (0600), not predictable world-readable paths — the response can carry order/customer data.
PAYLOAD="$(mktemp)"; RESP="$(mktemp)"; HDR="$(mktemp)"; trap 'rm -f "$PAYLOAD" "$RESP" "$HDR"' EXIT
printf '%s' '{"prompt":"Triage order O-1003: score risk, check SAP credit, and flag for review if warranted. Cite any KB policy used."}' > "$PAYLOAD"
# Bearer header via a 0600 mktemp file (not argv) so the live token stays off the process list.
printf 'Authorization: Bearer %s' "$TOKEN" > "$HDR"
ENC_ARN="$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$ARN")"
URL="https://bedrock-agentcore.${AWS_REGION}.amazonaws.com/runtimes/${ENC_ARN}/invocations?qualifier=DEFAULT"
curl -sS -X POST "$URL" \
  -H @"$HDR" \
  -H "Content-Type: application/json" \
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: $SID" \
  --data-binary @"$PAYLOAD" > "$RESP"
echo "--- agent response (tail) ---"
tail -c 900 "$RESP"; echo

#!/usr/bin/env bash
# Trigger Knowledge Base ingestion (terraform apply creates the KB + data source
# but does not run ingestion). Needed after every fresh apply so policy lookups
# work. CI deploys do NOT run this — run it once after a deploy.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/_demo_env.sh"
require_tools

KB="$(tf_output knowledge_base_id)"
[ -n "$KB" ] || die "knowledge_base_id output missing — run 'make deploy' first"
DS="$(aws bedrock-agent list-data-sources --knowledge-base-id "$KB" --query 'dataSourceSummaries[0].dataSourceId' --output text)"
log "Ingestion job (KB=$KB DS=$DS)"
JOB="$(aws bedrock-agent start-ingestion-job --knowledge-base-id "$KB" --data-source-id "$DS" --query 'ingestionJob.ingestionJobId' --output text)"
while :; do
  st="$(aws bedrock-agent get-ingestion-job --knowledge-base-id "$KB" --data-source-id "$DS" --ingestion-job-id "$JOB" --query 'ingestionJob.status' --output text)"
  case "$st" in COMPLETE|FAILED) echo "ingestion: $st"; break;; *) sleep 8;; esac
done
[ "$st" = "COMPLETE" ] || die "ingestion did not complete ($st)"

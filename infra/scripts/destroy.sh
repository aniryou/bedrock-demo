#!/usr/bin/env bash
# Tear down the deployment (terraform prompts for confirmation — not -auto-approve).
#   destroy.sh         -> MAIN stack only (keeps ECR image + S3 artifacts; `make deploy` brings it back fast)
#   destroy.sh --full  -> also destroys the bootstrap stack (ECR + artifacts bucket + secret container)
#                         and removes any CodeBuild project/role for the local image build
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/_demo_env.sh"
require_tools
FULL="${1:-}"
deploy_env   # `terraform destroy` evaluates the config, so the required TF_VARs must be set

log "Destroy main stack (runtime, gateway, KB, memory, policy, lambdas)"
tf_backend_init terraform
"$TF_BIN" -chdir="$REPO_DIR/terraform" destroy

if [ "$FULL" = "--full" ]; then
  log "Destroy bootstrap (ECR + artifacts bucket + secret container)"
  tf_backend_init bootstrap
  "$TF_BIN" -chdir="$REPO_DIR/bootstrap" destroy
  log "Remove any CodeBuild project/role (only present if the local image build ran)"
  aws codebuild delete-project --name "${NAME_PREFIX}-agent-build" >/dev/null 2>&1 || true
  aws iam delete-role-policy --role-name "${NAME_PREFIX}-codebuild" --policy-name "${NAME_PREFIX}-codebuild-inline" >/dev/null 2>&1 || true
  aws iam delete-role --role-name "${NAME_PREFIX}-codebuild" >/dev/null 2>&1 || true
  echo "Full teardown done. Bring back up with: make bootstrap && make deploy && make ingest"
else
  echo "Main stack destroyed. ECR image + S3 artifacts kept — bring back up with: make deploy && make ingest"
fi

#!/usr/bin/env bash
# Run terraform against a stack with the full remote-state + deploy-time env
# (so `make bootstrap`/`plan`/`deploy` work from a fresh clone, not only after an
# external init). Usage:
#   tf.sh bootstrap <plan|apply|...>   # ECR + artifacts bucket + secret container
#   tf.sh main      <plan|apply|...>   # the AgentCore stack (needs TF_VARs + bootstrap outputs)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/_demo_env.sh"
require_tools
[ $# -ge 2 ] || die "usage: tf.sh <bootstrap|main> <subcommand> [args...]"
stack="$1"; sub="$2"; shift 2
case "$stack" in
  bootstrap) dir="bootstrap" ;;
  main)      dir="terraform"; deploy_env ;;   # TF_VARs from .env + bootstrap outputs
  *)         die "unknown stack '$stack' (want: bootstrap | main)" ;;
esac
tf_backend_init "$dir"
"$TF_BIN" -chdir="$REPO_DIR/$dir" "$sub" "$@"

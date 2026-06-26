#!/usr/bin/env bash
# Seed / rotate the Entra OBO client secret into Secrets Manager (the value never
# enters Terraform state — identity.tf references it by ARN). Reads
# ENTRA_AGENT_CLIENT_SECRET from ../.env. Requires `make bootstrap` (the secret
# container) to have run. Re-run on every secret rotation.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/_demo_env.sh"
require_tools
seed_entra_secret

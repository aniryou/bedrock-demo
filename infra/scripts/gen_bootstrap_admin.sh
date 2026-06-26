#!/usr/bin/env bash
# Generate a headless "bootstrap admin" RSA key-pair for Snowflake and print the
# one-time Snowsight SQL + the admin-auth .env lines (account/host set separately).
#
# Run this ONCE, paste STEP 1 into a Snowsight worksheet as an ACCOUNTADMIN, copy
# STEP 2 into the root .env, and `make snowflake-setup` is then fully
# headless (no browser / no Snowsight) forever. Idempotent: reuses an existing key.
#
#   make bootstrap-admin                       # default user SVC_ORDER_TRIAGE_BOOTSTRAP
#   SNOWFLAKE_BOOTSTRAP_USER=MYADMIN make bootstrap-admin
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEY_DIR="${SNOWFLAKE_KEY_DIR:-$HERE/../snowflake/.keys}"   # gitignored
KEY="$KEY_DIR/bootstrap_admin_rsa_key.p8"
SF_USER="${SNOWFLAKE_BOOTSTRAP_USER:-SVC_ORDER_TRIAGE_BOOTSTRAP}"

command -v openssl >/dev/null || { echo "error: openssl not found on PATH" >&2; exit 1; }
mkdir -p "$KEY_DIR"

if [ -f "$KEY" ]; then
  echo "# reusing existing bootstrap-admin key: $KEY" >&2
else
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$KEY" 2>/dev/null
  echo "# generated new bootstrap-admin key: $KEY" >&2
fi
chmod 600 "$KEY"   # always enforce 0600, whether freshly generated or reused

# Public key Snowflake wants: DER SubjectPublicKeyInfo, base64, single line, no PEM armor.
PUB_B64="$(openssl pkey -in "$KEY" -pubout -outform DER 2>/dev/null | openssl base64 -A)"
# Private key for .env: base64 of the PKCS#8 PEM text, single line (.env-safe).
PRIV_B64="$(openssl base64 -A -in "$KEY")"

cat <<EOF

============================================================================
 STEP 1 — paste ONCE into a Snowsight worksheet as an ACCOUNTADMIN
============================================================================
USE ROLE ACCOUNTADMIN;

-- No password is set, and the RSA_PUBLIC_KEY below is the only credential, so this user
-- is key-pair-only. On editions that support it you may add  TYPE = SERVICE  to the CREATE
-- for stricter no-password/MFA enforcement (some accounts reject that property).
CREATE USER IF NOT EXISTS $SF_USER
  COMMENT = 'Headless key-pair bootstrap admin for order-triage (make snowflake-setup)';

ALTER USER $SF_USER SET RSA_PUBLIC_KEY = '$PUB_B64';

-- Option A (simplest; matches setup.sql's "USE ROLE ACCOUNTADMIN", no other code changes):
GRANT ROLE ACCOUNTADMIN TO USER $SF_USER;
ALTER USER $SF_USER SET DEFAULT_ROLE = ACCOUNTADMIN;
-- Least-privilege alternative (Option B): see infra/README.md.

============================================================================
 STEP 2 — add these admin-auth lines to the root .env
   (also set SNOWFLAKE_ACCOUNT + SNOWFLAKE_HOST — see .env.example)
   SENSITIVE: the last line is your bootstrap-admin PRIVATE KEY. Do NOT run this
   in CI or on a shared screen; clear your terminal scrollback after pasting.
============================================================================
SNOWFLAKE_ADMIN_USER=$SF_USER
SNOWFLAKE_ADMIN_AUTH=keypair
SNOWFLAKE_ADMIN_PRIVATE_KEY_B64=$PRIV_B64

============================================================================
 STEP 3 — headless from now on (no browser):
   make snowflake-setup
============================================================================
EOF

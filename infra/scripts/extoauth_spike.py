#!/usr/bin/env python3
"""Entra External OAuth helper for the live OBO chain.

Connects to Snowflake as the headless admin (key-pair, ACCOUNTADMIN — same env as
snowflake_bootstrap.py) and manages the AZURE External OAuth integration the OBO
token-exchange relies on.

Subcommands:
  create-azure-integration  (mutating): the entra_obo EXTERNAL_OAUTH_TYPE=AZURE
                       integration from AZURE_TENANT_ID / AZURE_AUDIENCE.
  verify-token TOKEN    (read-only): SYSTEM$VERIFY_EXTERNAL_OAUTH_TOKEN(token).
  teardown              Drop the entra_obo integration (mutating).

Admin connection env (sourced from ../.env by the Makefile pattern):
  SNOWFLAKE_ACCOUNT, SNOWFLAKE_HOST, SNOWFLAKE_ADMIN_USER,
  SNOWFLAKE_ADMIN_AUTH=keypair, SNOWFLAKE_ADMIN_PRIVATE_KEY_B64 | _PRIVATE_KEY [, _PASSPHRASE],
  SNOWFLAKE_WAREHOUSE (default ORDER_TRIAGE_WH).
create-azure-integration env:
  AZURE_TENANT_ID, AZURE_AUDIENCE (the resource app's Application ID URI),
  AZURE_USER_MAPPING_CLAIM (default 'upn'; a comma-separated list is allowed),
  AZURE_SNOWFLAKE_USER_ATTR (default 'login_name').
"""

from __future__ import annotations

import base64
import os
import sys


def admin_connection():
    import snowflake.connector
    from cryptography.hazmat.primitives import serialization

    account = os.environ["SNOWFLAKE_ACCOUNT"].upper()
    user = os.environ["SNOWFLAKE_ADMIN_USER"]
    host = os.environ.get("SNOWFLAKE_HOST", "")
    passp = os.environ.get("SNOWFLAKE_ADMIN_PRIVATE_KEY_PASSPHRASE", "") or None
    b64 = os.environ.get("SNOWFLAKE_ADMIN_PRIVATE_KEY_B64", "")
    path = os.environ.get("SNOWFLAKE_ADMIN_PRIVATE_KEY", "")
    if b64:
        pem = base64.b64decode(b64.strip())
    elif path:
        pem = open(path, "rb").read()
    else:
        sys.exit("error: SNOWFLAKE_ADMIN_PRIVATE_KEY_B64 or SNOWFLAKE_ADMIN_PRIVATE_KEY required")
    key = serialization.load_pem_private_key(pem, password=(passp.encode() if passp else None))
    der = key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    params = {
        "account": account,
        "user": user,
        "role": "ACCOUNTADMIN",
        "private_key": der,
        "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "ORDER_TRIAGE_WH"),
    }
    if host:
        params["host"] = host
    print(f"connecting as {user}@{account} (ACCOUNTADMIN, key-pair) ...")
    return snowflake.connector.connect(**params)


def _rows(cur, sql):
    cur.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    return cols, cur.fetchall()


def cmd_create_azure_integration() -> int:
    """Snowflake EXTERNAL_OAUTH_TYPE=AZURE integration for the Entra OBO chain.

    Env: AZURE_TENANT_ID, AZURE_AUDIENCE (the resource app's Application ID URI,
    e.g. api://order-triage-snowflake). The AZURE type sources the login role from
    the `session:role-any` / `session:role:<ROLE>` value in the token's `scp` natively,
    so we must NOT set EXTERNAL_OAUTH_SCOPE_MAPPING_ATTRIBUTE (CUSTOM-only). v1 issuer
    is required.
    """
    tenant = os.environ["AZURE_TENANT_ID"]
    audience = os.environ["AZURE_AUDIENCE"]
    # AZURE_USER_MAPPING_CLAIM may be a single claim or a comma-separated list. Managed
    # (member) users carry `upn`; guest / personal (live.com) accounts federated into the
    # tenant carry no `upn` — only `email` / `unique_name`. Mapping a LIST lets one
    # integration serve both: Snowflake tries each claim in turn.
    claims = [c.strip() for c in os.environ.get("AZURE_USER_MAPPING_CLAIM", "upn").split(",") if c.strip()]
    claim_sql = "('" + "','".join(claims) + "')" if len(claims) > 1 else f"'{claims[0]}'"
    attr = os.environ.get("AZURE_SNOWFLAKE_USER_ATTR", "login_name")
    sql = (
        "CREATE OR REPLACE SECURITY INTEGRATION entra_obo TYPE=external_oauth ENABLED=true "
        "EXTERNAL_OAUTH_TYPE=azure "
        f"EXTERNAL_OAUTH_ISSUER='https://sts.windows.net/{tenant}/' "
        f"EXTERNAL_OAUTH_JWS_KEYS_URL='https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys' "
        f"EXTERNAL_OAUTH_AUDIENCE_LIST=('{audience}') "
        f"EXTERNAL_OAUTH_TOKEN_USER_MAPPING_CLAIM={claim_sql} "
        f"EXTERNAL_OAUTH_SNOWFLAKE_USER_MAPPING_ATTRIBUTE='{attr}' "
        "EXTERNAL_OAUTH_ANY_ROLE_MODE='ENABLE'"
    )
    con = admin_connection()
    cur = con.cursor()
    try:
        print("  " + sql)
        cur.execute(sql)
        _, r = _rows(cur, "DESC SECURITY INTEGRATION entra_obo")
        print(f"[ok] integration entra_obo created ({len(r)} properties)")
    finally:
        con.close()
    return 0


def cmd_verify_token(token: str) -> int:
    con = admin_connection()
    cur = con.cursor()
    try:
        _, r = _rows(cur, f"SELECT SYSTEM$VERIFY_EXTERNAL_OAUTH_TOKEN('{token}')")
        print(r[0][0])
    finally:
        con.close()
    return 0


def cmd_teardown() -> int:
    con = admin_connection()
    cur = con.cursor()
    try:
        sql = "DROP SECURITY INTEGRATION IF EXISTS entra_obo"
        print("  " + sql)
        cur.execute(sql)
        print("[ok] entra_obo integration dropped")
    finally:
        con.close()
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "create-azure-integration":
        return cmd_create_azure_integration()
    if cmd == "verify-token":
        if len(sys.argv) < 3:
            sys.exit("usage: verify-token <jwt>")
        return cmd_verify_token(sys.argv[2])
    if cmd == "teardown":
        return cmd_teardown()
    print(f"unknown subcommand: {cmd}\n{__doc__}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

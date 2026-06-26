#!/usr/bin/env python3
"""Bootstrap the Snowflake side of the order-triage demo.

Runs snowflake/setup.sql (warehouse / DB / tables / seed + read-only role +
key-pair service user), generates an RSA key-pair and registers its public key on
the service user, then stores the private key + connection config in AWS Secrets
Manager — the secret the snowflake-query Lambda reads.

    make snowflake-setup                 # full bootstrap (idempotent, re-runnable)
    make snowflake-setup ARGS=--verify   # verify the existing setup only (read-only)

Config via env vars (object-name defaults match the deployed demo):

  Required:
    SNOWFLAKE_ACCOUNT        account identifier, e.g. GA20262
    SNOWFLAKE_HOST           <account>.<region>.snowflakecomputing.com
    SNOWFLAKE_ADMIN_USER     admin that creates objects, e.g. ANIRYOU  (setup only)

  Admin auth (creating objects needs admin; this can't bootstrap itself):
    SNOWFLAKE_ADMIN_AUTH         keypair (recommended, headless) | externalbrowser | password |
                                 pat | oauth        [default: externalbrowser]
    SNOWFLAKE_ADMIN_PASSWORD     (when ...AUTH=password)
    SNOWFLAKE_ADMIN_PRIVATE_KEY  path to a PKCS#8 key (when ...AUTH=keypair)
    SNOWFLAKE_ADMIN_PRIVATE_KEY_B64         inline base64 of the PKCS#8 PEM (alt to the path —
                                            .env-safe, single line; wins over the path if both set)
    SNOWFLAKE_ADMIN_PRIVATE_KEY_PASSPHRASE  passphrase if the PKCS#8 key is encrypted (either form)
    SNOWFLAKE_ADMIN_TOKEN_FILE   path to a file holding a token (when ...AUTH=pat|oauth);
                                 pat   = Programmatic Access Token, sent as the password;
                                 oauth = OAuth/session bearer token (authenticator=oauth).
    SNOWFLAKE_ADMIN_TOKEN        the token inline (alternative to ...TOKEN_FILE)

  Optional (defaults shown):
    SNOWFLAKE_DATABASE=ORDER_TRIAGE_DB   SNOWFLAKE_SCHEMA=PUBLIC
    SNOWFLAKE_WAREHOUSE=ORDER_TRIAGE_WH  SNOWFLAKE_RO_ROLE=ORDER_TRIAGE_RO
    SNOWFLAKE_SVC_USER=SVC_ORDER_TRIAGE  SNOWFLAKE_SECRET_NAME=order-triage/snowflake
    AWS_REGION=us-west-2                 SNOWFLAKE_KEY_DIR=snowflake/.keys
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import boto3
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

HERE = Path(__file__).resolve().parent
SETUP_SQL = HERE.parent / "snowflake" / "setup.sql"


def config() -> dict:
    return {
        "account": os.environ.get("SNOWFLAKE_ACCOUNT", "").upper(),
        "host": os.environ.get("SNOWFLAKE_HOST", ""),
        "admin_user": os.environ.get("SNOWFLAKE_ADMIN_USER", ""),
        "admin_auth": os.environ.get("SNOWFLAKE_ADMIN_AUTH", "externalbrowser"),
        "admin_password": os.environ.get("SNOWFLAKE_ADMIN_PASSWORD", ""),
        "admin_pk": os.environ.get("SNOWFLAKE_ADMIN_PRIVATE_KEY", ""),
        "admin_pk_b64": os.environ.get("SNOWFLAKE_ADMIN_PRIVATE_KEY_B64", ""),
        "admin_pk_passphrase": os.environ.get("SNOWFLAKE_ADMIN_PRIVATE_KEY_PASSPHRASE", ""),
        "admin_token_file": os.environ.get("SNOWFLAKE_ADMIN_TOKEN_FILE", ""),
        "admin_token": os.environ.get("SNOWFLAKE_ADMIN_TOKEN", ""),
        "database": os.environ.get("SNOWFLAKE_DATABASE", "ORDER_TRIAGE_DB"),
        "schema": os.environ.get("SNOWFLAKE_SCHEMA", "PUBLIC"),
        "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "ORDER_TRIAGE_WH"),
        "ro_role": os.environ.get("SNOWFLAKE_RO_ROLE", "ORDER_TRIAGE_RO"),
        "svc_user": os.environ.get("SNOWFLAKE_SVC_USER", "SVC_ORDER_TRIAGE").upper(),
        "secret_name": os.environ.get("SNOWFLAKE_SECRET_NAME", "order-triage/snowflake"),
        "region": os.environ.get("AWS_REGION", "us-west-2"),
        "key_dir": Path(os.environ.get("SNOWFLAKE_KEY_DIR", str(SETUP_SQL.parent / ".keys"))),
    }


def gen_or_load_keypair(key_dir: Path) -> tuple[str, str]:
    """Return (private_pem, public_key_b64). Reuse an existing key-pair if present
    (so re-runs don't rotate the key), otherwise generate one."""
    key_dir.mkdir(parents=True, exist_ok=True)
    p8 = key_dir / "rsa_key.p8"
    if p8.exists():
        priv = serialization.load_pem_private_key(p8.read_bytes(), password=None)
        print(f"reusing existing key-pair at {p8}")
    else:
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        p8.write_bytes(
            priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        p8.chmod(0o600)
        (key_dir / "rsa_key.pub").write_bytes(
            priv.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        print(f"generated new key-pair at {p8}")
    pub_der = priv.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return p8.read_text(), base64.b64encode(pub_der).decode()


def render_setup_sql(c: dict) -> str:
    """Read setup.sql and substitute its default object names with the configured
    ones, so the SQL, the Secrets Manager payload (upsert_secret), and the Lambda
    all agree on a single source of truth — config(). The defaults below are exactly
    the literals in setup.sql, so an un-overridden run renders BYTE-IDENTICAL SQL.
    None of the four names is a substring of another, so replace() order is moot.
    (SNOWFLAKE_SCHEMA is intentionally not templated — setup.sql uses the always-present
    PUBLIC schema; overriding the schema is unsupported by the SQL.)"""
    sql = SETUP_SQL.read_text()
    for default, configured in (
        ("ORDER_TRIAGE_WH", c["warehouse"]),
        ("ORDER_TRIAGE_DB", c["database"]),
        ("ORDER_TRIAGE_RO", c["ro_role"]),
        ("SVC_ORDER_TRIAGE", c["svc_user"]),
    ):
        sql = sql.replace(default, configured)
    return sql


def connect_admin(c: dict):
    """Open an admin Snowflake connection from config() (keypair / password /
    externalbrowser / pat|oauth), resolving the real host when only an account was
    given. Shared by run_admin_sql (setup) and apply_sql.py (ad-hoc SQL)."""
    import snowflake.connector  # lazy: only needed when actually connecting

    params = {
        "account": c["account"],
        "user": c["admin_user"],
        "role": "ACCOUNTADMIN",
        "warehouse": c["warehouse"],
    }
    if c["host"]:
        params["host"] = c["host"]  # else the connector derives it from the account
    auth = c["admin_auth"]
    if auth == "externalbrowser":
        params["authenticator"] = "externalbrowser"
    elif auth == "password":
        if not c["admin_password"]:
            sys.exit("error: SNOWFLAKE_ADMIN_PASSWORD required for AUTH=password")
        params["password"] = c["admin_password"]
    elif auth == "keypair":
        # Admin key-pair (fully headless). Key from an inline base64 PKCS#8 PEM (.env-safe)
        # or a file path; base64 wins when both are set.
        passphrase = c["admin_pk_passphrase"].encode() if c["admin_pk_passphrase"] else None
        if c["admin_pk_b64"]:
            pem_bytes = base64.b64decode(c["admin_pk_b64"].strip())
        elif c["admin_pk"]:
            pem_bytes = Path(c["admin_pk"]).read_bytes()
        else:
            sys.exit(
                "error: SNOWFLAKE_ADMIN_PRIVATE_KEY_B64 (inline) or "
                "SNOWFLAKE_ADMIN_PRIVATE_KEY (file path) required for AUTH=keypair"
            )
        admin_key = serialization.load_pem_private_key(pem_bytes, password=passphrase)
        params["private_key"] = admin_key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    elif auth in ("pat", "oauth", "token"):
        token = c["admin_token"] or (
            Path(c["admin_token_file"]).read_text().strip() if c["admin_token_file"] else ""
        )
        if not token:
            sys.exit("error: SNOWFLAKE_ADMIN_TOKEN_FILE or SNOWFLAKE_ADMIN_TOKEN required for AUTH=pat/oauth")
        if auth == "oauth":
            # OAuth / session bearer token.
            params["authenticator"] = "oauth"
            params["token"] = token
        else:
            # Programmatic Access Token: authenticates wherever a password would.
            params["password"] = token
    else:
        sys.exit(f"error: unknown SNOWFLAKE_ADMIN_AUTH={auth}")

    print(f"connecting to Snowflake as {c['admin_user']} (auth={auth}) ...")
    con = snowflake.connector.connect(**params)
    if not c["host"]:
        # Learn the real host from the established connection (e.g. an account-only
        # externalbrowser login) so the secret + verify use the actual hostname.
        c["host"] = getattr(con, "host", "") or c["host"]
        print(f"resolved host: {c['host']}")
    return con


def run_admin_sql(c: dict, public_b64: str) -> None:
    """Run setup.sql + register the service user's public key, as the admin."""
    sql = render_setup_sql(c)
    sql += f"\nALTER USER {c['svc_user']} SET RSA_PUBLIC_KEY = '{public_b64}';\n"

    con = connect_admin(c)
    try:
        for cur in con.execute_string(sql, remove_comments=False):
            cur.fetchall()
    finally:
        con.close()
    print(f"ran setup.sql + registered RSA public key on {c['svc_user']} ✓")


def upsert_secret(c: dict, private_pem: str) -> str:
    payload = {
        "account": c["account"],
        "host": c["host"],
        "user": c["svc_user"],
        "role": c["ro_role"],
        "warehouse": c["warehouse"],
        "database": c["database"],
        "schema": c["schema"],
        "private_key_pem": private_pem,
    }
    sm = boto3.client("secretsmanager", region_name=c["region"])
    body = json.dumps(payload)
    try:
        arn = sm.create_secret(
            Name=c["secret_name"],
            Description="Snowflake key-pair creds for the order-triage agent",
            SecretString=body,
        )["ARN"]
        print(f"created Secrets Manager secret {c['secret_name']}")
    except sm.exceptions.ResourceExistsException:
        arn = sm.put_secret_value(SecretId=c["secret_name"], SecretString=body)["ARN"]
        print(f"updated Secrets Manager secret {c['secret_name']}")
    return arn


def _keypair_jwt(account: str, user: str, private_pem: str) -> str:
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    fp = "SHA256:" + base64.b64encode(hashlib.sha256(der).digest()).decode()
    now = int(time.time())
    return jwt.encode(
        {"iss": f"{account}.{user}.{fp}", "sub": f"{account}.{user}", "iat": now, "exp": now + 300},
        key,
        algorithm="RS256",
    )


def verify(account, host, user, role, warehouse, database, schema, private_pem) -> None:
    """Sign a KEYPAIR_JWT as the service user and run a test SELECT via the Snowflake
    SQL REST API — the exact path the snowflake-query Lambda uses."""
    token = _keypair_jwt(account, user, private_pem)
    body = json.dumps(
        {
            "statement": f"SELECT COUNT(*) AS N FROM {database}.{schema}.ORDERS",
            "timeout": 60,
            "warehouse": warehouse,
            "role": role,
            "database": database,
            "schema": schema,
        }
    ).encode()
    req = urllib.request.Request(
        f"https://{host}/api/v2/statements",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    rows = data.get("data", [["?"]])[0][0]
    print(f"verify ✓ service user {user} read {database}.{schema}.ORDERS: {rows} rows")


def main() -> None:
    ap = argparse.ArgumentParser(description="Bootstrap Snowflake for the order-triage demo.")
    ap.add_argument(
        "--verify",
        action="store_true",
        help="only verify the existing setup (read the secret + run a test query); make no changes",
    )
    args = ap.parse_args()
    c = config()

    if args.verify:
        sm = boto3.client("secretsmanager", region_name=c["region"])
        s = json.loads(sm.get_secret_value(SecretId=c["secret_name"])["SecretString"])
        verify(
            s["account"], s["host"], s["user"], s["role"],
            s["warehouse"], s["database"], s["schema"], s["private_key_pem"],
        )
        return

    if not (c["account"] and c["admin_user"]):
        sys.exit(
            "error: SNOWFLAKE_ACCOUNT and SNOWFLAKE_ADMIN_USER are required for setup. "
            "Set SNOWFLAKE_HOST too unless an externalbrowser login can derive it from "
            "the account (--verify reads them from the secret)."
        )

    private_pem, public_b64 = gen_or_load_keypair(c["key_dir"])
    run_admin_sql(c, public_b64)
    upsert_secret(c, private_pem)
    time.sleep(2)  # brief pause for key propagation
    verify(
        c["account"], c["host"], c["svc_user"], c["ro_role"],
        c["warehouse"], c["database"], c["schema"], private_pem,
    )
    print(
        f"\nSnowflake bootstrap complete. The snowflake-query Lambda reads the secret "
        f"'{c['secret_name']}'. Run `make deploy` (or re-apply) if it isn't deployed yet."
    )


if __name__ == "__main__":
    main()

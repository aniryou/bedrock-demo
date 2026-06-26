"""Snowflake SQL REST API client (key-pair / KEYPAIR_JWT auth).

Reads connection config from an AWS Secrets Manager secret (JSON), signs an
RS256 KEYPAIR_JWT, and calls the Snowflake SQL REST API
(``/api/v2/statements``). The config + a lightweight "connection" (just the
parsed config) are cached at module level so warm Lambda invocations reuse them.

All user-supplied filter values are passed through parameterized ``?`` bindings
to avoid SQL injection. The AGENT_RO role is SELECT-only on ORDERS/CUSTOMERS, so
this path is read-only at the database level too.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

# boto3 / jwt / cryptography are bundled into the Lambda artifact but not the dev
# venv; import them lazily at their call sites so the module is unit-testable without
# AWS/crypto deps (the SQL-API path is mocked in tests).

# ---------------------------------------------------------------------------
# Config / connection cache (module level so warm Lambdas reuse it).
# ---------------------------------------------------------------------------
_CONFIG: dict | None = None


def _load_config() -> dict:
    """Fetch + parse the Snowflake secret from Secrets Manager (cached)."""
    import boto3  # lazy: runtime-only (Lambda), not needed for unit tests

    global _CONFIG
    if _CONFIG is None:
        secret_id = os.environ["SNOWFLAKE_SECRET_NAME"]
        resp = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
        _CONFIG = json.loads(resp["SecretString"])
    return _CONFIG


# ---------------------------------------------------------------------------
# KEYPAIR_JWT signing + SQL REST API call.
# ---------------------------------------------------------------------------
def _jwt(cfg: dict) -> str:
    import jwt  # lazy: runtime-only (Lambda), not needed for unit tests
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(cfg["private_key_pem"].encode(), password=None)
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    fp = "SHA256:" + base64.b64encode(hashlib.sha256(der).digest()).decode()
    acct = cfg["account"].upper()
    user = cfg["user"].upper()
    now = int(time.time())
    return jwt.encode(
        {
            "iss": f"{acct}.{user}.{fp}",
            "sub": f"{acct}.{user}",
            "iat": now,
            "exp": now + 300,
        },
        key,
        algorithm="RS256",
    )


def query(
    cfg: dict, statement: str, bindings: dict | None = None, oauth_token: str | None = None
) -> list[dict]:
    """Run a SQL statement against the Snowflake SQL REST API; return list of row dicts.

    Service path (``oauth_token`` is None): sign a KEYPAIR_JWT as the service user
    and request its configured role. User path (``oauth_token`` set): present the
    per-user OBO / External-OAuth bearer with token-type OAUTH and OMIT the role, so
    Snowflake maps the token to the user and runs under THAT user's RBAC via the user's
    DEFAULT_ROLE. The token's ``scp`` must carry ``session:role-any`` (or
    ``session:role:<ROLE>``) with ANY_ROLE_MODE=ENABLE — Snowflake's AZURE handler does
    NOT parse ``session:scope:<ROLE>`` (error 390317). Omitting the role keeps this path
    role-agnostic so the user's Snowflake grants alone decide.
    """
    body = {
        "statement": statement,
        "timeout": 60,
        "warehouse": cfg["warehouse"],
        "database": cfg["database"],
        "schema": cfg["schema"],
    }
    if oauth_token is None:
        body["role"] = cfg["role"]
        authorization = f"Bearer {_jwt(cfg)}"
        token_type = "KEYPAIR_JWT"
    else:
        authorization = f"Bearer {oauth_token}"
        token_type = "OAUTH"
    if bindings:
        body["bindings"] = bindings
    req = urllib.request.Request(
        f"https://{cfg['host']}/api/v2/statements",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": authorization,
            "X-Snowflake-Authorization-Token-Type": token_type,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "order-triage/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    cols = [c["name"].lower() for c in d.get("resultSetMetaData", {}).get("rowType", [])]
    return [dict(zip(cols, row, strict=False)) for row in d.get("data", [])]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _num(value):
    """The SQL API returns numerics as strings; coerce to int/float (None-safe)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    return int(f) if f.is_integer() else f


def _bind(value) -> dict:
    return {"type": "TEXT", "value": str(value)}


def _order_row(r: dict) -> dict:
    return {
        "order_id": r.get("order_id"),
        "customer_id": r.get("customer_id"),
        "customer_name": r.get("customer_name"),
        "customer_tier": r.get("customer_tier"),
        "customer_region": r.get("customer_region"),
        "customer_credit_limit": _num(r.get("customer_credit_limit")),
        "amount": _num(r.get("amount")),
        "status": r.get("status"),
        "channel": r.get("channel"),
        "region": r.get("region"),
        "created_at": r.get("created_at"),
    }


def _customer_row(r: dict) -> dict:
    return {
        "customer_id": r.get("customer_id"),
        "name": r.get("name"),
        "tier": r.get("tier"),
        "region": r.get("region"),
        "credit_limit": _num(r.get("credit_limit")),
    }


# ---------------------------------------------------------------------------
# Typed query helpers
# ---------------------------------------------------------------------------
_ORDER_SELECT = """
SELECT
  o.order_id            AS order_id,
  o.customer_id         AS customer_id,
  c.name                AS customer_name,
  c.tier                AS customer_tier,
  c.region              AS customer_region,
  c.credit_limit        AS customer_credit_limit,
  o.amount              AS amount,
  o.status              AS status,
  o.channel             AS channel,
  o.region              AS region,
  TO_CHAR(o.created_at, 'YYYY-MM-DD') AS created_at
FROM ORDERS o
LEFT JOIN CUSTOMERS c USING (customer_id)
"""


def list_orders(
    status: str | None = None,
    channel: str | None = None,
    tier: str | None = None,
    min_amount: float | None = None,
    oauth_token: str | None = None,
) -> list[dict]:
    """List orders joined to their customer, with optional filters.

    Filter values are passed as parameterized bindings (SQL-injection safe).
    """
    cfg = _load_config()
    clauses: list[str] = []
    bindings: dict[str, dict] = {}
    idx = 1
    if status is not None:
        clauses.append("UPPER(o.status) = UPPER(?)")
        bindings[str(idx)] = _bind(status)
        idx += 1
    if channel is not None:
        clauses.append("UPPER(o.channel) = UPPER(?)")
        bindings[str(idx)] = _bind(channel)
        idx += 1
    if tier is not None:
        clauses.append("UPPER(c.tier) = UPPER(?)")
        bindings[str(idx)] = _bind(tier)
        idx += 1
    if min_amount is not None:
        clauses.append("o.amount >= ?")
        bindings[str(idx)] = {"type": "REAL", "value": str(min_amount)}
        idx += 1

    sql = _ORDER_SELECT
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY o.created_at DESC"

    rows = query(cfg, sql, bindings or None, oauth_token=oauth_token)
    return [_order_row(r) for r in rows]


def get_order(order_id: str, oauth_token: str | None = None) -> dict | None:
    """Fetch a single order (joined to customer) by order_id, or None."""
    cfg = _load_config()
    sql = _ORDER_SELECT + " WHERE o.order_id = ?"
    rows = query(cfg, sql, {"1": _bind(order_id)}, oauth_token=oauth_token)
    return _order_row(rows[0]) if rows else None


_CUSTOMER_SELECT = """
SELECT
  customer_id   AS customer_id,
  name          AS name,
  tier          AS tier,
  region        AS region,
  credit_limit  AS credit_limit
FROM CUSTOMERS
"""


def list_customers(oauth_token: str | None = None) -> list[dict]:
    """List all customers (master data), ordered by id.

    Called by the agent under its own (service) identity — customer data is
    non-confidential, so it stays accessible regardless of the signed-in user.
    """
    cfg = _load_config()
    rows = query(cfg, _CUSTOMER_SELECT + " ORDER BY customer_id", oauth_token=oauth_token)
    return [_customer_row(r) for r in rows]


def get_customer(customer_id: str, oauth_token: str | None = None) -> dict | None:
    """Fetch a single customer by customer_id, or None."""
    cfg = _load_config()
    rows = query(cfg, _CUSTOMER_SELECT + " WHERE customer_id = ?", {"1": _bind(customer_id)}, oauth_token=oauth_token)
    return _customer_row(rows[0]) if rows else None

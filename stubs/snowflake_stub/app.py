"""Snowflake-backed read-only orders/customers API (AgentCore Gateway target).

A Gateway OpenAPI target (alongside the SAP + order-actions stubs). It runs locally
(``uvicorn snowflake_stub.app:app``) or as a Lambda Function URL behind the Gateway,
and every data route selects one of two identity paths from the inbound credential
(see ``_authorize``):

- **User (OBO) path** — a forwarded ``Authorization: Bearer <token>`` (injected by the
  Gateway's OBO credential provider) is presented to Snowflake with token-type OAUTH;
  Snowflake validates it and enforces THAT human's RBAC, so Snowflake is the real
  authorization boundary.
- **Service path** — otherwise a valid ``X-API-Key`` selects the agent's own identity
  and signs a key-pair ``KEYPAIR_JWT`` as the SELECT-only ``AGENT_RO`` role.

Either way the access is read-only at the database level.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException, Query

from snowflake_stub import snowflake_client

API_KEY = os.environ.get("SNOWFLAKE_API_KEY", "dev-sap-key")

app = FastAPI(title="Snowflake Orders API", version="1.0.0")


def _check_key(x_api_key: str | None) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


def _authorize(x_api_key: str | None, authorization: str | None) -> str | None:
    """Return the per-user OAuth token to present to Snowflake (user path), or None
    for the service / key-pair path.

    A forwarded ``Authorization: Bearer <token>`` (injected by the Gateway's OBO
    credential provider on the privileged target) selects the user path — Snowflake
    then validates the token and enforces THAT user's RBAC, so Snowflake is the real
    authorization boundary. Otherwise a valid ``X-API-Key`` selects the service
    (AGENT_RO, key-pair) path.
    """
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    _check_key(x_api_key)
    return None


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/orders")
def get_orders(
    status: str | None = Query(default=None),
    channel: str | None = Query(default=None),
    tier: str | None = Query(default=None),
    min_amount: float | None = Query(default=None),
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> list[dict]:
    """List orders (joined to customer) with optional filters.

    Service path requires X-API-Key; a forwarded user bearer impersonates the user
    (so Snowflake RBAC/RLS scopes the rows to that human).
    """
    token = _authorize(x_api_key, authorization)
    return snowflake_client.list_orders(
        status=status, channel=channel, tier=tier, min_amount=min_amount, oauth_token=token
    )


@app.get("/orders/{order_id}")
def get_order(
    order_id: str,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    """Get a single order by id. 404 if unknown."""
    token = _authorize(x_api_key, authorization)
    order = snowflake_client.get_order(order_id, oauth_token=token)
    if order is None:
        raise HTTPException(status_code=404, detail=f"no such order {order_id}")
    return order


@app.get("/customers")
def get_customers(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> list[dict]:
    """List all customers (master data).

    Called by the agent under its own (service) identity — customer data is
    non-confidential, so it stays accessible regardless of the signed-in user.
    """
    token = _authorize(x_api_key, authorization)
    return snowflake_client.list_customers(oauth_token=token)


@app.get("/customers/{customer_id}")
def get_customer(
    customer_id: str,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    """Get a single customer by id. 404 if unknown."""
    token = _authorize(x_api_key, authorization)
    customer = snowflake_client.get_customer(customer_id, oauth_token=token)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"no such customer {customer_id}")
    return customer

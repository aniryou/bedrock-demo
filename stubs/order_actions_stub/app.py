"""Dummy order-actions API — records order flags for human review.

A second AgentCore **Gateway** target (alongside the SAP stub). Like the SAP stub,
inbound access is gated by the Lambda Function URL's IAM authorization
(`AuthType=AWS_IAM`, SigV4 from the Gateway's execution role); it runs locally
(`make order-actions`) or as a Lambda Function URL behind the Gateway. Its *outbound*
call to the Snowflake data Lambda uses an `X-API-Key` (that URL stays AuthType=NONE).

**Authorization** (who may flag) is enforced by the **Cedar policy on the Gateway**
(`orders___flagOrder`), not here. This service only enforces the business rule (only
OPEN orders can be flagged) and records the flag.
"""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI
from pydantic import BaseModel


def _status(order_id: str) -> str | None:
    # Order status comes from the Snowflake data Lambda over HTTP.
    # Returns None when the order does not exist.
    base_url = os.environ["SNOWFLAKE_DATA_URL"].rstrip("/")
    api_key = os.environ["SNOWFLAKE_API_KEY"]
    resp = httpx.get(
        f"{base_url}/orders/{order_id}",
        headers={"X-API-Key": api_key},
        timeout=10.0,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    row = resp.json()
    return row["status"].upper()


app = FastAPI(title="Order Actions API", version="1.0.0")


class FlagRequest(BaseModel):
    reason: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/orders/{order_id}/flag")
def flag_order(order_id: str, body: FlagRequest) -> dict:
    """Flag an OPEN order for review. Refuses non-OPEN orders."""
    status = _status(order_id)
    if status is None:
        return {"flagged": False, "order_id": order_id, "message": f"No such order {order_id}."}
    if status != "OPEN":
        return {
            "flagged": False,
            "order_id": order_id,
            "status": status,
            "message": f"Order {order_id} is {status}, not OPEN — refusing to flag.",
        }
    return {
        "flagged": True,
        "order_id": order_id,
        "status": status,
        "reason": body.reason,
        "message": f"Order {order_id} flagged for review: {body.reason}",
    }

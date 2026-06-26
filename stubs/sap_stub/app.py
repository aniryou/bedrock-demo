"""Dummy SAP API — a tiny stand-in for an SAP credit service.

This is the **Gateway** target and the thing the agent reaches with **outbound
Identity** auth. Inbound access is gated by the Lambda Function URL's IAM authorization
(`AuthType=AWS_IAM`): the AgentCore Gateway SigV4-signs each call with its execution
role, so there is no app-layer API key. It runs locally (`make sap`) and deploys as a
Lambda Function URL behind an AgentCore Gateway OpenAPI target, deployed by the
**bedrock-demo-infra** repo (see `sap_stub/lambda_handler.py`).
"""

from __future__ import annotations

from fastapi import FastAPI

# Deterministic in-memory "SAP" credit data — a separate system from the orders DB.
_CREDIT = {
    "C-001": {"on_hold": False, "available_credit": 488_000, "balance": 12_000},
    "C-002": {"on_hold": True, "available_credit": 0, "balance": 50_000},
    "C-003": {"on_hold": False, "available_credit": -15_000, "balance": 45_000},
    "C-004": {"on_hold": False, "available_credit": 745_000, "balance": 5_000},
    "C-005": {"on_hold": False, "available_credit": 120_000, "balance": 30_000},
    "C-006": {"on_hold": True, "available_credit": -2_000, "balance": 22_000},
}

app = FastAPI(title="Dummy SAP API", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/credit-status/{customer_id}")
def credit_status(customer_id: str) -> dict:
    """Return the SAP credit status for a customer."""
    record = _CREDIT.get(customer_id)
    if record is None:
        return {
            "customer_id": customer_id,
            "known": False,
            "on_hold": False,
            "available_credit": 0,
            "currency": "USD",
        }
    return {
        "customer_id": customer_id,
        "known": True,
        "currency": "USD",
        **record,
    }

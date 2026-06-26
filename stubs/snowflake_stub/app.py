"""Snowflake analytics API (AgentCore Gateway target).

One agent tool: ``POST /ask {question}`` — **user (OBO) only**. The forwarded
``Authorization: Bearer`` (injected by the Gateway's OBO credential provider) runs the
Cortex-generated SQL as that user, so the row-access policy scopes the rows. A missing
bearer is a 401: RLS is meaningless without a real user.
"""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from snowflake_stub import snowflake_client

app = FastAPI(title="Snowflake Analytics API", version="2.0.0")


class AskRequest(BaseModel):
    question: str


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/ask")
def ask(body: AskRequest, authorization: str | None = Header(default=None)) -> dict:
    """NL question about orders/customers -> governed SQL over ORDERS_SV, run as the user."""
    if not (authorization and authorization.lower().startswith("bearer ")):
        raise HTTPException(status_code=401, detail="missing user bearer token (OBO required)")
    return snowflake_client.ask(body.question, oauth_token=authorization[7:].strip())

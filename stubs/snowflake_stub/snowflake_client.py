"""Snowflake data tool — Cortex Analyst ``/ask`` over the ``ORDERS_SV`` semantic view.

Cortex Analyst turns the natural-language question into SQL over the semantic view, then the
SQL API runs it. Both calls carry the same per-user OBO bearer (token-type ``OAUTH``), so the
query runs in the user's Snowflake context and the row-access policy scopes the rows.
"""

from __future__ import annotations

import json
import os
import urllib.request


def _config() -> dict:
    import boto3  # lazy: runtime-only (Lambda), not needed for unit tests

    resp = boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["SNOWFLAKE_SECRET_NAME"]
    )
    return json.loads(resp["SecretString"])


def _post(host: str, path: str, body: dict, oauth_token: str) -> dict:
    """One Snowflake REST POST as the signed-in user (token-type OAUTH)."""
    req = urllib.request.Request(
        f"https://{host}{path}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {oauth_token}",
            "X-Snowflake-Authorization-Token-Type": "OAUTH",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=65) as r:
        return json.load(r)


def ask(question: str, oauth_token: str) -> dict:
    """Answer an NL question: Cortex Analyst generates SQL over ``ORDERS_SV``, then run it
    under the same OBO token so RLS scopes the rows. Returns
    ``{question, sql, rows, row_count, explanation}``."""
    cfg = _config()
    host = cfg["host"]
    view = cfg.get("semantic_view") or f"{cfg['database']}.{cfg['schema']}.ORDERS_SV"

    reply = _post(
        host,
        "/api/v2/cortex/analyst/message",
        {
            "semantic_view": view,
            "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
            "stream": False,
        },
        oauth_token,
    )
    content = (reply.get("message") or {}).get("content", [])
    sql = next((p.get("statement") for p in content if p.get("type") == "sql"), None)
    explanation = " ".join(
        p["text"] for p in content if p.get("type") == "text" and p.get("text")
    ).strip()

    rows: list[dict] = []
    if sql:
        d = _post(
            host,
            "/api/v2/statements",
            {
                "statement": sql,
                "timeout": 60,
                "warehouse": cfg["warehouse"],
                "database": cfg["database"],
                "schema": cfg["schema"],
            },
            oauth_token,
        )
        cols = [c["name"].lower() for c in d.get("resultSetMetaData", {}).get("rowType", [])]
        rows = [dict(zip(cols, row, strict=False)) for row in d.get("data", [])]

    return {
        "question": question,
        "sql": sql,
        "rows": rows,
        "row_count": len(rows),
        "explanation": explanation,
    }

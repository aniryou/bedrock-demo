"""snowflake_stub — Cortex Analyst ``/ask`` (hermetic; Snowflake REST mocked).

``POST /ask`` is OBO-only, and ``ask()`` chains Cortex Analyst -> SQL under the same user token.
"""

from fastapi.testclient import TestClient

from snowflake_stub import snowflake_client as sc
from snowflake_stub.app import app

client = TestClient(app)


def test_ask_requires_user_bearer():
    # No bearer -> 401 (no service fallback; RLS needs a real user).
    assert client.post("/ask", json={"question": "show orders"}).status_code == 401


def test_ask_chains_analyst_then_sql(monkeypatch):
    monkeypatch.setattr(
        sc, "_config", lambda: {"host": "h", "warehouse": "W", "database": "D", "schema": "S"}
    )
    seen = []

    def fake_post(host, path, body, oauth_token):
        seen.append((path, oauth_token))
        if "analyst" in path:
            return {
                "message": {
                    "content": [
                        {"type": "text", "text": "Open orders."},
                        {"type": "sql", "statement": "SELECT order_id FROM ORDERS"},
                    ]
                }
            }
        return {"resultSetMetaData": {"rowType": [{"name": "ORDER_ID"}]}, "data": [["O-1"]]}

    monkeypatch.setattr(sc, "_post", fake_post)

    r = client.post(
        "/ask", json={"question": "open orders"}, headers={"Authorization": "Bearer u-tok"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sql"] == "SELECT order_id FROM ORDERS"
    assert body["rows"] == [{"order_id": "O-1"}]
    assert body["row_count"] == 1
    assert body["explanation"] == "Open orders."
    # Analyst then SQL API, both carrying the user's OBO token.
    assert [p for p, _ in seen] == ["/api/v2/cortex/analyst/message", "/api/v2/statements"]
    assert all(tok == "u-tok" for _, tok in seen)

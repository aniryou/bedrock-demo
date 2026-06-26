"""Snowflake stub — service (key-pair) vs user (OBO/OAUTH) path selection.

Hermetic: the SQL REST call and JWT signing are mocked, so no Snowflake or key is
needed. Proves the user path presents the forwarded bearer with token-type OAUTH and
omits the body role (the login role must come from the token's scp claim), while the
service path uses KEYPAIR_JWT + the AGENT_RO role.
"""

import io
import json

from fastapi.testclient import TestClient

from snowflake_stub import snowflake_client as sc
from snowflake_stub.app import app as sf_app

sf = TestClient(sf_app)


def test_query_service_vs_user_path(monkeypatch):
    cap = {}

    class FakeReq:
        def __init__(self, url, data=None, method=None, headers=None):
            cap["headers"] = headers or {}
            cap["body"] = json.loads(data.decode()) if data else {}

    monkeypatch.setattr(sc.urllib.request, "Request", FakeReq)
    monkeypatch.setattr(
        sc.urllib.request,
        "urlopen",
        lambda req, timeout=None: io.BytesIO(b'{"data":[],"resultSetMetaData":{"rowType":[]}}'),
    )
    monkeypatch.setattr(sc, "_jwt", lambda cfg: "kp-jwt")
    cfg = {"host": "h", "warehouse": "W", "role": "AGENT_RO", "database": "D", "schema": "S"}

    sc.query(cfg, "select 1")
    assert cap["headers"]["X-Snowflake-Authorization-Token-Type"] == "KEYPAIR_JWT"
    assert cap["headers"]["Authorization"] == "Bearer kp-jwt"
    assert cap["body"]["role"] == "AGENT_RO"

    sc.query(cfg, "select 1", oauth_token="user-tok")
    assert cap["headers"]["X-Snowflake-Authorization-Token-Type"] == "OAUTH"
    assert cap["headers"]["Authorization"] == "Bearer user-tok"
    assert "role" not in cap["body"]  # role MUST come from the token scp claim


def test_app_routes_user_vs_service(monkeypatch):
    cap = {}
    monkeypatch.setattr(sc, "list_orders", lambda **kw: cap.update(kw) or [])

    assert sf.get("/orders", headers={"X-API-Key": "dev-sap-key"}).status_code == 200
    assert cap.get("oauth_token") is None  # service path

    cap.clear()
    assert sf.get("/orders", headers={"Authorization": "Bearer user-tok"}).status_code == 200
    assert cap.get("oauth_token") == "user-tok"  # user path

    assert sf.get("/orders").status_code == 401  # neither credential


def test_customers_list_routes_user_vs_service(monkeypatch):
    cap = {}
    monkeypatch.setattr(sc, "list_customers", lambda **kw: cap.update(kw) or [])

    r = sf.get("/customers", headers={"X-API-Key": "dev-sap-key"})
    assert r.status_code == 200
    assert cap.get("oauth_token") is None  # agent/service path

    cap.clear()
    r = sf.get("/customers", headers={"Authorization": "Bearer user-tok"})
    assert r.status_code == 200
    assert cap.get("oauth_token") == "user-tok"  # user path


def test_list_customers_num_coercion(monkeypatch):
    def fake_query(cfg, statement, bindings=None, oauth_token=None):
        return [{
            "customer_id": "C-001", "name": "Acme", "tier": "enterprise",
            "region": "NA", "credit_limit": "500000",
        }]

    monkeypatch.setattr(sc, "query", fake_query)
    monkeypatch.setattr(
        sc, "_load_config",
        lambda: {"host": "h", "warehouse": "W", "role": "R", "database": "D", "schema": "S"},
    )

    custs = sc.list_customers()
    assert custs[0]["customer_id"] == "C-001"
    assert custs[0]["credit_limit"] == 500000  # _num coerces the string to int

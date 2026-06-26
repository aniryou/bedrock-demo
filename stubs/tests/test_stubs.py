"""Hermetic tests for both stub services (FastAPI TestClient, no running server).

Inbound auth for the deployed stubs is the Lambda Function URL's IAM authorization
(SigV4 from the Gateway's execution role), enforced by AWS at the URL edge — there is
no app-layer API key to exercise here. These tests cover the data + business-rule paths.
"""

import httpx
from fastapi.testclient import TestClient

from order_actions_stub import app as orders_module
from order_actions_stub.app import app as orders_app
from sap_stub.app import app as sap_app

sap = TestClient(sap_app)
orders = TestClient(orders_app)

# order_actions reads order status from the Snowflake data service over HTTP
# (order_actions_stub.app._status). Stub that call so the flag business-rule test
# stays hermetic — no running Snowflake service or network access required.
_ORDER_STATUS = {"O-1003": "OPEN", "O-1005": "SHIPPED"}


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


def _fake_snowflake_get(url, headers=None, timeout=None):
    order_id = url.rstrip("/").rsplit("/", 1)[-1]
    if order_id not in _ORDER_STATUS:
        return _FakeResponse(404, {})
    return _FakeResponse(200, {"status": _ORDER_STATUS[order_id]})


def test_sap_credit_status():
    assert sap.get("/credit-status/C-002").json()["on_hold"] is True
    assert sap.get("/credit-status/C-001").json()["on_hold"] is False


def test_orders_flag_open_and_refuse_non_open(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_DATA_URL", "http://snowflake.test")
    monkeypatch.setenv("SNOWFLAKE_API_KEY", "dev-sap-key")
    monkeypatch.setattr(orders_module.httpx, "get", _fake_snowflake_get)

    ok = orders.post("/orders/O-1003/flag", json={"reason": "exposure"}).json()
    assert ok["flagged"] is True
    refused = orders.post("/orders/O-1005/flag", json={"reason": "x"}).json()  # SHIPPED
    assert refused["flagged"] is False

"""Order-triage OBO demo — minimal chat web app.

A thin client for the AgentCore **OBO runtime**: it signs the human into Microsoft
Entra (auth-code), then proxies chat messages to the runtime carrying that user's
JWT — so the agent impersonates the signed-in user and Snowflake RBAC/RLS decides
what they can see.

Local-first: ``uvicorn app.main:app --port 8000``. Config comes from
``bedrock-demo/.env`` (shared Entra app config + secret) plus a webapp-local
``.env`` for the per-deploy bits (the OBO runtime ARN, redirect URI). No AWS
credentials are needed — the runtime call carries only the user bearer.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from .agentcore import stream_agent
from .entra import authorize_url, decode_id_claims, exchange_code

ROOT = Path(__file__).resolve().parents[1]  # app/
WEB = ROOT / "web"

# Shared config + secret from bedrock-demo/.env (read literally — python-dotenv
# does NOT tilde-expand, so the ``~``-leading client secret is safe here), then a
# webapp-local .env for per-deploy overrides (OBO_RUNTIME_ARN, redirect URI).
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env", override=True)

TENANT = os.environ.get("ENTRA_TENANT_ID", "")
CLIENT_ID = os.environ.get("ENTRA_AGENT_APP_ID", "")
CLIENT_SECRET = os.environ.get("ENTRA_AGENT_CLIENT_SECRET", "")
SCOPE = os.environ.get("ENTRA_AGENT_SCOPE", f"api://{CLIENT_ID}/access_as_user")
REDIRECT_URI = os.environ.get("WEBAPP_REDIRECT_URI", "http://localhost:8000/callback")
OBO_RUNTIME_ARN = os.environ.get("OBO_RUNTIME_ARN", "")
REGION = os.environ.get("AWS_REGION", "us-west-2")

COOKIE = "otsession"
STATE_COOKIE = "otstate"
_SESSIONS: dict[str, dict] = {}  # opaque cookie id -> session (in-memory; demo-only)

app = FastAPI(title="Order Triage — OBO demo")
log = logging.getLogger("order_triage_webapp")


def _session(request: Request) -> dict | None:
    sid = request.cookies.get(COOKIE)
    return _SESSIONS.get(sid) if sid else None


def _config_problem() -> str | None:
    missing = [
        name
        for name, val in [
            ("ENTRA_TENANT_ID", TENANT),
            ("ENTRA_AGENT_APP_ID", CLIENT_ID),
            ("ENTRA_AGENT_CLIENT_SECRET", CLIENT_SECRET),
        ]
        if not val
    ]
    return f"missing config: {', '.join(missing)}" if missing else None


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "config_problem": _config_problem(), "runtime_set": bool(OBO_RUNTIME_ARN)}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (WEB / "index.html").read_text()


@app.get("/me")
def me(request: Request) -> dict:
    s = _session(request)
    if not s:
        return {"authed": False, "config_problem": _config_problem(), "runtime_set": bool(OBO_RUNTIME_ARN)}
    return {"authed": True, "name": s.get("name"), "email": s.get("email")}


@app.get("/login")
def login() -> RedirectResponse:
    if _config_problem():
        raise HTTPException(500, _config_problem())
    state = secrets.token_urlsafe(16)
    resp = RedirectResponse(authorize_url(TENANT, CLIENT_ID, REDIRECT_URI, SCOPE, state))
    resp.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax")
    return resp


@app.get("/callback", response_class=HTMLResponse)
def callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    if error:
        return HTMLResponse(
            f"<h3>Sign-in failed</h3><pre>{error}: {error_description}</pre><a href='/'>back</a>",
            status_code=400,
        )
    if not code or not state or state != request.cookies.get(STATE_COOKIE):
        raise HTTPException(400, "invalid auth state (possible CSRF or expired login)")

    tok = exchange_code(TENANT, CLIENT_ID, CLIENT_SECRET, code, REDIRECT_URI, SCOPE)
    claims = decode_id_claims(tok.get("id_token", ""))
    sid = secrets.token_urlsafe(24)
    _SESSIONS[sid] = {
        "access_token": tok["access_token"],
        "expires_at": time.time() + int(tok.get("expires_in", 3600)),
        "name": claims.get("name") or claims.get("preferred_username") or "user",
        "email": claims.get("preferred_username") or claims.get("email") or claims.get("upn"),
        "runtime_session": "webapp-" + secrets.token_hex(20),  # >= 33 chars
    }
    resp = RedirectResponse("/")
    resp.set_cookie(COOKIE, sid, httponly=True, samesite="lax")
    resp.delete_cookie(STATE_COOKIE)
    return resp


@app.post("/logout")
def logout(request: Request) -> JSONResponse:
    sid = request.cookies.get(COOKIE)
    if sid:
        _SESSIONS.pop(sid, None)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


@app.post("/chat")
async def chat(request: Request) -> StreamingResponse:
    """Stream the agent's reply as newline-delimited JSON events.

    The client reads these incrementally so tokens render as they're generated.
    Each line is one event: ``{"type":"delta","text":...}`` for an answer chunk,
    ``{"type":"step","step":{...}}`` for an agent step, ``{"type":"error",
    "detail":...}`` if the upstream call fails mid-stream, and a final
    ``{"type":"done"}``. Pre-flight failures (auth, config) still return a normal
    HTTP error *before* the stream opens, so the client can show them plainly.
    """
    s = _session(request)
    if not s:
        raise HTTPException(401, "not signed in")
    if not OBO_RUNTIME_ARN:
        raise HTTPException(
            500,
            "OBO_RUNTIME_ARN is not set. Bring the stack up "
            "(cd ../infra && make deploy && make ingest), then run "
            "`terraform -chdir=../infra/terraform output -raw agent_runtime_arn` and set it as "
            "OBO_RUNTIME_ARN in app/.env.",
        )
    if time.time() > s["expires_at"] - 30:
        raise HTTPException(401, "session expired — please sign in again")

    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "empty message")

    async def events():
        try:
            async for kind, value in stream_agent(
                REGION, OBO_RUNTIME_ARN, s["access_token"], s["runtime_session"], message
            ):
                if kind == "delta":
                    yield json.dumps({"type": "delta", "text": value}) + "\n"
                elif kind == "step":  # tool_call / tool_result / reason — the audit timeline
                    yield json.dumps({"type": "step", "step": value}) + "\n"
        except Exception:  # noqa: BLE001 - log server-side; never leak the upstream body to the UI
            # The exception can carry the raw runtime error body (agentcore.py truncates it
            # into the RuntimeError). Keep that server-side only; the session id is an opaque
            # hex (see /callback), safe for correlation. The browser gets a generic message.
            log.exception("agent invocation failed (session=%s)", s["runtime_session"])
            yield json.dumps({"type": "error", "detail": "agent invocation failed — please try again"}) + "\n"
        else:
            yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        # Defeat any intermediary buffering so chunks reach the browser as they're produced.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

"""Microsoft Entra auth-code helpers (confidential client).

The agent app is a *confidential* client (it has a client secret), so the
auth-code → token exchange happens here, server-side. The access token we get
back has ``aud = api://<agent app>`` (from the ``access_as_user`` scope) — that
is exactly the inbound JWT the OBO runtime's CUSTOM_JWT authorizer expects.

No MSAL dependency: this is plain OAuth2 over httpx, mirroring the proven
auth-code + loopback recipe from the OBO handover.
"""

from __future__ import annotations

import base64
import binascii
import json
from urllib.parse import urlencode

import httpx

_AUTHORITY = "https://login.microsoftonline.com"


def authorize_url(tenant: str, client_id: str, redirect_uri: str, scope: str, state: str) -> str:
    """Build the Entra authorize URL for the auth-code flow."""
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": f"{scope} openid profile email",
            "state": state,
        }
    )
    return f"{_AUTHORITY}/{tenant}/oauth2/v2.0/authorize?{query}"


def exchange_code(
    tenant: str, client_id: str, client_secret: str, code: str, redirect_uri: str, scope: str
) -> dict:
    """Exchange an auth code for tokens. Returns the raw token response JSON.

    ``client_secret`` is passed in the form body (never via the shell), so the
    ``~``-leading secret is used literally — none of the ``source .env`` tilde-
    expansion landmine applies here.
    """
    resp = httpx.post(
        f"{_AUTHORITY}/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "scope": f"{scope} openid profile email",
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    return resp.json()


def decode_id_claims(id_token: str) -> dict:
    """Decode (WITHOUT verifying) an id_token's claims for display only.

    Entra already issued these over TLS; we read name/email purely to label the
    signed-in user in the UI, never for an authorization decision.
    """
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, binascii.Error, json.JSONDecodeError):
        return {}

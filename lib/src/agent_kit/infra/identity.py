"""Per-request user identity — the inbound on-behalf-of (OBO) bearer.

Under the CUSTOM_JWT Gateway inbound the runtime stores the verified user's JWT here for
the duration of one invocation; the Gateway client ([gateway.py]) forwards it as the
Gateway's bearer, and the Gateway brokers the per-user on-behalf-of token
(grant_type=TOKEN_EXCHANGE) so the backends enforce that user's RBAC.

The runtime makes no authorization decision itself. It does, however, read the token's
`sub` (subject) claim to use as the AgentCore Memory `actor_id`, so each user gets their
own facts/preferences/summaries namespace (see memory.py, ADR-0002). It also reads the
`oid` (directory object id) purely as a telemetry field for render-time actor resolution
(the `oid` is Graph-resolvable; the pairwise `sub` is not). That read decodes the
payload WITHOUT re-verifying the signature: the AgentCore CUSTOM_JWT authorizer already
verified the token before the runtime saw it, and the subject is used only as a memory
partition key, never to authorize. Authorization remains the Gateway/Cedar and the
resource (Snowflake/SAP) RBAC's job.
"""

from __future__ import annotations

import base64
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass

_LOG = logging.getLogger("agent_kit.identity")

# The shared, non-user-specific memory actor used when no verified user subject is
# available (e.g. a token without `sub`/`oid`, or a malformed one) — a shared namespace
# rather than failing the turn.
ANONYMOUS_ACTOR = "anonymous"


@dataclass(frozen=True)
class UserIdentity:
    raw_jwt: str
    subject: str | None = None  # Entra `sub` (fallback `oid`); the memory actor_id
    oid: str | None = None  # Entra `oid` (directory object id); Graph-resolvable, telemetry only


_current: ContextVar[UserIdentity | None] = ContextVar("user_identity", default=None)


def _claims_from_jwt(jwt: str) -> dict | None:
    """Best-effort decode of an already-verified JWT's payload.

    Decodes the payload segment only — no signature check (the CUSTOM_JWT authorizer
    verified the token upstream). Returns None on any malformed token so the caller can fall
    back to the anonymous actor. Carries NO token bytes / claim values into logs.
    """
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # restore stripped base64url padding
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as exc:  # missing segment / bad base64 / non-JSON
        _LOG.warning(
            "could not decode claims from verified JWT (%s); using anonymous memory actor",
            type(exc).__name__,
        )
        return None
    return claims if isinstance(claims, dict) else None


def _str_claim(claims: dict, *names: str) -> str | None:
    """The first present, non-empty string claim among ``names``."""
    for name in names:
        value = claims.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def set_user_jwt(jwt: str | None):
    """Set the per-request user identity from an inbound bearer JWT.

    Returns a reset token — pass it to ``reset()`` in a ``finally``.
    """
    if not jwt:
        return _current.set(None)
    claims = _claims_from_jwt(jwt) or {}
    return _current.set(
        UserIdentity(
            raw_jwt=jwt,
            subject=_str_claim(claims, "sub", "oid"),
            oid=_str_claim(claims, "oid"),
        )
    )


def reset(token) -> None:
    _current.reset(token)


def current() -> UserIdentity | None:
    return _current.get()


def actor_id(default: str = ANONYMOUS_ACTOR) -> str:
    """The AgentCore Memory actor for this turn: the verified user's subject when present,
    else the shared anonymous actor."""
    ident = _current.get()
    if ident and ident.subject:
        return ident.subject
    return default


def actor_oid(default: str = "") -> str:
    """The Entra directory object id (`oid`) for this turn, when present.

    Unlike the `sub` (a pairwise pseudonym, opaque per app), the `oid` is resolvable to a
    display name via Microsoft Graph, so it is emitted as a telemetry field for render-time
    actor resolution. An opaque GUID — not PII — and never used to authorize. Empty when the
    token carries no `oid`.
    """
    ident = _current.get()
    return ident.oid if ident and ident.oid else default

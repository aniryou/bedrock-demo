"""Per-request user identity: the memory `actor_id` (sub) and the Graph-resolvable `oid`."""

from __future__ import annotations

import base64
import json

import agent_kit.infra.identity as identity


def _jwt(claims: dict) -> str:
    """A fake `header.payload.signature` token — identity decodes the payload without
    verifying the signature, so the header/signature segments are inert."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


# ── Claim extraction (actor_id / actor_oid) ──────────────────────────────────


def test_actor_id_is_sub_and_oid_is_captured_separately():
    token = identity.set_user_jwt(_jwt({"sub": "SUB-pairwise", "oid": "OID-directory"}))
    try:
        assert identity.actor_id() == "SUB-pairwise"  # memory partition key
        assert identity.actor_oid() == "OID-directory"  # Graph-resolvable, telemetry only
    finally:
        identity.reset(token)


def test_actor_id_falls_back_to_oid_when_no_sub():
    token = identity.set_user_jwt(_jwt({"oid": "OID-directory"}))
    try:
        assert identity.actor_id() == "OID-directory"
        assert identity.actor_oid() == "OID-directory"
    finally:
        identity.reset(token)


def test_oid_empty_when_token_carries_only_sub():
    token = identity.set_user_jwt(_jwt({"sub": "SUB-pairwise"}))
    try:
        assert identity.actor_id() == "SUB-pairwise"
        assert identity.actor_oid() == ""  # no oid -> resolution falls back to the raw key
    finally:
        identity.reset(token)


def test_anonymous_actor_and_empty_oid_without_identity():
    assert identity.actor_id() == identity.ANONYMOUS_ACTOR
    assert identity.actor_oid() == ""


def test_malformed_token_does_not_raise():
    token = identity.set_user_jwt("not-a-jwt")
    try:
        assert identity.actor_id() == identity.ANONYMOUS_ACTOR
        assert identity.actor_oid() == ""
    finally:
        identity.reset(token)


# ── set_user_jwt / current / reset roundtrip ─────────────────────────────────


def test_identity_roundtrip_and_reset():
    # The live API is just set_user_jwt / current / reset: the runtime stores the
    # inbound bearer for the turn and the Gateway client forwards it verbatim.
    assert identity.current() is None
    tok = identity.set_user_jwt("header.payload.sig")
    try:
        ident = identity.current()
        assert ident is not None and ident.raw_jwt == "header.payload.sig"
    finally:
        identity.reset(tok)
    assert identity.current() is None


def test_identity_blank_jwt_is_none():
    tok = identity.set_user_jwt(None)
    try:
        assert identity.current() is None
    finally:
        identity.reset(tok)


def test_actor_id_uses_jwt_subject():
    tok = identity.set_user_jwt(_jwt({"sub": "u-123", "oid": "o-999"}))
    try:
        assert identity.current().subject == "u-123"
        assert identity.actor_id() == "u-123"
    finally:
        identity.reset(tok)


def test_actor_id_falls_back_to_oid_then_anonymous():
    tok = identity.set_user_jwt(_jwt({"oid": "o-999"}))  # no `sub`
    try:
        assert identity.actor_id() == "o-999"
    finally:
        identity.reset(tok)
    # No user token at all -> the shared anonymous actor.
    assert identity.actor_id() == identity.ANONYMOUS_ACTOR


def test_actor_id_anonymous_on_malformed_token():
    # A non-decodable payload must not raise and must fall back to the anonymous actor.
    tok = identity.set_user_jwt("header.payload.sig")
    try:
        assert identity.current().subject is None
        assert identity.actor_id() == identity.ANONYMOUS_ACTOR
    finally:
        identity.reset(tok)

"""Identity claim extraction: the memory `actor_id` (sub) and the Graph-resolvable `oid`."""

import base64
import json

import order_triage.identity as identity


def _jwt(claims: dict) -> str:
    """A fake `header.payload.signature` token — identity decodes the payload without
    verifying the signature, so the header/signature segments are inert."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


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

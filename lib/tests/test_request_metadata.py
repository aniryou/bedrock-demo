"""requestMetadata: opaque attribution ids (incl. the Graph-resolvable actor_oid), PII-free."""

from __future__ import annotations

from agent_kit.prompt import request_metadata


def test_includes_actor_oid_alongside_the_sub():
    md = request_metadata("order-triage", "webapp-abc", "SUB", "OID")
    assert md["actor"] == "SUB"  # the opaque sub (memory key)
    assert md["actor_oid"] == "OID"  # Graph-resolvable; the dashboards' audit resolver reads this
    assert md["session"] == "webapp-abc"
    assert md["turn"]  # always present


def test_anonymous_turn_omits_actor_and_oid():
    md = request_metadata("order-triage", None, "", "")
    assert md["agent"] == "order-triage"
    assert "actor" not in md
    assert "actor_oid" not in md
    assert "session" not in md


def test_pii_shaped_value_is_stripped_never_passed_intact():
    md = request_metadata("a", "s", "user@contoso.com", "OID")
    assert "@" not in md["actor"]
    assert md["actor"] == "usercontoso.com"

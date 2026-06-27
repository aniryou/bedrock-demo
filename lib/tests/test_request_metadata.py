"""requestMetadata: opaque attribution ids (incl. the Graph-resolvable actor_oid), PII-free."""

from __future__ import annotations

from agent_kit.agent import _request_metadata


def test_includes_actor_oid_alongside_the_sub():
    md = _request_metadata(agent_id="order-triage", actor_id="SUB", actor_oid="OID", session_id="webapp-abc")
    assert md["actor"] == "SUB"  # the opaque sub (memory key)
    assert md["actor_oid"] == "OID"  # Graph-resolvable; the dashboards' audit resolver reads this
    assert md["session"] == "webapp-abc"
    assert md["turn"]  # always present


def test_anonymous_turn_omits_actor_and_oid():
    md = _request_metadata(agent_id="order-triage", actor_id="", actor_oid="", session_id=None)
    assert md["agent"] == "order-triage"
    assert "actor" not in md
    assert "actor_oid" not in md
    assert "session" not in md


def test_pii_shaped_value_is_stripped_never_passed_intact():
    md = _request_metadata(agent_id="a", actor_id="user@contoso.com", actor_oid="OID", session_id="s")
    assert "@" not in md["actor"]
    assert md["actor"] == "usercontoso.com"

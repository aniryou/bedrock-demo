"""Hermetic tests for the local tools, the knowledge-repo loaders, and identity.

The backend tools (orders/customers/SAP/flag) are served by the Gateway as MCP tools
in the deployed runtime, so they are not unit-tested here — only the local-only tools
(skill loader, ontology lookup) and the per-request user identity are.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import order_triage.tools as tools_init
from order_triage import identity
from order_triage.tools.skills import load_skill

# ── Skill loader ──────────────────────────────────────────────────────────────


def test_load_skill_unknown():
    assert "No skill named" in load_skill("does_not_exist")


def test_skill_loader_reads_playbooks(tmp_path):
    # A plain markdown file with a leading '>' description still loads.
    (tmp_path / "demo_skill.md").write_text("# Demo\n> when to use demo\n\nsteps\n")
    from order_triage.skill_loader import SkillLoader

    loader = SkillLoader(tmp_path)
    assert "demo_skill" in loader.skills_catalog()
    skill = loader.get_skill("demo_skill")
    assert skill is not None
    assert "Demo" in skill.body
    assert skill.description == "when to use demo"


def test_skill_loader_parses_frontmatter(tmp_path):
    # The order-triage-knowledge format: YAML frontmatter (ontology binding) + body.
    (tmp_path / "credit_hold.skill.md").write_text(
        "---\n"
        "apiName: credit_hold\n"
        "version: 2\n"
        "description: >\n"
        "  Use when a customer may be over their credit limit.\n"
        "appliesTo:\n"
        "  objectTypes: [CreditProfile, CustomerProfile]\n"
        "  actions: [approveCreditLimit, raiseException]\n"
        "---\n"
        "# Credit Hold\n\nStep 1. do the thing.\n"
    )
    from order_triage.skill_loader import SkillLoader

    loader = SkillLoader(tmp_path)
    skill = loader.get_skill("credit_hold")  # keyed by apiName, not the '.skill' stem
    assert skill is not None
    assert skill.version == 2
    assert skill.entities == ("CreditProfile", "CustomerProfile")
    assert skill.actions == ("approveCreditLimit", "raiseException")
    assert skill.description == "Use when a customer may be over their credit limit."
    assert skill.body.startswith("# Credit Hold")
    cat = loader.skills_catalog()
    assert "applies to: CreditProfile, CustomerProfile" in cat
    assert "actions: approveCreditLimit, raiseException" in cat


# ── Ontology lookup (describe_entity over fetched bindings.json) ──────────────

_BINDINGS = {
    "generatedFrom": {"ontologyVersion": "0.5.0"},
    "index": {
        "objectType": {
            "CreditProfile": {
                "skills": ["credit_hold", "high_value_review"],
                "skillsViaLink": ["credit_hold", "handle_credit_override"],
                "actions": ["approveCreditLimit"],
                "kb": ["kb_credit_policy", "kb_credit_policy#c01"],
            },
            "Customer": {"skills": [], "skillsViaLink": [], "actions": [], "kb": []},
            "CustomerProfile": {"skills": [], "skillsViaLink": [], "actions": [], "kb": []},
            "DeliveryOrder": {"skills": [], "skillsViaLink": [], "actions": [], "kb": []},
            "Dispute": {"skills": [], "skillsViaLink": [], "actions": [], "kb": []},
            "Exception": {"skills": [], "skillsViaLink": [], "actions": [], "kb": []},
            "SalesOrder": {"skills": ["high_value_review"], "skillsViaLink": [], "actions": [], "kb": []},
            "StockPosition": {"skills": [], "skillsViaLink": [], "actions": [], "kb": []},
        },
        "linkType": {},
        "action": {},
    },
}

_BOUND = [
    "CreditProfile", "Customer", "CustomerProfile", "DeliveryOrder",
    "Dispute", "Exception", "SalesOrder", "StockPosition",
]


def _loader(tmp_path):
    (tmp_path / "bindings.json").write_text(json.dumps(_BINDINGS))
    from order_triage.tools.ontology import OntologyLoader

    return OntologyLoader(tmp_path)


def test_ontology_loader_reads_bindings(tmp_path):
    loader = _loader(tmp_path)
    assert loader.entity_names() == _BOUND  # exactly the bound 8, never all 42
    assert loader.version == "0.5.0"
    cp = loader.describe_entity("CreditProfile")
    assert cp is not None
    assert set(cp.skills) == {"credit_hold", "handle_credit_override", "high_value_review"}
    assert cp.actions == ("approveCreditLimit",)
    assert len(cp.kb) == 2
    assert cp.properties == ()
    assert cp.related == ()


def test_ontology_loader_case_insensitive_and_miss(tmp_path):
    loader = _loader(tmp_path)
    assert loader.describe_entity("salesorder").api_name == "SalesOrder"
    assert loader.describe_entity("BeanLot") is None


def test_ontology_loader_graceful_when_absent():
    from order_triage.tools.ontology import OntologyLoader

    loader = OntologyLoader(Path("/nonexistent/ontology"))
    assert loader.entity_names() == []
    assert loader.describe_entity("CreditProfile") is None


def test_describe_entity_tool(tmp_path, monkeypatch):
    import order_triage.tools.ontology as onto

    monkeypatch.setattr(onto, "ontology_loader", _loader(tmp_path))
    out = onto.describe_entity("creditprofile")  # tool resolves case-insensitively
    assert "CreditProfile" in out
    assert "credit_hold" in out and "approveCreditLimit" in out
    assert "NOT the agent's Snowflake runtime table" in out
    miss = onto.describe_entity("BeanLot")
    assert "No governed ontology entity" in miss and "CreditProfile" in miss


# ── Gateway action coverage (_assert_action_coverage) ────────────────────────


def _fake_tool(name):
    """A stand-in for a registered tool; _tool_name() reads `.tool_name` first."""
    return SimpleNamespace(tool_name=name)


def test_action_coverage_passes_when_action_is_served(monkeypatch):
    monkeypatch.setattr(
        tools_init, "skill_loader", SimpleNamespace(required_actions=lambda: {"raiseException"})
    )
    tools_init._assert_action_coverage([_fake_tool("orders___flagOrder")])  # no raise


def test_action_coverage_raises_when_action_unserved(monkeypatch):
    monkeypatch.setattr(
        tools_init, "skill_loader", SimpleNamespace(required_actions=lambda: {"raiseException"})
    )
    with pytest.raises(tools_init.SkillActionCoverageError):
        tools_init._assert_action_coverage([_fake_tool("snowflake___ask")])  # flagOrder absent


# ── Per-request user identity ────────────────────────────────────────────────


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


def _jwt(claims: dict) -> str:
    """A JWT-shaped string with the given payload claims (header/sig are placeholders —
    the runtime reads the payload, it never verifies the signature)."""
    import base64
    import json

    seg = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"hdr.{seg}.sig"


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
    assert identity.actor_id() == "order-triage"


def test_actor_id_anonymous_on_malformed_token():
    # A non-decodable payload must not raise and must fall back to the anonymous actor.
    tok = identity.set_user_jwt("header.payload.sig")
    try:
        assert identity.current().subject is None
        assert identity.actor_id() == "order-triage"
    finally:
        identity.reset(tok)

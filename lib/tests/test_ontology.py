"""Ontology lookup tests — describe_entity over the fetched bindings.json."""

from __future__ import annotations

import json
from pathlib import Path

import agent_kit.knowledge.ontology as onto
from agent_kit.knowledge.ontology import OntologyLoader

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
    loader = OntologyLoader(Path("/nonexistent/ontology"))
    assert loader.entity_names() == []
    assert loader.describe_entity("CreditProfile") is None


def test_describe_entity_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(onto, "ontology_loader", _loader(tmp_path))
    out = onto.describe_entity("creditprofile")  # tool resolves case-insensitively
    assert "CreditProfile" in out
    assert "credit_hold" in out and "approveCreditLimit" in out
    assert "NOT the agent's Snowflake runtime table" in out
    miss = onto.describe_entity("BeanLot")
    assert "No governed ontology entity" in miss and "CreditProfile" in miss

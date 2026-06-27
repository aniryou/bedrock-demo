"""Hermetic tests for the skill loader and its on-demand load_skill tool."""

from __future__ import annotations

from agent_kit.knowledge.skill_loader import SkillLoader
from agent_kit.knowledge.skills import load_skill


def test_load_skill_unknown():
    assert "No skill named" in load_skill("does_not_exist")


def test_skill_loader_reads_playbooks(tmp_path):
    # A plain markdown file with a leading '>' description still loads.
    (tmp_path / "demo_skill.md").write_text("# Demo\n> when to use demo\n\nsteps\n")

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

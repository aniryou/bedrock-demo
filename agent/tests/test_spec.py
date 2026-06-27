"""Per-agent contract tests for the order-triage agent.

These exercise the agent-specific surface only — the action-coverage contract between the
fetched skills and `agent.ACTIONS`. They never import `order_triage.runtime` or otherwise
pull `bedrock_agentcore` (that would require the `deploy` extra).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import agent_kit as kit
from agent_kit.knowledge.coverage import assert_action_coverage
from agent_kit.knowledge.skill_loader import SkillLoader

from order_triage.agent import ACTIONS

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


def test_every_invoked_action_is_mapped():
    """Every ontology action the fetched skills can invoke is mapped in ACTIONS."""
    required = SkillLoader(SKILLS_DIR).required_actions()
    assert required - set(ACTIONS) == set()


def test_coverage_gate_passes_with_gateway_tools():
    """With the Gateway tools the agent maps to, the startup coverage gate does not raise."""
    tools = [
        kit.make_kb_tool("search_policies", "x", "kb"),
        kit.describe_entity,
        kit.load_skill,
    ] + [SimpleNamespace(tool_name=v) for v in ACTIONS.values()]
    assert_action_coverage(tools, ACTIONS)

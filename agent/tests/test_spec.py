"""Per-agent contract tests for the order-triage `AgentSpec`.

These exercise the agent-specific surface only — the action-coverage contract between the
fetched skills and `SPEC.action_implementations`. They never import `order_triage.runtime`
or call `build_app` (that would require the `deploy` extra).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_kit.knowledge.coverage import get_tools
from agent_kit.knowledge.skill_loader import SkillLoader

import order_triage.spec
from order_triage.spec import SPEC

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


def test_every_invoked_action_is_mapped():
    """Every ontology action the fetched skills can invoke is mapped in the spec."""
    required = SkillLoader(SKILLS_DIR).required_actions()
    assert required - set(order_triage.spec.SPEC.action_implementations) == set()


def test_coverage_gate_passes_with_gateway_tools():
    """With the Gateway tools the spec maps to, the startup coverage gate does not raise."""
    extra_tools = [
        SimpleNamespace(tool_name=v) for v in SPEC.action_implementations.values()
    ]
    get_tools(SPEC, extra_tools=extra_tools)

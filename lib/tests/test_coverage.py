"""Gateway action coverage — the startup gate (assert_action_coverage)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import agent_kit.knowledge.coverage as coverage


def _fake_tool(name):
    """A stand-in for a registered tool; _tool_name() reads `.tool_name` first."""
    return SimpleNamespace(tool_name=name)


def test_action_coverage_passes_when_action_is_served(monkeypatch):
    monkeypatch.setattr(
        coverage, "skill_loader", SimpleNamespace(required_actions=lambda: {"raiseException"})
    )
    coverage.assert_action_coverage(
        [_fake_tool("orders___flagOrder")], {"raiseException": "orders___flagOrder"}
    )  # no raise


def test_action_coverage_raises_when_action_unserved(monkeypatch):
    monkeypatch.setattr(
        coverage, "skill_loader", SimpleNamespace(required_actions=lambda: {"raiseException"})
    )
    with pytest.raises(coverage.SkillActionCoverageError):
        coverage.assert_action_coverage(
            [_fake_tool("snowflake___ask")], {"raiseException": "orders___flagOrder"}
        )  # flagOrder absent

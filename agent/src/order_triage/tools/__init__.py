"""Agent tool registry + the Gateway action contract.

The backend tools (Snowflake reads, SAP credit, order flagging) are served by the AgentCore
Gateway as MCP tools and passed in as ``extra_tools`` (built in runtime.py); the live set is
discovered per session, never hard-coded here. Local-only tools (Knowledge Base, ontology,
skill loader) are always present.

``ACTION_IMPLEMENTATIONS`` maps each ontology action a skill can invoke to the Gateway tool
that serves it (names are ``<target>___<operationId>``; the operationId isn't the apiName —
e.g. ``raiseException`` -> ``orders___flagOrder`` — so it's authored). The startup gate checks
that every skill-invoked action resolves to a registered tool.
"""

from __future__ import annotations

from ..skill_loader import skill_loader
from .knowledge import search_policies
from .ontology import describe_entity
from .skills import load_skill

# ontology action apiName -> the Gateway MCP tool that implements it.
ACTION_IMPLEMENTATIONS = {"raiseException": "orders___flagOrder"}


class SkillActionCoverageError(RuntimeError):
    """A loaded skill can invoke an ontology action that no registered Gateway tool serves."""


def _tool_name(t) -> str | None:
    # strands @tool functions expose `.tool_name`; MCP tools (MCPAgentTool) do too.
    return getattr(t, "tool_name", None) or getattr(t, "__name__", None)


def _assert_action_coverage(tools: list) -> None:
    """Every action a loaded skill may invoke must map to a registered Gateway tool."""
    registered = {n for t in tools if (n := _tool_name(t))}
    gaps = {
        action: ACTION_IMPLEMENTATIONS.get(action)
        for action in skill_loader.required_actions()
        if ACTION_IMPLEMENTATIONS.get(action) not in registered
    }
    if gaps:
        raise SkillActionCoverageError(
            f"Skill-invoked action(s) not served by a registered Gateway tool: {gaps}. "
            "Map them in ACTION_IMPLEMENTATIONS or fix the skill's `invokes`."
        )


def _local_tools() -> list:
    """Tools that never traverse the Gateway."""
    return [search_policies, describe_entity, load_skill]


def get_tools(extra_tools: list | None = None) -> list:
    tools = _local_tools() + list(extra_tools or [])
    _assert_action_coverage(tools)  # startup gate
    return tools

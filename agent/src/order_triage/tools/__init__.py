"""Agent tool registry (Gateway-only).

The backend tools (Snowflake reads, SAP credit, order flagging) are served by the
AgentCore Gateway as MCP tools — Cedar-authorized and OBO-brokered via TOKEN_EXCHANGE —
and passed in as ``extra_tools`` (built in runtime.py from the Gateway MCP client).
Local-only tools (Knowledge Base, ontology, skill loader) are always present.
"""

from __future__ import annotations

from ..skill_loader import skill_loader
from .knowledge import search_policies
from .ontology import describe_entity
from .skills import load_skill

# ontology ACTION apiName -> the Gateway MCP tool name that implements it.
ACTION_IMPLEMENTATIONS = {
    "raiseException": "orders___flagOrder",
}


class SkillActionCoverageError(RuntimeError):
    """A fetched skill can `invoke` an ontology action that no registered tool implements."""


def _tool_name(t) -> str | None:
    # strands @tool functions expose `.tool_name`; MCP tools (MCPAgentTool) do too.
    return getattr(t, "tool_name", None) or getattr(t, "__name__", None)


def _assert_action_coverage(tools: list) -> None:
    """Fail fast if a loaded skill's `invoke` has no implementing (Gateway) tool."""
    registered = {_tool_name(t) for t in tools}
    gaps: dict[str, str] = {}
    for action in sorted(skill_loader.required_actions()):
        name = ACTION_IMPLEMENTATIONS.get(action)
        if not name:
            gaps[action] = "no tool mapped in ACTION_IMPLEMENTATIONS"
        elif name not in registered:
            gaps[action] = f"Gateway tool {name!r} not registered (is the Gateway target present?)"
    if gaps:
        invoked_by = {
            s.name: [a for a in s.invokes if a in gaps]
            for s in skill_loader.all_skills()
            if any(a in gaps for a in s.invokes)
        }
        raise SkillActionCoverageError(
            f"Skill->action coverage gap {gaps}; invoked by {invoked_by}. "
            "Add the action to ACTION_IMPLEMENTATIONS or fix the skill's `invokes`."
        )


def _local_tools() -> list:
    """Tools that never traverse the Gateway."""
    return [search_policies, describe_entity, load_skill]


def get_tools(extra_tools: list | None = None) -> list:
    tools = _local_tools() + list(extra_tools or [])
    _assert_action_coverage(tools)  # startup gate: every skill `invoke` has a tool
    return tools

"""The Gateway action-coverage gate.

The backend tools (Snowflake reads, SAP credit, order flagging) are served by the AgentCore
Gateway as MCP tools and passed in as ``extra_tools`` (built in the runtime entrypoint); the
live set is discovered per session, never hard-coded here. Local-only tools (Knowledge Base,
ontology, skill loader) are always present.

``action_implementations`` maps each ontology action a skill can invoke to the Gateway tool
that serves it (names are ``<target>___<operationId>``; the operationId isn't the apiName —
e.g. ``raiseException`` -> ``orders___flagOrder`` — so it's authored). The startup gate checks
that every skill-invoked action resolves to a registered tool.
"""

from __future__ import annotations

from agent_kit.knowledge.skill_loader import skill_loader


class SkillActionCoverageError(RuntimeError):
    """A loaded skill can invoke an ontology action that no registered Gateway tool serves."""


def _tool_name(t) -> str | None:
    # strands @tool functions expose `.tool_name`; MCP tools (MCPAgentTool) do too.
    return getattr(t, "tool_name", None) or getattr(t, "__name__", None)


def assert_action_coverage(tools: list, action_implementations: dict[str, str]) -> None:
    """Every action a loaded skill may invoke must map to a registered Gateway tool."""
    registered = {n for t in tools if (n := _tool_name(t))}
    gaps = {
        action: action_implementations.get(action)
        for action in skill_loader.required_actions()
        if action_implementations.get(action) not in registered
    }
    if gaps:
        raise SkillActionCoverageError(
            f"Skill-invoked action(s) not served by a registered Gateway tool: {gaps}. "
            "Map them in action_implementations or fix the skill's `invokes`."
        )


def tools_with_coverage(local_tools, action_implementations, extra_tools=None) -> list:
    tools = list(local_tools) + list(extra_tools or [])
    assert_action_coverage(tools, action_implementations)  # startup gate
    return tools

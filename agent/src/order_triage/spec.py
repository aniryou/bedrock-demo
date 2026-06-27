"""The order-triage agent's `AgentSpec` — the per-agent contract `agent_kit` consumes.

Everything agent-agnostic (prompt assembly, tool surface, model, memory, runtime entrypoint,
metrics) is driven from this spec; the toolkit itself stays generic.
"""

from __future__ import annotations

from agent_kit import AgentSpec

SPEC = AgentSpec(
    agent_id="order-triage",
    metric_namespace="OrderTriage/Agent",
    # Each ontology action a skill can invoke -> the Gateway tool that serves it
    # (the operationId isn't the apiName — `raiseException` -> `orders___flagOrder`).
    action_implementations={"raiseException": "orders___flagOrder"},
    kb_tool_name="search_policies",
    kb_tool_description=(
        "Search the order/credit/dispute policy knowledge base for relevant rules.\n\n"
        "Use this to ground decisions in policy (review thresholds, credit-hold rules,\n"
        "dispute handling) and cite the policy you relied on."
    ),
)

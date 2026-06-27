"""The per-agent contract object.

An `AgentSpec` is the small, agent-specific surface a consuming package supplies. Everything
in `agent_kit` (prompt assembly, tool surface, model, memory, runtime entrypoint, metrics) is
driven from it, so the toolkit itself stays agent-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    metric_namespace: str
    action_implementations: dict[str, str]
    kb_tool_name: str = "search_policies"
    kb_tool_description: str = "Search the policy knowledge base for relevant rules."
    system_prompt_preamble: str = ""
    # Long-term retrieval tuning, per strategy namespace. Each entry is
    # (namespace_template, top_k, relevance_score): top_k caps the semantic-search hits per
    # namespace; relevance_score is the minimum cosine-similarity floor. The KEYS (the
    # namespace templates) must match the templated namespaces declared in the agent
    # deployment's terraform/memory.tf — the Strands session manager resolves the
    # {actorId}/{sessionId} placeholders at retrieval time via str.format().
    retrieval_namespaces: tuple[tuple[str, int, float], ...] = (
        ("/facts/{actorId}", 5, 0.3),
        ("/preferences/{actorId}", 5, 0.3),
        ("/summaries/{actorId}/{sessionId}", 3, 0.3),
    )
    model_id: str = "anthropic.claude-opus-4-8"
    region: str = "us-west-2"
    max_tokens: int = 2048

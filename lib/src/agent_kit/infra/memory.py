"""Memory adapter — AgentCore Memory (short + long term).

`build_session_manager` returns a Strands `AgentCoreMemorySessionManager` that persists each
turn to AgentCore Memory (short-term events) and retrieves the extracted long-term memories
— facts, preferences, session summaries — injecting them into the turn as a `<user_context>`
block on the latest user message. `retrieval_config` (the `retrieval_namespaces` passed in)
selects which namespaces to search; `actor_id` comes from the request identity, so the
long-term namespaces are partitioned per user.

`memory_id` is required. `session_id=None` => a stateless single-shot agent (no
persistence). See the agent deployment's `terraform/memory.tf` for the namespace templates.

`retrieval_namespaces` is a tuple of `(namespace_template, top_k, relevance_score)` entries.
The KEYS must be the templated namespaces declared in terraform/memory.tf — the Strands
session manager resolves the {actorId}/{sessionId} placeholders at retrieval time via
str.format(). top_k caps the semantic-search hits per namespace; relevance_score is the
minimum cosine-similarity floor. SDK defaults are (10, 0.2); 0.3 is a conservative starting
floor to tune from the memory traces.
"""

from __future__ import annotations


def build_session_manager(
    memory_id: str,
    session_id: str | None,
    actor_id: str,
    retrieval_namespaces: tuple[tuple[str, int, float], ...],
    region: str = "us-west-2",
):
    if session_id is None:
        return None

    from bedrock_agentcore.memory.integrations.strands.config import (
        AgentCoreMemoryConfig,
        RetrievalConfig,
    )
    from bedrock_agentcore.memory.integrations.strands.session_manager import (
        AgentCoreMemorySessionManager,
    )

    return AgentCoreMemorySessionManager(
        agentcore_memory_config=AgentCoreMemoryConfig(
            memory_id=memory_id,
            session_id=session_id,
            actor_id=actor_id,
            retrieval_config={
                ns: RetrievalConfig(top_k=top_k, relevance_score=score)
                for (ns, top_k, score) in retrieval_namespaces
            },
        ),
        region_name=region,
    )

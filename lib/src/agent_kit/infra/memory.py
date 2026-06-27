"""Memory adapter — AgentCore Memory (short + long term).

`build_session_manager` returns a Strands `AgentCoreMemorySessionManager` that persists each
turn to AgentCore Memory (short-term events) and retrieves the extracted long-term memories
— facts, preferences, session summaries — injecting them into the turn as a `<user_context>`
block on the latest user message. `retrieval_config` (the `retrieval_namespaces` passed in)
selects which namespaces to search; `actor_id` comes from the request identity, so the
long-term namespaces are partitioned per user.

`AGENTCORE_MEMORY_ID` is required. `session_id=None` => a stateless single-shot agent (no
persistence). See the agent deployment's `terraform/memory.tf` for the namespace templates.

`retrieval_namespaces` is a tuple of `(namespace_template, top_k, relevance_score)` entries.
The KEYS must be the templated namespaces declared in terraform/memory.tf — the Strands
session manager resolves the {actorId}/{sessionId} placeholders at retrieval time via
str.format(). top_k caps the semantic-search hits per namespace; relevance_score is the
minimum cosine-similarity floor. SDK defaults are (10, 0.2); 0.3 is a conservative starting
floor to tune from the memory traces.
"""

from __future__ import annotations

from agent_kit.config import get_config
from agent_kit.infra import identity


def build_session_manager(
    session_id: str | None,
    retrieval_namespaces: tuple[tuple[str, int, float], ...],
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

    cfg = get_config()
    return AgentCoreMemorySessionManager(
        agentcore_memory_config=AgentCoreMemoryConfig(
            memory_id=cfg.memory_id,
            session_id=session_id,
            actor_id=identity.actor_id(),
            retrieval_config={
                ns: RetrievalConfig(top_k=top_k, relevance_score=score)
                for (ns, top_k, score) in retrieval_namespaces
            },
        ),
        region_name=cfg.aws_region,
    )

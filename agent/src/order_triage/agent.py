"""The order-triage agent — configuration and assembly.

This module OWNS the agent: it holds every configuration decision (model id, region,
guardrail, token budget, the Gateway action map, the KB tool's name/description, the memory
retrieval namespaces) and `build_agent`, which constructs the `BedrockModel` (with this
agent's own guardrail/model config) and the Strands `Agent` by composing `agent_kit` helpers.

It imports `strands` + `agent_kit` only (never `bedrock_agentcore`), so it stays import-safe
in the dev venv and the hermetic tests; the AgentCore Runtime loop lives in `runtime.py`.
"""

from __future__ import annotations

import os

import agent_kit as kit
from strands import Agent
from strands.models import BedrockModel

AGENT_ID = "order-triage"
METRIC_NAMESPACE = "OrderTriage/Agent"
REGION = os.getenv("AWS_REGION", "us-west-2")

# Each ontology action a skill can invoke -> the Gateway tool that serves it (the operationId
# isn't the apiName — `raiseException` -> `orders___flagOrder`).
ACTIONS = {"raiseException": "orders___flagOrder"}

KB_TOOL_NAME = "search_policies"
KB_TOOL_DESCRIPTION = (
    "Search the order/credit/dispute policy knowledge base for relevant rules.\n\n"
    "Use this to ground decisions in policy (review thresholds, credit-hold rules,\n"
    "dispute handling) and cite the policy you relied on."
)

# (namespace_template, top_k, relevance_score) — the KEYS must be the templated namespaces
# declared in terraform/memory.tf (the Strands session manager resolves the
# {actorId}/{sessionId} placeholders at retrieval time); top_k caps the hits per namespace,
# relevance_score is the minimum cosine-similarity floor.
RETRIEVAL_NAMESPACES = (
    ("/facts/{actorId}", 5, 0.3),
    ("/preferences/{actorId}", 5, 0.3),
    ("/summaries/{actorId}/{sessionId}", 3, 0.3),
)


def build_agent(
    session_id: str | None,
    actor_id: str,
    actor_oid: str,
    extra_tools: list,
) -> Agent:
    """Construct the order-triage agent. Pass a session_id to enable persistent memory.

    The runtime entrypoint passes the Gateway's MCP tools as ``extra_tools`` (the backend tool
    surface); `tools_with_coverage` merges them with the always-present local tools and gates
    that every skill-invoked action maps to a registered tool.
    """
    # Native Bedrock Guardrail (optional). Strands injects guardrailConfig into Converse/
    # ConverseStream only when BOTH id and version are present (strands BedrockModel: the
    # `if guardrail_id and guardrail_version` gate); one-without-the-other is a silent no-op,
    # so build the kwargs together or not at all. Empty env (sandbox) => no guardrail.
    gid = os.getenv("BEDROCK_GUARDRAIL_ID", "").strip()
    gver = os.getenv("BEDROCK_GUARDRAIL_VERSION", "").strip()
    guardrail_kwargs: dict = {}
    if gid and gver:
        guardrail_kwargs = {
            "guardrail_id": gid,
            "guardrail_version": gver,
            # async: response chunks stream to the client as they are generated, with the
            # guardrail assessment running out of band.
            "guardrail_stream_processing_mode": "async",
            # Keep the original user turn in conversation history when an input filter blocks
            # it (the SDK default, True, replaces it with "[User input redacted.]").
            "guardrail_redact_input": False,
        }

    tools = kit.tools_with_coverage(
        [
            kit.make_kb_tool(
                KB_TOOL_NAME,
                KB_TOOL_DESCRIPTION,
                os.getenv("KNOWLEDGE_BASE_ID", "").strip(),
                REGION,
            ),
            kit.describe_entity,
            kit.load_skill,
        ],
        ACTIONS,
        extra_tools,
    )

    return Agent(
        model=BedrockModel(
            model_id=os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-opus-4-8"),
            region_name=REGION,
            max_tokens=int(os.getenv("MAX_TOKENS", "2048")),
            # Tag every Converse call with opaque attribution ids so the model-invocation log
            # (invocation_logging.tf) is queryable by agent/actor/session. Strands spreads
            # additional_args at the Converse TOP LEVEL (-> the `requestMetadata` param), NOT
            # into additionalModelRequestFields. Opaque ids only — never PII.
            additional_args={
                "requestMetadata": kit.request_metadata(
                    AGENT_ID, session_id, actor_id, actor_oid
                )
            },
            **guardrail_kwargs,
        ),
        system_prompt=kit.build_system_prompt(),
        tools=tools,
        agent_id=AGENT_ID,
        session_manager=kit.build_session_manager(
            os.getenv("AGENTCORE_MEMORY_ID", "").strip(),
            session_id,
            actor_id,
            RETRIEVAL_NAMESPACES,
            REGION,
        ),
    )

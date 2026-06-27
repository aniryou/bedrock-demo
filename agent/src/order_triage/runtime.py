"""AgentCore Runtime entrypoint.

The order-triage agent owns its runtime loop: this module wires a `BedrockAgentCoreApp`,
exposing the `/invocations` and `/ping` endpoints AgentCore Runtime expects, and streams the
agent's output back, composing `agent_kit` helpers around the agent built in `agent.py`.

The runtime is behind the CUSTOM_JWT Gateway: it forwards the inbound user JWT to the
Gateway, whose MCP tools serve the backends (Cedar-authorized, OBO-brokered via
TOKEN_EXCHANGE). Requires the `deploy` extra (installed in the container image) for
`bedrock_agentcore`; this module is not imported by the tests.
"""

from __future__ import annotations

import os

import agent_kit as kit
from agent_kit import identity
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from .agent import AGENT_ID, METRIC_NAMESPACE, build_agent

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload, context=None):
    """AgentCore invocation entrypoint.

    payload: JSON body, e.g. {"prompt": "...", "session_id": "..."}.
    context: AgentCore runtime context (carries the session id and, under CUSTOM_JWT
    inbound, the user's request headers).
    """
    payload = payload or {}
    prompt = payload.get("prompt") or payload.get("inputText") or ""
    session_id = payload.get("session_id")
    if session_id is None and context is not None:
        session_id = getattr(context, "session_id", None)

    token = identity.set_user_jwt(
        kit.extract_user_jwt(context, os.getenv("USER_JWT_HEADER", "Authorization"))
    )
    try:
        gateway_url = os.getenv("GATEWAY_URL", "").strip()
        ident = identity.current()
        if not gateway_url or ident is None:
            raise RuntimeError(
                "This runtime requires the CUSTOM_JWT Gateway: a user bearer token and "
                "GATEWAY_URL must both be present."
            )
        # The Gateway serves the backend tools as MCP tools, brokered on-behalf-of the user.
        # The MCP client must stay open for the whole turn (its tools are only callable while
        # the session is live), so build + stream inside the context.
        actor = identity.actor_id(AGENT_ID)
        actor_oid = identity.actor_oid()
        gw_client = kit.build_gateway_client(gateway_url, ident.raw_jwt)
        with gw_client:
            agent = build_agent(
                session_id, actor, actor_oid, gw_client.list_tools_sync()
            )
            async for event in agent.stream_async(prompt):
                # AgentCore serializes each yield as one NDJSON line. Forward answer/thinking
                # TEXT (bare string — the full event dict carries a non-serializable Agent
                # object) and typed tool-step events; drop the rest.
                if isinstance(event, dict) and "data" in event:
                    yield event["data"]
                    continue
                for step in kit.step_events(event):
                    yield step
            # Stream complete: emit this turn's token usage as an EMF metric. The Strands
            # tracer already sets gen_ai.usage.* on its own spans, so we add NO span
            # attribute — only the metric, which is the genuine gap (CloudWatch has no token
            # metric otherwise).
            kit.emit_usage_metric(
                agent,
                namespace=METRIC_NAMESPACE,
                agent_id=AGENT_ID,
                model_id=os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-opus-4-8"),
                session_id=session_id,
                actor_id=actor,
                actor_oid=actor_oid,
            )
    finally:
        identity.reset(token)


if __name__ == "__main__":
    app.run()

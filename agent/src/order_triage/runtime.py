"""AgentCore Runtime entrypoint.

Wraps `build_agent()` in a `BedrockAgentCoreApp`, exposing the `/invocations` and `/ping`
endpoints AgentCore Runtime expects, and streams the agent's output back.

The runtime is behind the CUSTOM_JWT Gateway: it forwards the inbound user JWT to the
Gateway, whose MCP tools serve the backends (Cedar-authorized, OBO-brokered via
TOKEN_EXCHANGE). Requires the `deploy` extra (installed in the container image); this
module is not imported by the tests.
"""

from __future__ import annotations

import json
import logging
import time

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from . import identity
from .agent import build_agent
from .config import get_config
from .gateway import build_gateway_client
from .stream_steps import step_events

app = BedrockAgentCoreApp()

_LOG = logging.getLogger("order_triage.runtime")
_AGENT_ID = "order-triage"


def _emit_usage_metric(
    usage: dict, *, session_id: str | None, actor_id: str, actor_oid: str = ""
) -> None:
    """Emit this turn's Bedrock token usage as a CloudWatch EMF metric line on stdout.

    The line is a valid Embedded Metric Format document AND a queryable structured JSON log.
    Cardinality rule: only agent_id + model_id are metric DIMENSIONS; session_id / actor_id
    / actor_oid / cache_* stay as root log fields (high cardinality -> never dimensions).
    actor_oid is the Graph-resolvable directory id the dashboards' actor-resolution widget
    maps to a display name (actor_id is the opaque pairwise sub). Never raises —
    a telemetry failure must not break the user's turn.

    NOTE: CloudWatch EMF auto-extraction is documented for the direct PutLogEvents path.
    Whether it ALSO fires for lines that reach the APPLICATION_LOGS group via AgentCore's
    vended-log *delivery* pipeline is not guaranteed; if it doesn't, add a CloudWatch Logs
    metric filter on the group over this same JSON. The structured log line is useful
    via Logs Insights either way.
    """
    try:
        in_tok = int(usage.get("inputTokens", 0))
        out_tok = int(usage.get("outputTokens", 0))
        total = int(usage.get("totalTokens", in_tok + out_tok))
        emf = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "OrderTriage/Agent",
                        "Dimensions": [["agent_id", "model_id"]],
                        "Metrics": [
                            {"Name": "InputTokens", "Unit": "Count"},
                            {"Name": "OutputTokens", "Unit": "Count"},
                            {"Name": "TotalTokens", "Unit": "Count"},
                        ],
                    }
                ],
            },
            "agent_id": _AGENT_ID,
            "model_id": get_config().bedrock_model_id,
            "InputTokens": in_tok,
            "OutputTokens": out_tok,
            "TotalTokens": total,
            # Root log fields only — high cardinality, NEVER metric dimensions.
            "session_id": session_id or "",
            "actor_id": actor_id,
            "actor_oid": actor_oid,
            "cache_read_input_tokens": int(usage.get("cacheReadInputTokens", 0)),
            "cache_write_input_tokens": int(usage.get("cacheWriteInputTokens", 0)),
        }
        print(json.dumps(emf), flush=True)
    except Exception:  # never let telemetry break a turn
        _LOG.warning("failed to emit token-usage metric", exc_info=True)


def _extract_user_jwt(context) -> str | None:
    """Pull the inbound user bearer from the request headers (CUSTOM_JWT inbound)."""
    headers = getattr(context, "request_headers", None) if context else None
    if not headers:
        return None
    want = get_config().user_jwt_header.lower()
    for k, v in headers.items():
        if k.lower() == want and isinstance(v, str):
            v = v.strip()
            if v.lower().startswith("bearer "):
                v = v[7:].strip()
            return v or None
    return None


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

    token = identity.set_user_jwt(_extract_user_jwt(context))
    try:
        gw_client = build_gateway_client()
        if gw_client is None:
            raise RuntimeError(
                "This runtime requires the CUSTOM_JWT Gateway: a user bearer token and "
                "GATEWAY_URL must both be present."
            )
        # The Gateway serves the backend tools as MCP tools, brokered on-behalf-of the
        # user. The MCP client must stay open for the whole turn (its tools are only
        # callable while the session is live), so build + stream inside the context.
        actor = identity.actor_id()
        actor_oid = identity.actor_oid()
        with gw_client:
            agent = build_agent(
                session_id=session_id,
                actor_id=actor,
                actor_oid=actor_oid,
                extra_tools=gw_client.list_tools_sync(),
            )
            async for event in agent.stream_async(prompt):
                # AgentCore serializes each yield as one NDJSON line. Forward answer/
                # thinking TEXT (bare string — the full event dict carries a
                # non-serializable Agent object) and typed tool-step events; drop the rest.
                if isinstance(event, dict) and "data" in event:
                    yield event["data"]
                    continue
                for step in step_events(event):
                    yield step
            # Stream complete: emit this turn's token usage as a metric. Read
            # latest_agent_invocation.usage (the PER-TURN total) — Strands never zeroes
            # accumulated_usage, so that would over-count on a reused Agent; the read here
            # is correct regardless of lifecycle. The Strands tracer already sets
            # gen_ai.usage.* on its own spans, so we add NO span attribute — only the
            # EMF metric, which is the genuine gap (CloudWatch has no token metric otherwise).
            inv = getattr(agent.event_loop_metrics, "latest_agent_invocation", None)
            usage = dict(getattr(inv, "usage", None) or {})
            _emit_usage_metric(
                usage, session_id=session_id, actor_id=actor, actor_oid=actor_oid
            )
    finally:
        identity.reset(token)


if __name__ == "__main__":
    app.run()

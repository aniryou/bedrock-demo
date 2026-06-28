"""Token-usage telemetry — CloudWatch Embedded Metric Format (EMF).

`emit_usage_metric` reads this turn's per-turn Bedrock token usage off the agent and prints
one EMF document on stdout: a valid metric line AND a queryable structured JSON log.
"""

from __future__ import annotations

import json
import logging
import time

_LOG = logging.getLogger("agent_kit.metrics")


def emit_usage_metric(
    agent,
    *,
    namespace: str,
    agent_id: str,
    model_id: str = "",
    session_id: str | None = None,
    actor_id: str = "",
    actor_oid: str = "",
) -> None:
    """Emit this turn's Bedrock token usage as a CloudWatch EMF metric line on stdout.

    The line is a valid Embedded Metric Format document AND a queryable structured JSON log.
    Cardinality rule: only agent_id + model_id are metric DIMENSIONS; session_id / actor_id
    / actor_oid / cache_* stay as root log fields (high cardinality -> never dimensions).
    actor_oid is the Graph-resolvable directory id the dashboards' actor-resolution widget
    maps to a display name (actor_id is the opaque pairwise sub). Never raises —
    a telemetry failure must not break the user's turn.

    Reads `latest_agent_invocation.usage` (the PER-TURN total) — Strands never zeroes
    accumulated_usage, so reading that would over-count on a reused Agent; this read is
    correct regardless of lifecycle.

    NOTE: CloudWatch EMF auto-extraction is documented for the direct PutLogEvents path.
    Whether it ALSO fires for lines that reach the APPLICATION_LOGS group via AgentCore's
    vended-log *delivery* pipeline is not guaranteed; if it doesn't, add a CloudWatch Logs
    metric filter on the group over this same JSON. The structured log line is useful
    via Logs Insights either way.
    """
    try:
        inv = getattr(agent.event_loop_metrics, "latest_agent_invocation", None)
        usage = dict(getattr(inv, "usage", None) or {})
        in_tok = int(usage.get("inputTokens", 0))
        out_tok = int(usage.get("outputTokens", 0))
        total = int(usage.get("totalTokens", in_tok + out_tok))
        emf = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": namespace,
                        "Dimensions": [["agent_id", "model_id"]],
                        "Metrics": [
                            {"Name": "InputTokens", "Unit": "Count"},
                            {"Name": "OutputTokens", "Unit": "Count"},
                            {"Name": "TotalTokens", "Unit": "Count"},
                        ],
                    }
                ],
            },
            "agent_id": agent_id,
            "model_id": model_id,
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

"""Classify Strands stream events into typed *agent-step* events for an audit timeline.

Pure helpers (no AgentCore / model imports) so they are unit-testable off the
deployed runtime. They surface what the agent *does* — each tool call (name +
parsed input) and its result (status + summary) — which a client renders as a
Claude-Code-style timeline next to the answer.

Why the ``message`` events and not the streaming deltas: in Strands the complete
tool name+input and the tool result arrive cleanly on ``{"message": ...}`` events
(``toolUse`` / ``toolResult`` content blocks). The incremental ``tool_use_stream``
deltas instead carry the whole ``invocation_state`` — including a non-serializable
``Agent`` object, so we never forward
those raw.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def tool_result_text(content: Any) -> str:
    """Flatten a toolResult's content blocks into a short text summary."""
    if not isinstance(content, list):
        return ""
    parts = [b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]
    return "\n".join(parts).strip()


def step_events(event: Any) -> Iterator[dict]:
    """Yield typed ``{"__step__": {...}}`` event(s) for one Strands event, or nothing.

    - ``tool_call``: {kind, id, name, input}
    - ``tool_result``: {kind, id, status, text}
    - ``reason``: {kind, text}  (native reasoning models; Nova emits <thinking> inline)
    """
    if not isinstance(event, dict):
        return
    msg = event.get("message")
    if isinstance(msg, dict):
        for block in msg.get("content") or []:
            if not isinstance(block, dict):
                continue
            tu = block.get("toolUse")
            if isinstance(tu, dict) and tu.get("name"):
                yield {"__step__": {
                    "kind": "tool_call",
                    "id": tu.get("toolUseId"),
                    "name": tu.get("name"),
                    "input": tu.get("input"),
                }}
            tr = block.get("toolResult")
            if isinstance(tr, dict):
                yield {"__step__": {
                    "kind": "tool_result",
                    "id": tr.get("toolUseId"),
                    "status": tr.get("status"),
                    "text": tool_result_text(tr.get("content")),
                }}
        return
    if event.get("reasoning") and isinstance(event.get("reasoningText"), str):
        yield {"__step__": {"kind": "reason", "text": event["reasoningText"]}}

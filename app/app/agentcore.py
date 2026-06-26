"""Invoke the AgentCore OBO runtime with the signed-in user's Entra JWT.

The OBO runtime uses CUSTOM_JWT inbound auth, so the call carries ONLY the user
bearer (no SigV4 / AWS creds needed) — the same shape as the handover's §6 curl.
The runtime streams its answer as NDJSON.

This module streams **incrementally**: :func:`stream_agent` yields ``("delta",
text)`` / ``("step", entry)`` tuples as each NDJSON line arrives off the wire, so
the web layer can forward tokens to the browser in real time instead of buffering
the whole answer.
"""

from __future__ import annotations

import json
from typing import AsyncIterator, Union
from urllib.parse import quote

import httpx

# One parsed stream item: answer text ("delta") or an agent-step ("step", a
# tool_call/tool_result/reason dict).
Event = Union[tuple[str, str], tuple[str, dict]]


def _data_url(region: str, runtime_arn: str) -> str:
    enc = quote(runtime_arn, safe="")
    return f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{enc}/invocations?qualifier=DEFAULT"


# The runtime's stream forwards Strands' *internal* loop events (tool-use streams,
# lifecycle objects) alongside real answer text — they arrive as Python ``repr``
# strings like ``{'type': 'tool_use_stream', ..., 'agent': <strands.agent...>}``.
# They're not user content (a single one can be tens of KB), so we drop them here
# rather than ship them to the browser. See OBO-HANDOVER / runtime.py `else: yield`.
_EVENT_NOISE_MARKERS = (
    "tool_use_stream",
    "current_tool_use",
    "'toolUse'",
    "<strands",
    "init_event_loop",
    "reasoningText",
    "force_stop",
    "'stop_reason'",
)


def _is_event_noise(text: str) -> bool:
    """True if ``text`` is a leaked Strands event repr rather than answer text."""
    head = text.lstrip()
    if not (head.startswith("{'") or head.startswith('{"')):
        return False
    return any(marker in text for marker in _EVENT_NOISE_MARKERS)


def _parse_line(raw: str) -> Event | None:
    """Parse one NDJSON/SSE line into a ``(kind, value)`` event, or ``None`` to skip.

    Tolerates SSE framing (``data:``/``event:`` prefixes), bare JSON strings, and
    ``{"data": "..."}`` text chunks. Leaked internal event reprs and unrecognized
    control events are dropped so only real answer text + steps reach the UI.
    """
    line = raw.strip()
    if not line:
        return None
    if line.startswith("data:"):  # tolerate SSE framing
        line = line[5:].strip()
    if not line or line.startswith("event:"):
        return None
    try:
        val = json.loads(line)
    except json.JSONDecodeError:
        return None if _is_event_noise(line) else ("delta", line)
    if isinstance(val, str):
        return None if _is_event_noise(val) else ("delta", val)
    if isinstance(val, dict):
        if isinstance(val.get("__step__"), dict):  # typed agent-step (tool_call/result/reason)
            return ("step", val["__step__"])
        if isinstance(val.get("data"), str):
            return None if _is_event_noise(val["data"]) else ("delta", val["data"])
    return None


async def stream_agent(
    region: str, runtime_arn: str, bearer: str, session_id: str, prompt: str
) -> AsyncIterator[Event]:
    """Stream the OBO runtime's reply as the user, yielding events as they arrive.

    Yields ``("delta", text)`` for each answer chunk and ``("step", entry)`` for
    each agent step (tool call/result/reason). Raises on transport / HTTP errors.
    """
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        # AgentCore requires a session id of >= 33 chars.
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }
    url = _data_url(region, runtime_arn)
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream("POST", url, headers=headers, json={"prompt": prompt}) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", "replace")[:600]
                raise RuntimeError(f"runtime returned {resp.status_code}: {body}")
            async for raw in resp.aiter_lines():
                event = _parse_line(raw)
                if event is not None:
                    yield event

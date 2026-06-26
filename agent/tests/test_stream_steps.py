"""The Strands-event → typed-step classifier (the audit-timeline source).

Proves that the runtime surfaces what the agent *does* — tool calls (name + parsed
input) and their results (status + summary) — from the clean ``message`` events, and
drops the noisy/non-serializable events (the streaming ``tool_use_stream`` deltas that
carry an ``Agent`` object). Shapes here mirror real Strands 1.44.0 events captured from
a Nova Lite run.
"""

from __future__ import annotations

import json

from order_triage.stream_steps import step_events, tool_result_text


def _steps(event):
    return [e["__step__"] for e in step_events(event)]


def test_assistant_message_yields_tool_calls():
    # One assistant turn can fire several tool calls at once.
    event = {"message": {"role": "assistant", "content": [
        {"text": "<thinking>check it</thinking>"},
        {"toolUse": {"toolUseId": "t1", "name": "ask_orders", "input": {"question": "status of O-1003"}}},
        {"toolUse": {"toolUseId": "t2", "name": "lookup_customer", "input": {"query": "C-003"}}},
    ]}}
    steps = _steps(event)
    assert [s["kind"] for s in steps] == ["tool_call", "tool_call"]
    assert steps[0] == {"kind": "tool_call", "id": "t1", "name": "ask_orders",
                        "input": {"question": "status of O-1003"}}
    assert steps[1]["name"] == "lookup_customer"


def test_user_message_yields_tool_result():
    event = {"message": {"role": "user", "content": [
        {"toolResult": {"toolUseId": "t1", "status": "success",
                        "content": [{"text": "Order O-1003 ($45,000, smb Initech, OPEN, web) -> risk = high"}]}},
    ]}}
    steps = _steps(event)
    assert len(steps) == 1
    assert steps[0] == {"kind": "tool_result", "id": "t1", "status": "success",
                        "text": "Order O-1003 ($45,000, smb Initech, OPEN, web) -> risk = high"}


def test_error_tool_result_preserves_status():
    event = {"message": {"role": "user", "content": [
        {"toolResult": {"toolUseId": "t9", "status": "error",
                        "content": [{"text": "Error: ReadTimeout - SAP API did not respond"}]}},
    ]}}
    (step,) = _steps(event)
    assert step["status"] == "error"
    assert "ReadTimeout" in step["text"]


def test_native_reasoning_event_becomes_reason_step():
    event = {"reasoningText": "I should score the order first.", "reasoning": True, "delta": {}}
    assert _steps(event) == [{"kind": "reason", "text": "I should score the order first."}]


def test_noisy_and_text_events_are_dropped():
    # Text deltas are handled by the runtime's "data" branch, not here; lifecycle
    # and the non-serializable streaming tool_use deltas must produce nothing.
    assert list(step_events({"data": "<thinking", "delta": {"text": "<thinking"}})) == []
    assert list(step_events({"init_event_loop": True})) == []
    assert list(step_events({"type": "tool_use_stream", "current_tool_use": {"name": "x"},
                             "agent": object()})) == []
    assert list(step_events("a bare string")) == []


def test_all_emitted_steps_are_json_serializable():
    event = {"message": {"role": "assistant", "content": [
        {"toolUse": {"toolUseId": "t1", "name": "score_order", "input": {"order_id": "O-1003"}}},
    ]}}
    for emitted in step_events(event):
        json.dumps(emitted)  # must not raise


def test_tool_result_text_flattens_and_tolerates_junk():
    assert tool_result_text([{"text": "a"}, {"text": "b"}]) == "a\nb"
    assert tool_result_text([{"json": {"x": 1}}, {"text": "ok"}]) == "ok"
    assert tool_result_text(None) == ""
    assert tool_result_text("nope") == ""

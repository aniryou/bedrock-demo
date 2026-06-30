"""AWS Lambda entrypoint for the order-actions API (deploy path).

Deployed as a native AgentCore Gateway **Lambda target**: the Gateway invokes the function
(`lambda:InvokeFunction`) with the tool arguments as the `event` and the MCP tool name in
`context.client_context.custom['bedrockAgentCoreToolName']` (format `"<target>___<tool>"`).
No HTTP layer on this path — the business logic lives in `app.py`. Locally, use
`make order-actions` (the FastAPI app under uvicorn).
"""

from __future__ import annotations

from .app import FlagRequest, flag_order

_DELIM = "___"


def handler(event, context):
    tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool = tool_name.split(_DELIM, 1)[1] if _DELIM in tool_name else tool_name
    if tool == "flagOrder":
        return flag_order(event["order_id"], FlagRequest(reason=event["reason"]))
    raise ValueError(f"Unknown tool: {tool_name}")

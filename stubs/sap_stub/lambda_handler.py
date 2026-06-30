"""AWS Lambda entrypoint for the dummy SAP API (deploy path).

The infra repo deploys this as a native AgentCore Gateway **Lambda target**: the Gateway
invokes the function (`lambda:InvokeFunction`) with the tool arguments as the `event` (a flat
map of the tool's inputSchema properties) and the MCP tool name in
`context.client_context.custom['bedrockAgentCoreToolName']` (format `"<target>___<tool>"`).
There is no HTTP layer on this path — the business logic lives in `app.py` and is called
directly. Locally, use `make sap` (the FastAPI app under uvicorn).
"""

from __future__ import annotations

from .app import credit_status

_DELIM = "___"


def handler(event, context):
    tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool = tool_name.split(_DELIM, 1)[1] if _DELIM in tool_name else tool_name
    if tool == "getCreditStatus":
        return credit_status(event["customer_id"])
    raise ValueError(f"Unknown tool: {tool_name}")

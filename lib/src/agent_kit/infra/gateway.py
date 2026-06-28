"""AgentCore Gateway MCP client — the tool transport.

The agent runs behind the CUSTOM_JWT Gateway: the backend tools (Snowflake reads, SAP
credit, order flagging) are served by the Gateway as MCP tools, authorized by Cedar and
brokered on-behalf-of the user via the target's OAUTH `grant_type=TOKEN_EXCHANGE`
credential. The agent forwards the inbound user JWT as the Gateway's bearer and mints
nothing itself.

The Gateway exposes each target as MCP tools named ``<target>___<operationId>`` — the same
names Cedar authorizes in policy.tf. The live set is discovered per session via
``list_tools_sync()``; the agent never hard-codes it. The ontology-action -> tool binding the
agent relies on lives in the agent's ``ACTIONS`` and is validated against this live surface at
startup.

Lifecycle: ``MCPClient`` runs the MCP session on a background thread and MUST be used as a
context manager spanning the whole agent invocation.
"""

from __future__ import annotations


def build_gateway_client(gateway_url: str, jwt: str):
    """An ``MCPClient`` bound to the Gateway, authenticated with the user's JWT."""
    # Lazy imports: the MCP transport is only needed on the deployed Gateway path.
    from mcp.client.streamable_http import streamablehttp_client
    from strands.tools.mcp import MCPClient

    headers = {"Authorization": f"Bearer {jwt}"}
    return MCPClient(lambda: streamablehttp_client(url=gateway_url, headers=headers))

"""AgentCore Gateway MCP client — the tool transport.

The agent runs behind the CUSTOM_JWT Gateway: the backend tools (Snowflake reads, SAP
credit, order flagging) are served by the Gateway as MCP tools, authorized by Cedar and
brokered on-behalf-of the user via the target's OAUTH `grant_type=TOKEN_EXCHANGE`
credential. The agent forwards the inbound user JWT as the Gateway's bearer and mints
nothing itself.

The Gateway exposes each target as MCP tools named ``<target>___<operationId>`` — the same
names Cedar authorizes in policy.tf. The live set is discovered per session via
``list_tools_sync()``; the agent never hard-codes it. The ontology-action -> tool binding the
agent relies on lives in the agent's ``ACTION_IMPLEMENTATIONS`` and is validated against this
live surface at startup.

Lifecycle: ``MCPClient`` runs the MCP session on a background thread and MUST be used as a
context manager spanning the whole agent invocation (see app.py).
"""

from __future__ import annotations

from agent_kit.config import get_config
from agent_kit.infra import identity


def build_gateway_client():
    """An ``MCPClient`` bound to the Gateway, authenticated with the current user's JWT.

    Returns ``None`` only when misconfigured — no ``GATEWAY_URL`` or no inbound user
    identity — which the runtime treats as a hard error (this runtime requires the
    CUSTOM_JWT Gateway).
    """
    cfg = get_config()
    ident = identity.current()
    if not cfg.gateway_url or ident is None:
        return None

    # Lazy imports: the MCP transport is only needed on the deployed Gateway path.
    from mcp.client.streamable_http import streamablehttp_client
    from strands.tools.mcp import MCPClient

    url = cfg.gateway_url
    headers = {"Authorization": f"Bearer {ident.raw_jwt}"}
    return MCPClient(lambda: streamablehttp_client(url=url, headers=headers))

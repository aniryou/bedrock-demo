"""AgentCore Gateway MCP client — the tool transport.

The agent runs behind the CUSTOM_JWT Gateway: the backend tools (Snowflake reads, SAP
credit, order flagging) are served by the Gateway as MCP tools, authorized by Cedar and
brokered on-behalf-of the user via the target's OAUTH `grant_type=TOKEN_EXCHANGE`
credential. The agent forwards the inbound user JWT as the Gateway's bearer and mints
nothing itself.

Tool names the Gateway exposes (== the Cedar action names in policy.tf):
    snowflake___getOrders, snowflake___getOrder, snowflake___getCustomer,
    sap___getCreditStatus, orders___flagOrder

Lifecycle: ``MCPClient`` runs the MCP session on a background thread and MUST be used as a
context manager spanning the whole agent invocation (see runtime.py).
"""

from __future__ import annotations

from . import identity
from .config import get_config


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

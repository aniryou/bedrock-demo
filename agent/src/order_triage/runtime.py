"""AgentCore Runtime entrypoint.

`build_app(SPEC)` (from `agent_kit`) wraps `build_agent(SPEC, ...)` in a
`BedrockAgentCoreApp`, exposing the `/invocations` and `/ping` endpoints AgentCore Runtime
expects, and streams the agent's output back.

The runtime is behind the CUSTOM_JWT Gateway: it forwards the inbound user JWT to the
Gateway, whose MCP tools serve the backends (Cedar-authorized, OBO-brokered via
TOKEN_EXCHANGE). Requires the `deploy` extra (installed in the container image); this
module is not imported by the tests.
"""

from __future__ import annotations

from agent_kit import build_app

from .spec import SPEC

app = build_app(SPEC)

if __name__ == "__main__":
    app.run()

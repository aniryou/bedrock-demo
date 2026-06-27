# agent_kit

`agent_kit` is the agent-agnostic Strands + AgentCore runtime toolkit. It packages the
infrastructure plumbing (Gateway MCP client, per-request user identity, AgentCore Memory
session manager) and the knowledge plumbing (skill loader, ontology, knowledge-base search,
and the action-coverage gate) so that a per-agent package only supplies an `AgentSpec` — its
id, metric namespace, action implementations, and prompt preamble — and consumes
`build_agent(spec, ...)` and `build_app(spec)` to stand up a deployable AgentCore Runtime.

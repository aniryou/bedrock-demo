"""agent_kit — the agent-agnostic Strands + AgentCore runtime toolkit.

`import agent_kit` succeeds with only the core deps (strands, boto3, pyyaml) installed:
`build_app` lazy-imports `bedrock_agentcore` inside the function, so the `deploy` extra is
required only at runtime-build time, not at import time.
"""

from __future__ import annotations

from agent_kit.agent import build_agent
from agent_kit.app import build_app
from agent_kit.config import Config, get_config
from agent_kit.knowledge.kb import make_kb_tool
from agent_kit.knowledge.ontology import describe_entity
from agent_kit.knowledge.skills import load_skill
from agent_kit.spec import AgentSpec
from agent_kit.stream_steps import step_events

__all__ = [
    "AgentSpec",
    "Config",
    "build_agent",
    "build_app",
    "describe_entity",
    "get_config",
    "load_skill",
    "make_kb_tool",
    "step_events",
]

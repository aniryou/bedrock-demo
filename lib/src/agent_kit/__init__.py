"""agent_kit — a toolkit of composable helpers for Strands + AgentCore agents.

The library is pure helpers with zero control flow and zero configuration decisions: the
consuming agent owns assembly (constructing its `BedrockModel` with its own guardrail/model
config) and the AgentCore Runtime loop, calling these helpers.

`import agent_kit` succeeds with only the core deps (strands, boto3, pyyaml) installed:
`bedrock_agentcore` and `mcp` are lazy-imported inside the helpers that need them, so the
`deploy` extra is required only at runtime-build time, not at import time.
"""

from __future__ import annotations

from agent_kit.infra import identity
from agent_kit.infra.gateway import build_gateway_client
from agent_kit.infra.identity import extract_user_jwt
from agent_kit.infra.memory import build_session_manager
from agent_kit.infra.metrics import emit_usage_metric
from agent_kit.knowledge.coverage import (
    SkillActionCoverageError,
    assert_action_coverage,
    tools_with_coverage,
)
from agent_kit.knowledge.kb import make_kb_tool
from agent_kit.knowledge.ontology import (
    OntologyLoader,
    describe_entity,
    ontology_loader,
)
from agent_kit.knowledge.skill_loader import SkillLoader, skill_loader
from agent_kit.knowledge.skills import load_skill
from agent_kit.prompt import build_system_prompt, request_metadata
from agent_kit.stream_steps import step_events, tool_result_text

__all__ = [
    "OntologyLoader",
    "SkillActionCoverageError",
    "SkillLoader",
    "assert_action_coverage",
    "build_gateway_client",
    "build_session_manager",
    "build_system_prompt",
    "describe_entity",
    "emit_usage_metric",
    "extract_user_jwt",
    "identity",
    "load_skill",
    "make_kb_tool",
    "ontology_loader",
    "request_metadata",
    "skill_loader",
    "step_events",
    "tool_result_text",
    "tools_with_coverage",
]

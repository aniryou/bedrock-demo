"""Environment-driven configuration.

The agent runs on AgentCore Runtime behind the CUSTOM_JWT Gateway. Every value is read
from the runtime environment in `Config.from_env()` (at call time, not in field defaults),
so changing an env var takes effect after clearing the `get_config` cache.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    # Model (Amazon Bedrock)
    bedrock_model_id: str
    aws_region: str
    max_tokens: int
    # Bedrock Guardrail (optional; BOTH must be set for the guardrail to apply — Strands
    # injects guardrailConfig only when guardrail_id and guardrail_version are both truthy).
    guardrail_id: str
    guardrail_version: str
    # AgentCore capabilities
    knowledge_base_id: str  # Bedrock Knowledge Base (search_policies)
    memory_id: str  # AgentCore Memory (session persistence)
    gateway_url: str  # AgentCore Gateway MCP endpoint (the backend tool transport)
    # Inbound user identity (CUSTOM_JWT)
    user_jwt_header: str  # inbound header carrying the user bearer (default 'Authorization')
    # Knowledge-repo artifacts fetched into the image (skills + ontology bindings)
    skills_dir: Path
    ontology_dir: Path

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            bedrock_model_id=os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-opus-4-8"),
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
            max_tokens=int(os.getenv("MAX_TOKENS", "2048")),
            guardrail_id=os.getenv("BEDROCK_GUARDRAIL_ID", "").strip(),
            guardrail_version=os.getenv("BEDROCK_GUARDRAIL_VERSION", "").strip(),
            knowledge_base_id=os.getenv("KNOWLEDGE_BASE_ID", "").strip(),
            memory_id=os.getenv("AGENTCORE_MEMORY_ID", "").strip(),
            gateway_url=os.getenv("GATEWAY_URL", "").strip(),
            user_jwt_header=os.getenv("USER_JWT_HEADER", "Authorization").strip(),
            skills_dir=Path(os.getenv("SKILLS_DIR", str(REPO_ROOT / "skills"))),
            ontology_dir=Path(os.getenv("ONTOLOGY_DIR", str(REPO_ROOT / "ontology"))),
        )


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config.from_env()

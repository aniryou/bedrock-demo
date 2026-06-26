# AgentCore Runtime + endpoint. The ARM64 image is built & pushed to ECR by the
# order-triage-agent repo's CI; infra consumes it by URI (var.agent_image_uri).
#
# Single runtime: inbound auth is the Microsoft Entra user JWT (CUSTOM_JWT). The agent
# forwards that JWT to the Gateway, whose MCP tools serve the backends (Cedar-authorized,
# OBO brokered via TOKEN_EXCHANGE). There is NO SigV4/service runtime — every invocation
# must present a user bearer token.

resource "aws_bedrockagentcore_agent_runtime" "this" {
  agent_runtime_name = local.name_prefix_us # AgentCore requires underscores
  role_arn           = aws_iam_role.runtime.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = var.agent_image_uri
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  # Inbound auth = Microsoft Entra user JWT. v1 discovery (inbound token is v1:
  # iss=https://sts.windows.net/<tenant>/); allowed_audience is the api:// form.
  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url    = "https://login.microsoftonline.com/${var.entra_tenant_id}/.well-known/openid-configuration"
      allowed_audience = ["api://${var.entra_agent_app_id}"]
    }
  }

  # Surface the inbound Authorization header so the agent can forward the user JWT to the
  # Gateway (runtime.py _extract_user_jwt -> gateway.py bearer).
  request_header_configuration {
    request_header_allowlist = ["Authorization"]
  }

  # Slim env: model + capability ids + the Gateway. Backend tools come from the Gateway
  # (no direct backend URLs/keys), and OBO is brokered by the Gateway (no in-agent mint).
  environment_variables = {
    BEDROCK_MODEL_ID    = var.bedrock_model_id
    MAX_TOKENS          = tostring(var.max_tokens)
    AGENTCORE_MEMORY_ID = aws_bedrockagentcore_memory.this.id
    KNOWLEDGE_BASE_ID   = aws_bedrockagent_knowledge_base.this.id
    GATEWAY_URL         = aws_bedrockagentcore_gateway.this.gateway_url
    USER_JWT_HEADER     = "Authorization"
    # Emit OTEL gen_ai latest-convention spans + content events (prompt/response/tool
    # messages) so AgentCore online Evaluations can read per-span content; gen_ai_tool_definitions
    # feeds the tool-accuracy evaluators. Captures full request/response content (incl. tool
    # results) unmasked into the runtime + eval-results log groups.
    OTEL_SEMCONV_STABILITY_OPT_IN = "gen_ai_latest_experimental,gen_ai_tool_definitions"
    # Guardrail (both empty when var.enable_guardrail=false -> agent injects no
    # guardrailConfig). Pass the bare guardrail_id (Strands semantics), not the ARN; bind the
    # version to the published number, never the base resource's DRAFT pointer.
    BEDROCK_GUARDRAIL_ID      = var.enable_guardrail ? aws_bedrock_guardrail.order_triage[0].guardrail_id : ""
    BEDROCK_GUARDRAIL_VERSION = var.enable_guardrail ? aws_bedrock_guardrail_version.order_triage[0].version : ""
  }
}

resource "aws_bedrockagentcore_agent_runtime_endpoint" "default" {
  agent_runtime_id = aws_bedrockagentcore_agent_runtime.this.agent_runtime_id
  name             = "default"
  # Track the runtime's current version so the endpoint rolls when the runtime updates.
  agent_runtime_version = aws_bedrockagentcore_agent_runtime.this.agent_runtime_version
}

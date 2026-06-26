output "memory_id" {
  value       = aws_bedrockagentcore_memory.this.id
  description = "Set as AGENTCORE_MEMORY_ID to use real Memory."
}

output "memory_log_group" {
  value       = module.observability.memory_log_group_name
  description = "CloudWatch Logs group receiving AgentCore Memory APPLICATION_LOGS."
}

output "knowledge_base_id" {
  value       = aws_bedrockagent_knowledge_base.this.id
  description = "Set as KNOWLEDGE_BASE_ID to use the real Knowledge Base."
}

output "gateway_url" {
  value       = aws_bedrockagentcore_gateway.this.gateway_url
  description = "Set as GATEWAY_URL to call the stubs through the Gateway."
}

output "sap_function_url" {
  value = aws_lambda_function_url.sap.function_url
}

output "order_actions_function_url" {
  value = aws_lambda_function_url.order_actions.function_url
}

output "agent_runtime_arn" {
  value = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
}

output "policy_engine_arn" {
  value = aws_bedrockagentcore_policy_engine.this.policy_engine_arn
}

output "entra_obo_provider_name" {
  value       = one(awscc_bedrockagentcore_o_auth_2_credential_provider.entra_obo[*].name)
  description = "Entra OBO credential provider name (MicrosoftOauth2 + tenant_id). Consumed by the Gateway's snowflake target TOKEN_EXCHANGE egress (terraform_data.snowflake_obo_egress) — not a runtime env. Null if Entra creds not supplied."
}

output "entra_obo_provider_arn" {
  value       = one(awscc_bedrockagentcore_o_auth_2_credential_provider.entra_obo[*].credential_provider_arn)
  description = "ARN of the Entra OBO credential provider (null if not created)."
}

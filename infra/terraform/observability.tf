# Observability lives in ./modules/observability: dashboards, alarms, SLOs, log/trace
# delivery, model-invocation logging, Contributor Insights, and saved queries. This block
# wires the module to the agent resources it observes.
module "observability" {
  source = "./modules/observability"

  name_prefix      = var.name_prefix
  region           = var.region
  account_id       = data.aws_caller_identity.current.account_id
  bedrock_model_id = var.bedrock_model_id

  memory_log_retention_days             = var.memory_log_retention_days
  bedrock_invocation_log_retention_days = var.bedrock_invocation_log_retention_days
  function_log_retention_days           = var.function_log_retention_days

  alert_email                  = var.alert_email
  model_input_usd_per_million  = var.model_input_usd_per_million
  model_output_usd_per_million = var.model_output_usd_per_million
  trace_indexing_percentage    = var.trace_indexing_percentage
  deploy_marker_ts             = var.deploy_marker_ts
  enable_online_evaluations    = var.enable_online_evaluations
  enable_actor_resolution      = var.enable_actor_resolution
  graph_resolver_secret_name   = var.graph_resolver_secret_name

  runtime_arn        = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
  runtime_id         = aws_bedrockagentcore_agent_runtime.this.agent_runtime_id
  gateway_arn        = aws_bedrockagentcore_gateway.this.gateway_arn
  gateway_id         = aws_bedrockagentcore_gateway.this.gateway_id
  memory_arn         = aws_bedrockagentcore_memory.this.arn
  memory_id          = aws_bedrockagentcore_memory.this.id
  knowledge_base_arn = aws_bedrockagent_knowledge_base.this.arn
  knowledge_base_id  = aws_bedrockagent_knowledge_base.this.id
}


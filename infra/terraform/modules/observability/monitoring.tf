# Alert notifications (SNS) + the metric-namespace locals the dashboards/alarms/SLOs share.
# CloudWatch metric namespaces this stack reads from:
#   AWS/Bedrock-AgentCore  vended runtime/gateway/memory/authz(Cedar)/identity(OBO) metrics;
#                          dims: Operation, Resource(=ARN), Name, Method/Protocol (gateway),
#                          StrategyId/StrategyType (memory)
#   bedrock-agentcore      OTEL app metrics: strands.* (by tool_name),
#                          gen_ai.client.* (by gen_ai.token.type / gen_ai.request.model)
#   ApplicationSignals     auto-instrumented golden signals + dependency map
#                          (Latency/Error/Fault/Throttle by Service x RemoteService)
#   OrderTriage/Agent      EMF token metric (InputTokens/OutputTokens/TotalTokens by
#                          agent_id + model_id), emitted to the runtime -DEFAULT log group

locals {
  # CloudWatch metric namespaces.
  ns_vended = "AWS/Bedrock-AgentCore" # the AWS-vended namespace (hyphen; not bedrock-agentcore)
  ns_otel   = "bedrock-agentcore"     # OTEL-exported app metrics
  ns_appsig = "ApplicationSignals"
  ns_tokens = "OrderTriage/Agent"

  name_prefix_us = replace(var.name_prefix, "-", "_") # order-triage -> order_triage

  # `Resource` metric-dimension values for the runtime + gateway.
  runtime_arn = var.runtime_arn
  gateway_arn = var.gateway_arn

  # Runtime-level vended metrics (Invocations/Latency/SystemErrors/Throttles/Sessions) carry
  # the dimension set [Name, Operation, Resource] — the [Operation, Resource]-only combo is
  # the gateway's. `Name` = "<runtime_name>::<endpoint>", endpoint DEFAULT.
  runtime_name_dim = "${local.name_prefix_us}::DEFAULT"

  # Application Signals canonical service for this agent: "<runtime_name>.DEFAULT".
  appsig_service     = "${local.name_prefix_us}.DEFAULT"
  appsig_environment = "bedrock-agentcore:default"

  # The agent_id emitted by the EMF token metric.
  agent_id = var.name_prefix

  # Log groups for the Logs Insights queries + Contributor Insights rules. The agent's EMF
  # token line + structured logs land in the runtime "-DEFAULT" group, not the vended
  # APPLICATION_LOGS group. EMF root fields for ranking: $.TotalTokens, $.InputTokens,
  # $.OutputTokens, $.actor_id, $.session_id.
  runtime_default_log_group  = "/aws/bedrock-agentcore/runtimes/${var.runtime_id}-DEFAULT"
  modelinvocations_log_group = aws_cloudwatch_log_group.bedrock_invocations.name
}

# Incident loop: anomaly + static metric alarms -> composite rollup -> SNS -> email. Not
# Incident Manager (closed to new customers); EventBridge/Chatbot can fan out off this topic.
resource "aws_sns_topic" "alerts" {
  name = "${var.name_prefix}-observability-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

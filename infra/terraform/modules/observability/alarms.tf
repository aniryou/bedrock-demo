# CloudWatch alarms (static fault + anomaly-band) rolled up by a composite, all notifying
# the SNS topic. treat_missing_data = "notBreaching" throughout: this demo agent idles for
# long stretches, so "missing" must not read as a fault. Static fault alarms fire on
# Sum > 0 over a single 5-min period; the cost alarm is anomaly-band based.

# --- Runtime faults (vended AWS/Bedrock-AgentCore) ---------------------------
resource "aws_cloudwatch_metric_alarm" "runtime_system_errors" {
  alarm_name          = "${var.name_prefix}-runtime-system-errors"
  alarm_description   = "AgentCore Runtime InvokeAgentRuntime SystemErrors > 0 (5xx from the managed runtime)."
  namespace           = local.ns_vended
  metric_name         = "SystemErrors"
  dimensions          = { Name = local.runtime_name_dim, Operation = "InvokeAgentRuntime", Resource = local.runtime_arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "runtime_throttles" {
  alarm_name          = "${var.name_prefix}-runtime-throttles"
  alarm_description   = "AgentCore Runtime InvokeAgentRuntime Throttles > 0 (capacity/quota pressure)."
  namespace           = local.ns_vended
  metric_name         = "Throttles"
  dimensions          = { Name = local.runtime_name_dim, Operation = "InvokeAgentRuntime", Resource = local.runtime_arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# --- OBO token-exchange failures (vended; security + availability signal) ----
# ResourceAccessTokenFetchFailures rolls up across ExceptionType/ProviderName; the
# undimensioned aggregate is the account-wide total. A failure here means the Gateway
# could not broker the per-user Snowflake OBO token (TOKEN_EXCHANGE) — users get denied.
resource "aws_cloudwatch_metric_alarm" "obo_failures" {
  alarm_name          = "${var.name_prefix}-obo-token-exchange-failures"
  alarm_description   = "AgentCore Identity ResourceAccessTokenFetchFailures > 0 — Entra OBO TOKEN_EXCHANGE failing (per-user Snowflake access broken)."
  namespace           = local.ns_vended
  metric_name         = "ResourceAccessTokenFetchFailures"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# --- Downstream faults (Application Signals; covers SAP/Snowflake/Bedrock/KB/Memory) -
# App Signals Fault on the agent service rolls up faults to ANY downstream dependency.
resource "aws_cloudwatch_metric_alarm" "appsig_service_faults" {
  alarm_name          = "${var.name_prefix}-service-faults"
  alarm_description   = "Application Signals Fault > 0 for the order-triage service (a downstream dependency — model/KB/memory/SAP/Snowflake — returned a fault)."
  namespace           = local.ns_appsig
  metric_name         = "Fault"
  dimensions          = { Service = local.appsig_service, Environment = local.appsig_environment }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

# --- Cost spike (anomaly band on the EMF token metric) -----------------------
# No USD metric exists natively; token volume is the leading cost indicator. Anomaly
# detection works on EMF custom metrics. The EMF line flushes per-turn, so a single 5-min
# period is adequate; paired with notBreaching for the idle demo.
resource "aws_cloudwatch_metric_alarm" "token_usage_anomaly" {
  alarm_name          = "${var.name_prefix}-token-usage-anomaly"
  alarm_description   = "Total Bedrock token usage breached its anomaly band (≈2σ) — unusual spend/usage. Token counts, not USD; dollarize via FINOPS-SPIKE price table."
  comparison_operator = "GreaterThanUpperThreshold"
  evaluation_periods  = 1
  threshold_metric_id = "ad1"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  metric_query {
    id          = "ad1"
    expression  = "ANOMALY_DETECTION_BAND(m1, 2)"
    label       = "TotalTokens (expected band)"
    return_data = true
  }
  metric_query {
    id          = "m1"
    return_data = true
    metric {
      namespace   = local.ns_tokens
      metric_name = "TotalTokens"
      dimensions  = { agent_id = local.agent_id, model_id = var.bedrock_model_id }
      period      = 300
      stat        = "Sum"
    }
  }
}

# --- Composite rollup: "agent unhealthy" -------------------------------------
# Single signal for the Exec + Operations dashboards. Any critical fault trips it.
resource "aws_cloudwatch_composite_alarm" "agent_unhealthy" {
  alarm_name        = "${var.name_prefix}-agent-unhealthy"
  alarm_description = "Rollup of critical agent faults: runtime 5xx, throttles, downstream faults, or OBO token-exchange failures."
  alarm_rule = join(" OR ", [
    "ALARM(\"${aws_cloudwatch_metric_alarm.runtime_system_errors.alarm_name}\")",
    "ALARM(\"${aws_cloudwatch_metric_alarm.runtime_throttles.alarm_name}\")",
    "ALARM(\"${aws_cloudwatch_metric_alarm.appsig_service_faults.alarm_name}\")",
    "ALARM(\"${aws_cloudwatch_metric_alarm.obo_failures.alarm_name}\")",
  ])
  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# --- KB ingestion FAILED (fed by the metric filter in observability.tf) ------
# Deliberately NOT in the agent-unhealthy composite: a failed KB sync is a data-freshness
# issue, not a live request-path fault.
resource "aws_cloudwatch_metric_alarm" "kb_ingestion_failed" {
  alarm_name          = "${var.name_prefix}-kb-ingestion-failed"
  alarm_description   = "Bedrock Knowledge Base ingestion job reported FAILED (job-level StatusChanged). Data may be stale."
  namespace           = "${var.name_prefix}/KnowledgeBase"
  metric_name         = "KBIngestionJobFailed"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
}

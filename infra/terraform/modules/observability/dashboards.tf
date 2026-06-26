# Four audience-scoped CloudWatch dashboards: Operations (app-eng + SRE: health, dependencies,
# tools, cost, quality), FinOps (finance), Governance / Audit (compliance + security), and a slim
# Exec rollup (leadership). Runtime metrics use the [Name, Operation, Resource] dimension set;
# cross-cut breakdowns use Metrics Insights (SELECT ... GROUP BY). Each board defaults to a 1-week
# window (start = -P7D) so the idle demo's panels show data on first load. Console drill-down is
# board-level: the Operations header deep-links to the X-Ray Trace Map / Transaction Search / GenAI
# Observability consoles, and queries.tf holds the saved Logs Insights queries. Stacked-area is used
# for additive series (counts, tokens); levels (latency, saturation, the anomaly band, eval score)
# stay as lines so the top of a stack is never a meaningless sum.

locals {
  # Namespace + metric name + dimension name/value pairs shared by the runtime widgets.
  _rt_dims = ["Name", local.runtime_name_dim, "Operation", "InvokeAgentRuntime", "Resource", local.runtime_arn]

  # Deploy marker: a vertical annotation rendered only when a deploy timestamp is supplied
  # (var.deploy_marker_ts, set by CI). Empty => no annotation, so the dashboards carry no
  # marker outside a real deploy.
  _deploy_annotation = var.deploy_marker_ts == "" ? {} : {
    vertical = [{ value = var.deploy_marker_ts, label = "deploy", color = "#2ca02c" }]
  }
  _release_md = "Deployed `${var.deploy_marker_ts == "" ? "local / not via CI" : var.deploy_marker_ts}`"

  # Default time window for every board: the demo is low-traffic, so a 1-week window is what
  # actually populates the panels.
  _dash_window = { start = "-P7D", periodOverride = "auto" }

  # Console deep-links shown in the Operations header (board-level triage entry points).
  _console_links = "[X-Ray Trace Map](https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#xray:traces/map) · [Transaction Search](https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#xray:traces/query) · [GenAI Observability](https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#gen-ai-observability)"

  # Quality note shown above the eval panel (folded in from the former Feedback board).
  _quality_note = var.enable_online_evaluations ? "**Quality** — online evaluations configured; scores not publishing yet. Human thumbs/rating feedback not instrumented." : "**Quality** — online evaluations not enabled. Human thumbs/rating feedback not instrumented."
}

# --- Operations dashboard (app-engineers + SRE): health -> dependencies -> tools -> cost -> quality ---
resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = "${var.name_prefix}-operations"
  dashboard_body = jsonencode(merge(local._dash_window, {
    widgets = [
      {
        type       = "text", x = 0, y = 0, width = 24, height = 2
        properties = { markdown = "## order-triage · Operations\n${local._console_links}" }
      },
      # --- On-call: active alarms ---
      {
        type = "alarm", x = 0, y = 2, width = 24, height = 2
        properties = {
          title = "Active alarms"
          alarms = [
            aws_cloudwatch_composite_alarm.agent_unhealthy.arn,
            aws_cloudwatch_metric_alarm.runtime_system_errors.arn,
            aws_cloudwatch_metric_alarm.runtime_throttles.arn,
            aws_cloudwatch_metric_alarm.appsig_service_faults.arn,
            aws_cloudwatch_metric_alarm.obo_failures.arn,
            aws_cloudwatch_metric_alarm.token_usage_anomaly.arn,
          ]
        }
      },
      # --- Golden-signal header (RED) ---
      {
        type = "metric", x = 0, y = 4, width = 6, height = 3
        properties = {
          title   = "Invocations", region = var.region, view = "singleValue", stat = "Sum", period = 300
          metrics = [concat([local.ns_vended, "Invocations"], local._rt_dims)]
        }
      },
      {
        type = "metric", x = 6, y = 4, width = 6, height = 3
        properties = {
          title   = "Latency (avg ms)", region = var.region, view = "singleValue", stat = "Average", period = 300
          metrics = [concat([local.ns_vended, "Latency"], local._rt_dims)]
        }
      },
      {
        type = "metric", x = 12, y = 4, width = 6, height = 3
        properties = {
          title   = "Sessions", region = var.region, view = "singleValue", stat = "Sum", period = 300
          metrics = [concat([local.ns_vended, "Sessions"], local._rt_dims)]
        }
      },
      {
        type = "metric", x = 18, y = 4, width = 6, height = 3
        properties = {
          title = "Errors & throttles", region = var.region, view = "timeSeries", stacked = true, stat = "Sum", period = 300
          yAxis = { left = { label = "Count", showUnits = false } }
          metrics = [
            concat([local.ns_vended, "SystemErrors"], local._rt_dims),
            concat([local.ns_vended, "UserErrors"], local._rt_dims),
            concat([local.ns_vended, "Throttles"], local._rt_dims),
          ]
        }
      },
      # --- Downstream dependency health (Application Signals) ---
      {
        type = "metric", x = 0, y = 7, width = 12, height = 6
        properties = {
          title   = "Downstream latency by dependency (App Signals)"
          region  = var.region, view = "timeSeries", period = 300
          yAxis   = { left = { label = "Latency (ms)", showUnits = false } }
          metrics = [[{ expression = "SELECT AVG(Latency) FROM \"ApplicationSignals\" WHERE Service = '${local.appsig_service}' GROUP BY RemoteService", label = "", id = "dep_lat" }]]
        }
      },
      {
        type = "metric", x = 12, y = 7, width = 12, height = 6
        properties = {
          title   = "Downstream faults by dependency (App Signals)"
          region  = var.region, view = "timeSeries", stacked = true, period = 300
          yAxis   = { left = { label = "Faults (count)", showUnits = false } }
          metrics = [[{ expression = "SELECT SUM(Fault) FROM \"ApplicationSignals\" WHERE Service = '${local.appsig_service}' GROUP BY RemoteService", label = "", id = "dep_fault" }]]
        }
      },
      # --- Per-tool latency + error rate (strands.* metrics, by tool) ---
      {
        type = "metric", x = 0, y = 13, width = 12, height = 6
        properties = {
          title   = "Per-tool duration (avg, by tool)"
          region  = var.region, view = "timeSeries", period = 300
          yAxis   = { left = { label = "Avg duration (s)", showUnits = false } }
          metrics = [[{ expression = "SELECT AVG(\"strands.tool.duration\") FROM \"bedrock-agentcore\" GROUP BY \"tool_name\"", label = "", id = "tool_dur" }]]
        }
      },
      {
        type = "metric", x = 12, y = 13, width = 12, height = 6
        properties = {
          title   = "Per-tool errors (sum, by tool)"
          region  = var.region, view = "timeSeries", stacked = true, period = 300
          yAxis   = { left = { label = "Errors (count)", showUnits = false } }
          metrics = [[{ expression = "SELECT SUM(\"strands.tool.error_count\") FROM \"bedrock-agentcore\" GROUP BY \"tool_name\"", label = "", id = "tool_err" }]]
        }
      },
      # --- Cost / usage: per-turn token volume + anomaly band ---
      {
        type = "metric", x = 0, y = 19, width = 12, height = 6
        properties = {
          title = "Token usage (per turn, In/Out)", region = var.region, view = "timeSeries", stacked = true, stat = "Sum", period = 300
          yAxis = { left = { label = "Tokens", showUnits = false } }
          metrics = [
            [local.ns_tokens, "InputTokens", "agent_id", local.agent_id, "model_id", var.bedrock_model_id],
            [local.ns_tokens, "OutputTokens", "agent_id", local.agent_id, "model_id", var.bedrock_model_id],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 19, width = 12, height = 6
        properties = {
          title = "Token usage vs anomaly band", region = var.region, view = "timeSeries", stat = "Sum", period = 300
          yAxis = { left = { label = "Tokens", showUnits = false } }
          metrics = [
            [local.ns_tokens, "TotalTokens", "agent_id", local.agent_id, "model_id", var.bedrock_model_id, { id = "m1" }],
            [{ expression = "ANOMALY_DETECTION_BAND(m1, 2)", label = "expected band", id = "ad1" }],
          ]
          annotations = local._deploy_annotation
        }
      },
      # --- Saturation (USE) + LLM call latency ---
      {
        type = "metric", x = 0, y = 25, width = 12, height = 6
        properties = {
          title = "Saturation (USE): vCPU-h / GB-h / sessions", region = var.region, view = "timeSeries", stat = "Sum", period = 3600
          yAxis = { left = { label = "vCPU-h / GB-h / sessions", showUnits = false } }
          metrics = [
            [local.ns_vended, "CPUUsed-vCPUHours", "Resource", local.runtime_arn, "Service", "AgentCore.Runtime"],
            [local.ns_vended, "MemoryUsed-GBHours", "Resource", local.runtime_arn, "Service", "AgentCore.Runtime"],
            concat([local.ns_vended, "Sessions"], local._rt_dims),
          ]
        }
      },
      {
        type = "metric", x = 12, y = 25, width = 12, height = 6
        properties = {
          title   = "LLM call latency by model (proxy for quality/perf regressions)"
          region  = var.region, view = "timeSeries", period = 3600
          yAxis   = { left = { label = "Latency (ms)", showUnits = false } }
          metrics = [[{ expression = "SELECT AVG(Latency) FROM \"ApplicationSignals\" WHERE Service = '${local.appsig_service}' AND RemoteService = 'AWS::BedrockRuntime' GROUP BY RemoteResourceIdentifier", label = "", id = "modlat" }]]
        }
      },
      # --- Quality / evaluation (folded in from the former Feedback board) ---
      {
        type       = "text", x = 0, y = 31, width = 24, height = 1
        properties = { markdown = local._quality_note }
      },
      {
        type = "metric", x = 0, y = 32, width = 24, height = 6
        properties = {
          title   = "Eval score trend (populates after enablement)"
          region  = var.region, view = "timeSeries", period = 3600
          yAxis   = { left = { label = "Score (0-1)", showUnits = false } }
          metrics = [[{ expression = "SELECT AVG(Score) FROM \"Bedrock-AgentCore-Evaluations\" GROUP BY EvaluatorName", label = "Avg score by evaluator", id = "evalscore" }]]
        }
      },
      # --- Deployment / version marker ---
      {
        type       = "text", x = 0, y = 38, width = 24, height = 1
        properties = { markdown = local._release_md }
      },
    ]
  }))
}

# --- FinOps dashboard (finance + eng-leads) ---
resource "aws_cloudwatch_dashboard" "finops" {
  dashboard_name = "${var.name_prefix}-finops"
  dashboard_body = jsonencode(merge(local._dash_window, {
    widgets = [
      {
        type       = "text", x = 0, y = 0, width = 24, height = 2
        properties = { markdown = "## order-triage · FinOps\nCosts are token×rate estimates; invoice-accurate per-actor spend comes from Cost Explorer / CUR." }
      },
      {
        type = "metric", x = 0, y = 2, width = 12, height = 6
        properties = {
          title = "Token volume (In/Out)", region = var.region, view = "timeSeries", stacked = true, stat = "Sum", period = 3600
          yAxis = { left = { label = "Tokens", showUnits = false } }
          metrics = [
            [local.ns_tokens, "InputTokens", "agent_id", local.agent_id, "model_id", var.bedrock_model_id],
            [local.ns_tokens, "OutputTokens", "agent_id", local.agent_id, "model_id", var.bedrock_model_id],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 2, width = 12, height = 6
        properties = {
          title = "Estimated cost (¢, token×rate)", region = var.region, view = "timeSeries", period = 3600
          yAxis = { left = { label = "Cost (¢)", showUnits = false } }
          metrics = [
            [local.ns_tokens, "InputTokens", "agent_id", local.agent_id, "model_id", var.bedrock_model_id, { id = "min", stat = "Sum", visible = false }],
            [local.ns_tokens, "OutputTokens", "agent_id", local.agent_id, "model_id", var.bedrock_model_id, { id = "mout", stat = "Sum", visible = false }],
            [{ expression = "100*((min/1000000*${var.model_input_usd_per_million})+(mout/1000000*${var.model_output_usd_per_million}))", label = "Est. cost (¢)", id = "cost" }],
          ]
        }
      },
      local._actors_widget,
      {
        type = "metric", x = 12, y = 8, width = 12, height = 6
        properties = {
          title       = "Top sessions by tokens (Contributor Insights)"
          region      = var.region, view = "timeSeries", stacked = true, period = 3600
          yAxis       = { left = { label = "Tokens", showUnits = false } }
          insightRule = { maxContributorCount = 10, orderBy = "Sum", ruleName = aws_cloudwatch_contributor_insight_rule.top_sessions_by_tokens.rule_name }
          legend      = { position = "bottom" }
        }
      },
      {
        type = "metric", x = 0, y = 14, width = 12, height = 6
        properties = {
          title   = "Tokens by downstream model (App Signals)"
          region  = var.region, view = "timeSeries", stacked = true, period = 3600
          yAxis   = { left = { label = "Tokens", showUnits = false } }
          metrics = [[{ expression = "SELECT SUM(InputTokens) FROM \"ApplicationSignals\" WHERE Service = '${local.appsig_service}' GROUP BY RemoteResourceIdentifier", label = "", id = "permodel" }]]
        }
      },
      {
        type = "metric", x = 12, y = 14, width = 12, height = 6
        properties = {
          title   = "Memory long-term-processing tokens (hidden cost)"
          region  = var.region, view = "timeSeries", stacked = true, period = 3600
          yAxis   = { left = { label = "Tokens", showUnits = false } }
          metrics = [[{ expression = "SELECT SUM(TokenCount) FROM \"AWS/Bedrock-AgentCore\" WHERE Operation = 'LongTermMemoryProcessing' GROUP BY StrategyType", label = "", id = "memtok" }]]
        }
      },
    ]
  }))
}

# --- Governance / Audit dashboard (compliance + security): audit table isolated atop, then auth/guardrail panels ---
resource "aws_cloudwatch_dashboard" "governance" {
  dashboard_name = "${var.name_prefix}-governance"
  dashboard_body = jsonencode(merge(local._dash_window, {
    widgets = [
      {
        type = "text", x = 0, y = 0, width = 24, height = 2
        properties = {
          markdown = "## order-triage · Governance / Audit\nModel-invocation logs are masked for 5 PII identifiers (email, US phone, SSN, driver's license, credit card). Config and policy changes: [CloudTrail Event history](https://${var.region}.console.aws.amazon.com/cloudtrailv2/home?region=${var.region}#/events)."
        }
      },
      # --- Append-only audit record, isolated at the top for evidentiary clarity. Resolved to
      # display names by the custom-widget Lambda when enable_actor_resolution = true. ---
      local._audit_widget,
      # --- Guardrail interventions (from Security) ---
      {
        type = "metric", x = 0, y = 10, width = 12, height = 6
        properties = {
          title   = "Guardrail interventions by policy type"
          region  = var.region, view = "timeSeries", stacked = true, period = 300
          yAxis   = { left = { label = "Interventions (count)", showUnits = false } }
          metrics = [[{ expression = "SELECT SUM(InvocationsIntervened) FROM \"AWS/Bedrock/Guardrails\" GROUP BY GuardrailPolicyType", label = "", id = "gpol" }]]
        }
      },
      {
        type = "metric", x = 12, y = 10, width = 12, height = 6
        properties = {
          title   = "Guardrail interventions by content source (in/out)"
          region  = var.region, view = "timeSeries", stacked = true, period = 300
          yAxis   = { left = { label = "Interventions (count)", showUnits = false } }
          metrics = [[{ expression = "SELECT SUM(InvocationsIntervened) FROM \"AWS/Bedrock/Guardrails\" GROUP BY GuardrailContentSource", label = "", id = "gsrc" }]]
        }
      },
      # --- Cedar authorization: by tool (Security) + by policy engine (Governance) ---
      {
        type = "metric", x = 0, y = 16, width = 12, height = 6
        properties = {
          title   = "Cedar authorization decisions by tool"
          region  = var.region, view = "timeSeries", stacked = true, period = 300
          yAxis   = { left = { label = "Allow decisions (count)", showUnits = false } }
          metrics = [[{ expression = "SELECT SUM(AllowDecisions) FROM \"AWS/Bedrock-AgentCore\" WHERE OperationName = 'PartiallyAuthorizeActions' GROUP BY ToolName", label = "", id = "cedar" }]]
        }
      },
      {
        type = "metric", x = 12, y = 16, width = 12, height = 6
        properties = {
          title   = "Cedar policy decisions by policy engine"
          region  = var.region, view = "timeSeries", stacked = true, period = 3600
          yAxis   = { left = { label = "Allow decisions (count)", showUnits = false } }
          metrics = [[{ expression = "SELECT SUM(AllowDecisions) FROM \"AWS/Bedrock-AgentCore\" GROUP BY PolicyEngine", label = "", id = "poleng" }]]
        }
      },
      # --- OBO token-exchange health (Security) ---
      {
        type = "metric", x = 0, y = 22, width = 12, height = 6
        properties = {
          title = "OBO token-exchange (success vs failure)", region = var.region, view = "timeSeries", stacked = true, stat = "Sum", period = 300
          yAxis = { left = { label = "Count", showUnits = false } }
          metrics = [
            [local.ns_vended, "ResourceAccessTokenFetchSuccess"],
            [local.ns_vended, "ResourceAccessTokenFetchFailures"],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 22, width = 12, height = 6
        properties = {
          title   = "OBO failures by exception type"
          region  = var.region, view = "timeSeries", stacked = true, period = 300
          yAxis   = { left = { label = "Failures (count)", showUnits = false } }
          metrics = [[{ expression = "SELECT SUM(ResourceAccessTokenFetchFailures) FROM \"AWS/Bedrock-AgentCore\" GROUP BY ExceptionType", label = "", id = "oboerr" }]]
        }
      },
      # --- Knowledge Base data-source access latency (Governance) ---
      {
        type = "metric", x = 0, y = 28, width = 24, height = 6
        properties = {
          title   = "Knowledge Base access latency (data-source access)"
          region  = var.region, view = "timeSeries", period = 3600
          yAxis   = { left = { label = "Latency (ms)", showUnits = false } }
          metrics = [[{ expression = "SELECT AVG(Latency) FROM \"ApplicationSignals\" WHERE Service = '${local.appsig_service}' AND RemoteResourceType = 'AWS::Bedrock::KnowledgeBase' GROUP BY RemoteResourceIdentifier", label = "", id = "kb" }]]
        }
      },
    ]
  }))
}

# --- Exec rollup dashboard (leadership) ---
resource "aws_cloudwatch_dashboard" "exec" {
  dashboard_name = "${var.name_prefix}-exec"
  dashboard_body = jsonencode(merge(local._dash_window, {
    widgets = [
      {
        type = "text", x = 0, y = 0, width = 24, height = 2
        properties = {
          markdown = "## order-triage · Executive rollup\nEst. cost is a token×rate estimate, not invoiced spend."
        }
      },
      {
        type = "metric", x = 0, y = 2, width = 5, height = 3
        properties = {
          title = "Success rate", region = var.region, view = "singleValue", period = 86400
          metrics = [
            concat([local.ns_vended, "Invocations"], local._rt_dims, [{ id = "inv", stat = "Sum", visible = false }]),
            concat([local.ns_vended, "Errors"], local._rt_dims, [{ id = "err", stat = "Sum", visible = false }]),
            [{ expression = "100*(inv-err)/inv", label = "Success %", id = "succ" }],
          ]
        }
      },
      {
        type = "metric", x = 5, y = 2, width = 5, height = 3
        properties = {
          title   = "Latency p99 (ms)", region = var.region, view = "singleValue", stat = "p99", period = 86400
          metrics = [[local.ns_appsig, "Latency", "Environment", local.appsig_environment, "Service", local.appsig_service]]
        }
      },
      {
        type = "metric", x = 10, y = 2, width = 5, height = 3
        properties = {
          title = "Est. cost (¢, token×rate)", region = var.region, view = "singleValue", period = 86400
          metrics = [
            [local.ns_tokens, "InputTokens", "agent_id", local.agent_id, "model_id", var.bedrock_model_id, { id = "min", stat = "Sum", visible = false }],
            [local.ns_tokens, "OutputTokens", "agent_id", local.agent_id, "model_id", var.bedrock_model_id, { id = "mout", stat = "Sum", visible = false }],
            [{ expression = "100*((min/1000000*${var.model_input_usd_per_million})+(mout/1000000*${var.model_output_usd_per_million}))", label = "Est. cost (¢)", id = "cost" }],
          ]
        }
      },
      {
        type = "metric", x = 15, y = 2, width = 5, height = 3
        properties = {
          title   = "Guardrail interventions", region = var.region, view = "singleValue", period = 86400
          metrics = [[{ expression = "SELECT SUM(InvocationsIntervened) FROM \"AWS/Bedrock/Guardrails\"", label = "Intervened", id = "gi" }]]
        }
      },
      {
        type       = "alarm", x = 20, y = 2, width = 4, height = 3
        properties = { title = "Agent health", alarms = [aws_cloudwatch_composite_alarm.agent_unhealthy.arn] }
      },
      {
        type = "metric", x = 0, y = 5, width = 12, height = 6
        properties = {
          title = "Invocations & errors (trend)", region = var.region, view = "timeSeries", stacked = true, stat = "Sum", period = 3600
          yAxis = { left = { label = "Count", showUnits = false } }
          metrics = [
            concat([local.ns_vended, "Invocations"], local._rt_dims),
            concat([local.ns_vended, "Errors"], local._rt_dims),
          ]
        }
      },
      {
        type = "metric", x = 12, y = 5, width = 12, height = 6
        properties = {
          title = "Token usage (trend)", region = var.region, view = "timeSeries", stacked = true, stat = "Sum", period = 3600
          yAxis = { left = { label = "Tokens", showUnits = false } }
          metrics = [
            [local.ns_tokens, "InputTokens", "agent_id", local.agent_id, "model_id", var.bedrock_model_id],
            [local.ns_tokens, "OutputTokens", "agent_id", local.agent_id, "model_id", var.bedrock_model_id],
          ]
        }
      },
      # --- Deployment / version marker ---
      {
        type       = "text", x = 0, y = 11, width = 24, height = 1
        properties = { markdown = local._release_md }
      },
    ]
  }))
}

# Observability is automatic on AgentCore Runtime (the image launches under
# opentelemetry-instrument with aws-opentelemetry-distro), so logs + metrics flow
# to CloudWatch with no extra config. Traces/spans need CloudWatch Transaction
# Search, which is two coupled account-level toggles:
#   1. a CloudWatch Logs resource policy letting X-Ray write spans to aws/spans
#   2. routing X-Ray trace segments to CloudWatch Logs
# (1) must exist before (2), or X-Ray's PutLogEvents to aws/spans is denied.

resource "aws_cloudwatch_log_resource_policy" "xray_spans" {
  policy_name = "xray-transaction-search-spans"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TransactionSearchXRayAccess"
      Effect    = "Allow"
      Principal = { Service = "xray.amazonaws.com" }
      Action    = "logs:PutLogEvents"
      Resource = [
        "arn:aws:logs:${var.region}:${var.account_id}:log-group:aws/spans:*",
        "arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/application-signals/data:*",
      ]
      Condition = {
        ArnLike      = { "aws:SourceArn" = "arn:aws:xray:${var.region}:${var.account_id}:*" }
        StringEquals = { "aws:SourceAccount" = var.account_id }
      }
    }]
  })
}

# Route X-Ray segments to CloudWatch Logs (Transaction Search). The resource policy
# above must exist AND propagate first — X-Ray's pre-flight PutLogEvents check can
# lag a few minutes after the policy is created on a fresh account — so this stays
# best-effort (|| true). If it no-ops on the very first apply, a re-run picks it up.
resource "terraform_data" "transaction_search" {
  depends_on       = [aws_cloudwatch_log_resource_policy.xray_spans]
  triggers_replace = [aws_cloudwatch_log_resource_policy.xray_spans.policy_document]
  provisioner "local-exec" {
    command = "aws xray update-trace-segment-destination --destination CloudWatchLogs --region ${var.region} || true"
  }
}

# --- AgentCore Memory observability --------------------------------------------
# Unlike the runtime, AgentCore does NOT auto-configure log/trace destinations for a
# memory resource — these are the IaC equivalent of the console "Log delivery" + "Tracing"
# toggles. We wire both: APPLICATION_LOGS -> a vended CloudWatch Logs group (memory
# extraction/consolidation + retrieval errors), and TRACES -> X-Ray (CreateEvent /
# RetrieveMemoryRecords spans, surfaced via the Transaction Search routing above). The
# XRAY delivery-destination type needs aws provider >= 6.21 (locked at 6.50).

resource "aws_cloudwatch_log_group" "memory" {
  # The /aws/vendedlogs/ prefix is auto-authorized for log delivery (no resource policy).
  name              = "/aws/vendedlogs/bedrock-agentcore/memory/APPLICATION_LOGS/${var.memory_id}"
  retention_in_days = var.memory_log_retention_days
}

resource "aws_cloudwatch_log_delivery_source" "memory_logs" {
  name         = "${var.name_prefix}-memory-app-logs"
  log_type     = "APPLICATION_LOGS"
  resource_arn = var.memory_arn
}

resource "aws_cloudwatch_log_delivery_source" "memory_traces" {
  name         = "${var.name_prefix}-memory-traces"
  log_type     = "TRACES"
  resource_arn = var.memory_arn
}

resource "aws_cloudwatch_log_delivery_destination" "memory_logs" {
  name = "${var.name_prefix}-memory-app-logs"
  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.memory.arn
  }
}

# X-Ray destination takes no delivery_destination_configuration (it's the X-Ray service).
resource "aws_cloudwatch_log_delivery_destination" "memory_traces" {
  name                      = "${var.name_prefix}-memory-traces"
  delivery_destination_type = "XRAY"
}

resource "aws_cloudwatch_log_delivery" "memory_logs" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.memory_logs.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.memory_logs.arn
}

resource "aws_cloudwatch_log_delivery" "memory_traces" {
  # Tracing requires Transaction Search to be enabled first (see above).
  depends_on               = [terraform_data.transaction_search]
  delivery_source_name     = aws_cloudwatch_log_delivery_source.memory_traces.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.memory_traces.arn
}

# --- AgentCore Runtime + Gateway log/trace delivery ---------------------------
# Like Memory, the Runtime and Gateway resources do not auto-configure destinations, so
# each gets the delivery_source -> delivery_destination -> delivery trio: APPLICATION_LOGS
# (+ USAGE_LOGS for the runtime) to CloudWatch Logs, and TRACES to X-Ray, which surfaces
# the gen_ai/tool spans in aws/spans via Transaction Search. The aws/spans PutLogEvents
# grant (aws_cloudwatch_log_resource_policy.xray_spans, above) covers these. Identity/
# WorkloadIdentity has no standalone resource — it traces transitively via these.

# Runtime APPLICATION_LOGS -> vended CloudWatch Logs group.
resource "aws_cloudwatch_log_group" "runtime_app" {
  name              = "/aws/vendedlogs/bedrock-agentcore/runtime/APPLICATION_LOGS/${var.runtime_id}"
  retention_in_days = var.memory_log_retention_days
}

resource "aws_cloudwatch_log_delivery_source" "runtime_logs" {
  name         = "${var.name_prefix}-runtime-app-logs"
  log_type     = "APPLICATION_LOGS"
  resource_arn = var.runtime_arn
}

resource "aws_cloudwatch_log_delivery_destination" "runtime_logs" {
  name = "${var.name_prefix}-runtime-app-logs"
  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.runtime_app.arn
  }
}

resource "aws_cloudwatch_log_delivery" "runtime_logs" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.runtime_logs.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.runtime_logs.arn
}

# Runtime USAGE_LOGS -> vended CloudWatch Logs group: per-session 1-sec vCPU/GB-hours,
# the only native per-session resource-cost signal.
resource "aws_cloudwatch_log_group" "runtime_usage" {
  name              = "/aws/vendedlogs/bedrock-agentcore/runtime/USAGE_LOGS/${var.runtime_id}"
  retention_in_days = var.memory_log_retention_days
}

resource "aws_cloudwatch_log_delivery_source" "runtime_usage" {
  name         = "${var.name_prefix}-runtime-usage-logs"
  log_type     = "USAGE_LOGS"
  resource_arn = var.runtime_arn
}

resource "aws_cloudwatch_log_delivery_destination" "runtime_usage" {
  name = "${var.name_prefix}-runtime-usage-logs"
  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.runtime_usage.arn
  }
}

resource "aws_cloudwatch_log_delivery" "runtime_usage" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.runtime_usage.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.runtime_usage.arn
}

# Runtime TRACES -> X-Ray: emits the gen_ai/service spans into aws/spans via Transaction
# Search. The XRAY destination takes no config block (it is the X-Ray service).
resource "aws_cloudwatch_log_delivery_source" "runtime_traces" {
  name         = "${var.name_prefix}-runtime-traces"
  log_type     = "TRACES"
  resource_arn = var.runtime_arn
}

resource "aws_cloudwatch_log_delivery_destination" "runtime_traces" {
  name                      = "${var.name_prefix}-runtime-traces"
  delivery_destination_type = "XRAY"
}

resource "aws_cloudwatch_log_delivery" "runtime_traces" {
  # Tracing requires Transaction Search enabled + propagated first (see top of file).
  depends_on               = [terraform_data.transaction_search]
  delivery_source_name     = aws_cloudwatch_log_delivery_source.runtime_traces.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.runtime_traces.arn
}

# Gateway APPLICATION_LOGS -> vended CloudWatch Logs group (tool-call payloads).
resource "aws_cloudwatch_log_group" "gateway_app" {
  name              = "/aws/vendedlogs/bedrock-agentcore/gateway/APPLICATION_LOGS/${var.gateway_id}"
  retention_in_days = var.memory_log_retention_days
}

resource "aws_cloudwatch_log_delivery_source" "gateway_logs" {
  name         = "${var.name_prefix}-gateway-app-logs"
  log_type     = "APPLICATION_LOGS"
  resource_arn = var.gateway_arn
}

resource "aws_cloudwatch_log_delivery_destination" "gateway_logs" {
  name = "${var.name_prefix}-gateway-app-logs"
  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.gateway_app.arn
  }
}

resource "aws_cloudwatch_log_delivery" "gateway_logs" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.gateway_logs.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.gateway_logs.arn
}

# Gateway TRACES -> X-Ray: the two-span Call-Tool structure (SERVER + CLIENT with
# TargetExecutionTime) covering the Gateway->Lambda hop, plus the Identity OBO
# GetWorkloadAccessTokenForJWT(issuer, user_sub) spans.
resource "aws_cloudwatch_log_delivery_source" "gateway_traces" {
  name         = "${var.name_prefix}-gateway-traces"
  log_type     = "TRACES"
  resource_arn = var.gateway_arn
}

resource "aws_cloudwatch_log_delivery_destination" "gateway_traces" {
  name                      = "${var.name_prefix}-gateway-traces"
  delivery_destination_type = "XRAY"
}

resource "aws_cloudwatch_log_delivery" "gateway_traces" {
  depends_on               = [terraform_data.transaction_search]
  delivery_source_name     = aws_cloudwatch_log_delivery_source.gateway_traces.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.gateway_traces.arn
}

# --- Knowledge Base ingestion logging -----------------------------------------
# A Bedrock Knowledge Base vends APPLICATION_LOGS only (no TRACES leg), and the delivery
# source is the KB ARN, not the data-source ARN. The /aws/vendedlogs/ prefix is auto-
# authorized (no resource policy); this is CloudWatch Logs, so no transaction_search dep.
resource "aws_cloudwatch_log_group" "kb_app" {
  name              = "/aws/vendedlogs/bedrock/knowledge-base/APPLICATION_LOGS/${var.knowledge_base_id}"
  retention_in_days = var.memory_log_retention_days
}

resource "aws_cloudwatch_log_delivery_source" "kb_logs" {
  name         = "${var.name_prefix}-kb-app-logs"
  log_type     = "APPLICATION_LOGS" # the ONLY log_type a KB supports
  resource_arn = var.knowledge_base_arn
}

resource "aws_cloudwatch_log_delivery_destination" "kb_logs" {
  name = "${var.name_prefix}-kb-app-logs"
  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.kb_app.arn
  }
}

resource "aws_cloudwatch_log_delivery" "kb_logs" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.kb_logs.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.kb_logs.arn
}

# FAILED-ingestion metric filter (no native AWS/Bedrock ingestion metric exists); the
# alarm on this metric lives in alarms.tf. The job-level pattern is provisional until
# confirmed against a real record — the resource-level form is $.event.status in
# {EMBEDDING_FAILED, INDEXING_FAILED, ...}, or broaden to { $.level = "ERROR" }.
resource "aws_cloudwatch_log_metric_filter" "kb_ingestion_failed" {
  log_group_name = aws_cloudwatch_log_group.kb_app.name
  name           = "${var.name_prefix}-kb-ingestion-failed"
  pattern        = "{ $.event_type = \"StartIngestionJob.StatusChanged\" && $.event.ingestion_job_status = \"FAILED\" }"
  metric_transformation {
    name          = "KBIngestionJobFailed"
    namespace     = "${var.name_prefix}/KnowledgeBase"
    value         = "1"
    default_value = "0"
  }
}

# --- Transaction Search indexing rate -----------------------------------------
# "Default" is the singleton indexing rule Transaction Search provisions. Indexing % is a
# COST + search-index lever ONLY — it does NOT reduce span STORAGE in aws/spans (head
# sampling + retention + data-protection govern PII volume).
resource "aws_xray_indexing_rule" "default" {
  name = "Default"
  rule {
    probabilistic {
      desired_sampling_percentage = var.trace_indexing_percentage
    }
  }
  depends_on = [terraform_data.transaction_search]
}

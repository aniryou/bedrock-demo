# Render-time actor resolution (opt-in; ADR-0007). A CloudWatch custom-widget Lambda ranks token
# spend by the Entra directory id (`actor_oid`, emitted by the agent runtime) and resolves each
# oid -> display name via Microsoft Graph AT RENDER TIME. Stored telemetry stays opaque (the oid
# is a PII-free GUID); the display name lives only in the render path. Gated by
# var.enable_actor_resolution because it needs an out-of-band Entra app + Graph secret (see the
# entra/ module's graph_resolver app + `make seed-graph-secret`).

# Top actors ranked by the Graph-resolvable oid (vs. the opaque pairwise sub the other rule uses).
resource "aws_cloudwatch_contributor_insight_rule" "top_actors_by_oid" {
  count      = var.enable_actor_resolution ? 1 : 0
  rule_name  = "${var.name_prefix}-top-actors-by-oid"
  rule_state = "ENABLED"
  rule_definition = jsonencode({
    Schema        = { Name = "CloudWatchLogRule", Version = 1 }
    LogGroupNames = [local.runtime_default_log_group]
    LogFormat     = "JSON"
    Contribution = {
      Keys    = ["$.actor_oid"]
      ValueOf = "$.TotalTokens"
      Filters = [{ Match = "$.actor_oid", IsPresent = true }] # ignore turns with no oid claim
    }
    AggregateOn = "Sum"
  })
}

# Graph app creds {tenant_id, client_id, client_secret}; seeded out-of-band, never in TF state.
data "aws_secretsmanager_secret" "graph_resolver" {
  count = var.enable_actor_resolution ? 1 : 0
  name  = var.graph_resolver_secret_name
}

data "archive_file" "actor_resolver" {
  count       = var.enable_actor_resolution ? 1 : 0
  type        = "zip"
  source_file = "${path.module}/lambda/actor_resolver.py"
  output_path = "${path.module}/lambda/actor_resolver.zip"
}

resource "aws_iam_role" "actor_resolver" {
  count = var.enable_actor_resolution ? 1 : 0
  name  = "${var.name_prefix}-actor-resolver"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "actor_resolver_basic" {
  count      = var.enable_actor_resolution ? 1 : 0
  role       = aws_iam_role.actor_resolver[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "actor_resolver" {
  count = var.enable_actor_resolution ? 1 : 0
  name  = "actor-resolver"
  role  = aws_iam_role.actor_resolver[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # GetInsightRuleReport has no resource-level scoping (read-only over rules).
      { Sid = "ReadInsightRule", Effect = "Allow", Action = ["cloudwatch:GetInsightRuleReport"], Resource = "*" },
      { Sid = "ReadGraphSecret", Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = data.aws_secretsmanager_secret.graph_resolver[0].arn },
      # Audit mode: Logs Insights over the (masked) model-invocation group. StopQuery/
      # GetQueryResults are query-id scoped (no resource-level ARN).
      { Sid = "StartAuditQuery", Effect = "Allow", Action = ["logs:StartQuery"], Resource = "${aws_cloudwatch_log_group.bedrock_invocations.arn}:*" },
      { Sid = "ReadAuditQuery", Effect = "Allow", Action = ["logs:GetQueryResults", "logs:StopQuery"], Resource = "*" },
    ]
  })
}

resource "aws_lambda_function" "actor_resolver" {
  count            = var.enable_actor_resolution ? 1 : 0
  function_name    = "${var.name_prefix}-actor-resolver"
  role             = aws_iam_role.actor_resolver[0].arn
  handler          = "actor_resolver.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  timeout          = 30 # audit mode polls Logs Insights to completion
  filename         = data.archive_file.actor_resolver[0].output_path
  source_code_hash = data.archive_file.actor_resolver[0].output_base64sha256

  environment {
    variables = {
      INSIGHT_RULE_NAME          = aws_cloudwatch_contributor_insight_rule.top_actors_by_oid[0].rule_name
      GRAPH_SECRET_NAME          = var.graph_resolver_secret_name
      MODELINVOCATIONS_LOG_GROUP = local.modelinvocations_log_group
      MAX_ACTORS                 = "10"
    }
  }
}

# The FinOps "Top actors" widget: the Graph-resolved custom widget when resolution is enabled,
# else the opaque-sub Contributor Insights leaderboard. The two widget shapes don't unify as a
# Terraform conditional (custom vs. metric), so encode each to a string and decode the choice.
locals {
  _actors_widget = jsondecode(var.enable_actor_resolution ? jsonencode({
    type   = "custom"
    x      = 0
    y      = 8
    width  = 12
    height = 6
    properties = {
      title    = "Top actors by tokens (resolved)"
      endpoint = one(aws_lambda_function.actor_resolver[*].arn)
      params   = { mode = "leaderboard" }
      updateOn = { refresh = true, resize = true, timeRange = true }
    }
    }) : jsonencode({
    type   = "metric"
    x      = 0
    y      = 8
    width  = 12
    height = 6
    properties = {
      title       = "Top actors by tokens (opaque Entra subject)"
      region      = var.region
      view        = "timeSeries"
      stacked     = true
      period      = 3600
      yAxis       = { left = { label = "Tokens", showUnits = false } }
      insightRule = { maxContributorCount = 10, orderBy = "Sum", ruleName = aws_cloudwatch_contributor_insight_rule.top_actors_by_tokens.rule_name }
      legend      = { position = "bottom" }
    }
  }))

  # Governance per-turn audit table: actor column resolved (custom widget) when enabled, else the
  # native Logs Insights table (which now also surfaces the raw actor_oid column).
  _audit_widget = jsondecode(var.enable_actor_resolution ? jsonencode({
    type   = "custom"
    x      = 0
    y      = 2
    width  = 24
    height = 8
    properties = {
      title    = "Per-turn model invocations (actor resolved)"
      endpoint = one(aws_lambda_function.actor_resolver[*].arn)
      params   = { mode = "audit" }
      updateOn = { refresh = true, resize = true, timeRange = true }
    }
    }) : jsonencode({
    type   = "log"
    x      = 0
    y      = 2
    width  = 24
    height = 8
    properties = {
      title  = "Per-turn model invocations (append-only record)"
      region = var.region
      view   = "table"
      query  = "SOURCE '${local.modelinvocations_log_group}' | fields @timestamp, modelId, identity.arn, input.inputTokenCount, output.outputTokenCount, requestMetadata.turn, requestMetadata.actor, requestMetadata.actor_oid, requestMetadata.session | sort @timestamp desc | limit 200"
    }
  }))
}

# Contributor Insights rules + Logs Insights saved queries powering the FinOps "top
# spenders" leaderboards and the FinOps/Governance drill-downs. Contributor Insights ranks
# high-cardinality contributors (actor/session) straight from JSON log fields, with no
# metric dimensions. The agent's EMF line in the runtime -DEFAULT group carries
# $.actor_id / $.session_id / $.TotalTokens.

# Top actors by total tokens — the FinOps "who is spending" leaderboard.
resource "aws_cloudwatch_contributor_insight_rule" "top_actors_by_tokens" {
  rule_name  = "${var.name_prefix}-top-actors-by-tokens"
  rule_state = "ENABLED"
  rule_definition = jsonencode({
    Schema        = { Name = "CloudWatchLogRule", Version = 1 }
    LogGroupNames = [local.runtime_default_log_group]
    LogFormat     = "JSON"
    Contribution = {
      Keys    = ["$.actor_id"]
      ValueOf = "$.TotalTokens"
      Filters = []
    }
    AggregateOn = "Sum"
  })
}

# Top sessions by total tokens — the FinOps "which conversation is expensive" view.
resource "aws_cloudwatch_contributor_insight_rule" "top_sessions_by_tokens" {
  rule_name  = "${var.name_prefix}-top-sessions-by-tokens"
  rule_state = "ENABLED"
  rule_definition = jsonencode({
    Schema        = { Name = "CloudWatchLogRule", Version = 1 }
    LogGroupNames = [local.runtime_default_log_group]
    LogFormat     = "JSON"
    Contribution = {
      Keys    = ["$.session_id"]
      ValueOf = "$.TotalTokens"
      Filters = []
    }
    AggregateOn = "Sum"
  })
}

# --- Logs Insights saved queries (one-click drill-downs) ---------------------
resource "aws_cloudwatch_query_definition" "tokens_by_session" {
  name            = "${var.name_prefix}/FinOps - tokens by session+actor"
  log_group_names = [local.runtime_default_log_group]
  query_string    = <<-EOQ
    fields actor_id, session_id, InputTokens, OutputTokens, TotalTokens
    | filter ispresent(TotalTokens)
    | stats sum(TotalTokens) as total_tokens, sum(InputTokens) as input_tokens, sum(OutputTokens) as output_tokens, count(*) as turns by session_id, actor_id
    | sort total_tokens desc
  EOQ
}

resource "aws_cloudwatch_query_definition" "model_invocations_by_turn" {
  name            = "${var.name_prefix}/Governance - model invocations by turn"
  log_group_names = [local.modelinvocations_log_group]
  query_string    = <<-EOQ
    fields @timestamp, modelId, identity.arn, input.inputTokenCount, output.outputTokenCount, requestMetadata.turn, requestMetadata.actor, requestMetadata.session
    | sort @timestamp desc
    | limit 200
  EOQ
}

resource "aws_cloudwatch_query_definition" "tokens_per_turn_cost" {
  name            = "${var.name_prefix}/FinOps - tokens+est-cost per turn"
  log_group_names = [local.modelinvocations_log_group]
  query_string    = <<-EOQ
    fields modelId, requestMetadata.turn as turn, input.inputTokenCount as in_tok, output.outputTokenCount as out_tok
    | stats sum(in_tok) as input_tokens, sum(out_tok) as output_tokens by turn, modelId
    | sort input_tokens desc
  EOQ
}

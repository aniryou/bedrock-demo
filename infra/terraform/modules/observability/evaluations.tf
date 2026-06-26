# AgentCore online Evaluations: an LLM judge scores sampled agent traces (from aws/spans)
# and publishes scores to the Bedrock-AgentCore-Evaluations CloudWatch namespace, which the
# Operations dashboard's eval panel reads. Gated by var.enable_online_evaluations — online evaluation runs
# a judge model per sampled trace (ongoing cost), so it is opt-in. Built-in evaluators are
# referenced directly; there is no native TF resource for the config, so it is created via
# the CLI in a terraform_data local-exec (same pattern as the SLOs).

locals {
  online_eval_payload = jsonencode({
    onlineEvaluationConfigName = "${local.name_prefix_us}_online_evals" # must match [a-zA-Z][a-zA-Z0-9_]{0,47} (no hyphens)
    description                = "LLM-judge evaluation of ${var.name_prefix} agent traces"
    rule                       = { samplingConfig = { samplingPercentage = 100 } }
    dataSourceConfig = {
      cloudWatchLogs = {
        # aws/spans carries the trace spans; the runtime -DEFAULT group carries the per-span
        # gen_ai content events (input/output messages) the judge correlates by spanId.
        logGroupNames = ["aws/spans", local.runtime_default_log_group]
        serviceNames  = ["${local.name_prefix_us}.DEFAULT"]
      }
    }
    evaluators = [
      { evaluatorId = "Builtin.Correctness" },
      { evaluatorId = "Builtin.Helpfulness" },
      { evaluatorId = "Builtin.Faithfulness" },
      { evaluatorId = "Builtin.ToolSelectionAccuracy" },
      { evaluatorId = "Builtin.ToolParameterAccuracy" },
    ]
    evaluationExecutionRoleArn = one(aws_iam_role.evaluations[*].arn)
    enableOnCreate             = true
  })
}

# Execution role the evaluation service assumes: read the trace log group, invoke the judge
# model, publish the score metrics.
resource "aws_iam_role" "evaluations" {
  count = var.enable_online_evaluations ? 1 : 0
  name  = "${var.name_prefix}-evaluations-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = var.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "evaluations" {
  count = var.enable_online_evaluations ? 1 : 0
  name  = "evaluations-exec"
  role  = aws_iam_role.evaluations[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # ReadTraces + field-index access: the eval service reads (and may manage) the field-index
      # policy on the trace log groups (aws/spans) to query them. Without the *IndexPolic*/field
      # perms the create fails "Access denied when accessing index policy for aws/spans".
      { Sid = "ReadTraces", Effect = "Allow", Action = ["logs:StartQuery", "logs:GetQueryResults", "logs:GetLogEvents", "logs:FilterLogEvents", "logs:DescribeLogGroups", "logs:DescribeIndexPolicies", "logs:PutIndexPolicy", "logs:DescribeFieldIndexes", "logs:GetLogGroupFields"], Resource = "*" },
      # Evaluations writes results to its own /aws/bedrock-agentcore/evaluations/ group.
      { Sid = "WriteResults", Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:PutRetentionPolicy", "logs:DescribeLogStreams"], Resource = ["arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/bedrock-agentcore/evaluations/*", "arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/bedrock-agentcore/evaluations/*:*"] },
      { Sid = "InvokeJudge", Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = "*" },
      { Sid = "PublishScores", Effect = "Allow", Action = ["cloudwatch:PutMetricData"], Resource = "*" },
    ]
  })
}

resource "terraform_data" "online_evaluations" {
  count            = var.enable_online_evaluations ? 1 : 0
  input            = { region = var.region, name = "${local.name_prefix_us}_online_evals" }
  triggers_replace = [local.online_eval_payload]
  depends_on       = [aws_iam_role_policy.evaluations]

  # Retry on the exec-role permission-propagation errors: the role policy is created/updated in
  # the same apply and IAM is eventually consistent, so the create's sequential permission checks
  # may run before the grant propagates. This surfaces as either "does not have permissions to
  # access the specified log groups" (log-group check) OR "Access denied when accessing index
  # policy for aws/spans" (index-policy check) — retry on both; any other error fails fast.
  provisioner "local-exec" {
    command = <<-EOC
      existing="$(aws bedrock-agentcore-control list-online-evaluation-configs --region ${var.region} --query "onlineEvaluationConfigs[?onlineEvaluationConfigName=='${local.name_prefix_us}_online_evals'].onlineEvaluationConfigId | [0]" --output text 2>/dev/null)"
      if [ -n "$existing" ] && [ "$existing" != "None" ]; then echo "eval config already exists ($existing); skipping create"; exit 0; fi
      for i in 1 2 3 4 5 6; do
        out="$(aws bedrock-agentcore-control create-online-evaluation-config --region ${var.region} --cli-input-json '${local.online_eval_payload}' 2>&1)" && exit 0
        echo "$out"
        echo "$out" | grep -qiE "does not have permissions|access denied" || exit 1
        echo "exec-role IAM not propagated yet; retry $i/6 in 15s"; sleep 15
      done
      exit 1
    EOC
  }
  provisioner "local-exec" {
    when    = destroy
    command = "id=$(aws bedrock-agentcore-control list-online-evaluation-configs --region ${self.input.region} --query \"onlineEvaluationConfigs[?onlineEvaluationConfigName=='${self.input.name}'].onlineEvaluationConfigId | [0]\" --output text 2>/dev/null); [ -n \"$id\" ] && [ \"$id\" != \"None\" ] && aws bedrock-agentcore-control delete-online-evaluation-config --region ${self.input.region} --online-evaluation-config-id \"$id\" || true"
  }
}

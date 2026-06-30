# Order-actions API as a Lambda Function URL — the second Gateway target (flagging).
# Zip published to the artifacts bucket (stubs/order_actions.zip) by bedrock-demo-stubs.

# source_code_hash forces UpdateFunctionCode when the published zip changes (see sap_lambda.tf).
data "aws_s3_object" "order_actions_zip" {
  bucket = var.artifacts_bucket
  key    = "stubs/order_actions.zip"
}

resource "aws_lambda_function" "order_actions" {
  function_name    = "${var.name_prefix}-order-actions"
  role             = aws_iam_role.sap_lambda.arn
  handler          = "order_actions_stub.lambda_handler.handler"
  runtime          = var.lambda_runtime
  architectures    = var.lambda_architectures
  timeout          = var.lambda_timeout
  s3_bucket        = var.artifacts_bucket
  s3_key           = "stubs/order_actions.zip"
  source_code_hash = data.aws_s3_object.order_actions_zip.etag

  environment {
    variables = {
      # Outbound key for the direct call to the Snowflake data Lambda (its URL stays NONE).
      SNOWFLAKE_DATA_URL = trimsuffix(aws_lambda_function_url.snowflake.function_url, "/")
      SNOWFLAKE_API_KEY  = var.snowflake_api_key
    }
  }
}

# Native AgentCore Gateway Lambda target (gateway.tf): invoked directly, no Function URL.
# Identity-side grant is on the Gateway role (iam.tf); this resource policy grants the
# AgentCore service principal scoped to this account's gateways.
resource "aws_lambda_permission" "order_actions_gateway" {
  statement_id  = "AllowAgentCoreGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.order_actions.function_name
  principal     = "bedrock-agentcore.amazonaws.com"
  source_arn    = "arn:aws:bedrock-agentcore:${var.region}:${local.account_id}:gateway/*"
}

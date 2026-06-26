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

resource "aws_lambda_function_url" "order_actions" {
  function_name = aws_lambda_function.order_actions.function_name
  # Locked to IAM: only the AgentCore Gateway role may invoke (SigV4).
  authorization_type = "AWS_IAM"
}

resource "aws_lambda_permission" "order_actions_url" {
  statement_id           = "AllowGatewayFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.order_actions.function_name
  principal              = aws_iam_role.gateway.arn
  function_url_auth_type = "AWS_IAM"
}

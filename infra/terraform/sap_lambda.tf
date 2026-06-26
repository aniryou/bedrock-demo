# Dummy SAP API as a Lambda Function URL. The zip is built & published to the
# artifacts bucket (stubs/sap.zip) by bedrock-demo-stubs; infra references it by key.

# Without source_code_hash the provider tracks only the s3_key STRING, so a re-published
# zip would NOT trigger UpdateFunctionCode — leaving stale code live. The object's etag
# changes with content, so referencing it forces a code update on a new publish.
data "aws_s3_object" "sap_zip" {
  bucket = var.artifacts_bucket
  key    = "stubs/sap.zip"
}

resource "aws_lambda_function" "sap" {
  function_name    = "${var.name_prefix}-sap"
  role             = aws_iam_role.sap_lambda.arn
  handler          = "sap_stub.lambda_handler.handler"
  runtime          = var.lambda_runtime
  architectures    = var.lambda_architectures
  timeout          = var.lambda_timeout
  s3_bucket        = var.artifacts_bucket
  s3_key           = "stubs/sap.zip"
  source_code_hash = data.aws_s3_object.sap_zip.etag
}

resource "aws_lambda_function_url" "sap" {
  function_name = aws_lambda_function.sap.function_name
  # Locked to IAM: only the AgentCore Gateway role may invoke (SigV4). No public access
  # and no app-layer key — the Gateway target's gateway_iam_role credential signs the call.
  authorization_type = "AWS_IAM"
}

resource "aws_lambda_permission" "sap_url" {
  statement_id           = "AllowGatewayFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.sap.function_name
  principal              = aws_iam_role.gateway.arn
  function_url_auth_type = "AWS_IAM"
}

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

# Native AgentCore Gateway Lambda target (gateway.tf): the Gateway invokes this function
# directly — no Function URL, no public surface. The Gateway's execution role is granted
# lambda:InvokeFunction (iam.tf, identity side); this resource policy grants the AgentCore
# service principal, scoped to this account's gateways, covering the principal AgentCore
# presents at invoke time.
resource "aws_lambda_permission" "sap_gateway" {
  statement_id  = "AllowAgentCoreGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sap.function_name
  principal     = "bedrock-agentcore.amazonaws.com"
  source_arn    = "arn:aws:bedrock-agentcore:${var.region}:${local.account_id}:gateway/*"
}

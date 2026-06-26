# Retention for the three backend Lambdas' log groups. Lambda auto-creates /aws/lambda/<fn>
# on first invocation with no expiry, so these adopt the groups to manage retention as IaC.
# Names derive from var.name_prefix (matching the function names) to keep the module self-
# contained. The groups pre-exist, so a from-scratch apply must `terraform import` each
# first, e.g. module.observability.aws_cloudwatch_log_group.lambda_sap /aws/lambda/<prefix>-sap.
resource "aws_cloudwatch_log_group" "lambda_sap" {
  name              = "/aws/lambda/${var.name_prefix}-sap"
  retention_in_days = var.function_log_retention_days
}

resource "aws_cloudwatch_log_group" "lambda_order_actions" {
  name              = "/aws/lambda/${var.name_prefix}-order-actions"
  retention_in_days = var.function_log_retention_days
}

resource "aws_cloudwatch_log_group" "lambda_snowflake" {
  name              = "/aws/lambda/${var.name_prefix}-snowflake"
  retention_in_days = var.function_log_retention_days
}

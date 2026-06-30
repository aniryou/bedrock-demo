# Snowflake-query API as a Lambda Function URL — a Gateway target backed by Snowflake.
# Zip published to the artifacts bucket (stubs/snowflake.zip) by bedrock-demo-stubs.
# The Lambda signs a key-pair JWT and calls the Snowflake SQL REST API; the RSA private
# key + connection config come from Secrets Manager (var.snowflake_secret_name), not env.

data "aws_secretsmanager_secret" "snowflake" {
  name = var.snowflake_secret_name
}

# --- Execution role: basic logging + read the one Snowflake secret -------------
resource "aws_iam_role" "snowflake_lambda" {
  name = "${var.name_prefix}-snowflake-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "snowflake_lambda_basic" {
  role       = aws_iam_role.snowflake_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "snowflake_lambda_secrets" {
  name = "snowflake-secrets"
  role = aws_iam_role.snowflake_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = data.aws_secretsmanager_secret.snowflake.arn
    }]
  })
}

# --- The Lambda + public (AuthType=NONE) Function URL — the Gateway reaches it with a per-user
# --- Entra OBO bearer (OAUTH TOKEN_EXCHANGE), set by snowflake_obo_egress below; not an X-API-Key.
data "aws_s3_object" "snowflake_zip" {
  bucket = var.artifacts_bucket
  key    = "stubs/snowflake.zip"
}

resource "aws_lambda_function" "snowflake" {
  function_name    = "${var.name_prefix}-snowflake"
  role             = aws_iam_role.snowflake_lambda.arn
  handler          = "snowflake_stub.lambda_handler.handler"
  runtime          = var.lambda_runtime
  architectures    = var.lambda_architectures
  timeout          = var.snowflake_lambda_timeout # higher: warehouse auto-resume on a cold query
  s3_bucket        = var.artifacts_bucket
  s3_key           = "stubs/snowflake.zip"
  source_code_hash = data.aws_s3_object.snowflake_zip.etag

  environment {
    variables = {
      SNOWFLAKE_SECRET_NAME = var.snowflake_secret_name
    }
  }
}

resource "aws_lambda_function_url" "snowflake" {
  function_name      = aws_lambda_function.snowflake.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "snowflake_url" {
  statement_id           = "AllowPublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.snowflake.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

# --- Gateway target: exposes the Lambda's OpenAPI as the MCP tool snowflake___ask ---
data "aws_s3_object" "snowflake_openapi" {
  bucket = var.artifacts_bucket
  key    = "stubs/snowflake.openapi.json"
}

resource "aws_bedrockagentcore_gateway_target" "snowflake" {
  gateway_identifier = aws_bedrockagentcore_gateway.this.gateway_id
  name               = "snowflake"
  description        = "Orders/customers data backed by Snowflake (OpenAPI target)"

  target_configuration {
    mcp {
      open_api_schema {
        inline_payload {
          payload = replace(
            data.aws_s3_object.snowflake_openapi.body,
            "https://REPLACE_WITH_LAMBDA_FUNCTION_URL",
            trimsuffix(aws_lambda_function_url.snowflake.function_url, "/")
          )
        }
      }
    }
  }

  # Outbound Identity. The api_key block is the SigV4-path credential AND the creation
  # placeholder. When Entra OBO is configured, terraform_data.snowflake_obo_egress (below)
  # swaps this for an OAUTH grant_type=TOKEN_EXCHANGE credential out-of-band via the AWS CLI
  # — neither the aws nor awscc provider can express TOKEN_EXCHANGE on a gateway target. We
  # ignore_changes on the credential so the provider does not revert the CLI-applied OBO cred.
  credential_provider_configuration {
    api_key {
      provider_arn              = aws_bedrockagentcore_api_key_credential_provider.snowflake.credential_provider_arn
      credential_location       = "HEADER"
      credential_parameter_name = "X-API-Key"
    }
  }

  lifecycle {
    ignore_changes = [credential_provider_configuration]
    precondition {
      condition     = var.entra_agent_app_id == "" || var.entra_obo_scope != ""
      error_message = "entra_obo_scope must be non-empty when entra_agent_app_id is set: the Gateway OBO TOKEN_EXCHANGE needs a Snowflake resource scope, e.g. api://<snowflake-app>/session:role-any (set ENTRA_OBO_SCOPE in .env)."
    }
  }
}

# When Entra OBO is configured, set the Snowflake gateway target's egress credential to
# OAUTH grant_type=TOKEN_EXCHANGE so the GATEWAY brokers a per-user on-behalf-of token.
# Neither the aws nor awscc provider exposes TOKEN_EXCHANGE on a gateway target (the awscc
# provider has no gateway_target resource at all), so it is applied out-of-band via the AWS
# CLI. Uses the built-in terraform_data (no null provider). targetConfiguration is rendered
# from the SAME S3 OpenAPI Terraform manages, so the CLI replace is byte-consistent with the
# target. Re-runs whenever the target id, OBO provider, scope, or OpenAPI/Function-URL changes
# (which re-asserts the OBO credential if a provider update reverts it to the api_key placeholder).
resource "terraform_data" "snowflake_obo_egress" {
  count = var.entra_agent_app_id != "" ? 1 : 0

  triggers_replace = [
    aws_bedrockagentcore_gateway_target.snowflake.target_id,
    awscc_bedrockagentcore_o_auth_2_credential_provider.entra_obo[0].credential_provider_arn,
    var.entra_obo_scope,
    sha1("${data.aws_s3_object.snowflake_openapi.body}:${aws_lambda_function_url.snowflake.function_url}"),
  ]

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    environment = {
      GW           = aws_bedrockagentcore_gateway.this.gateway_id
      TID          = aws_bedrockagentcore_gateway_target.snowflake.target_id
      REGION       = var.region
      PROVIDER_ARN = awscc_bedrockagentcore_o_auth_2_credential_provider.entra_obo[0].credential_provider_arn
      SCOPE        = var.entra_obo_scope
      TARGET_CONFIG = jsonencode({
        mcp = { openApiSchema = { inlinePayload = replace(
          data.aws_s3_object.snowflake_openapi.body,
          "https://REPLACE_WITH_LAMBDA_FUNCTION_URL",
          trimsuffix(aws_lambda_function_url.snowflake.function_url, "/")
        ) } }
      })
    }
    command = <<-EOT
      set -euo pipefail
      CRED="$(printf '[{"credentialProviderType":"OAUTH","credentialProvider":{"oauthCredentialProvider":{"providerArn":"%s","scopes":["%s"],"grantType":"TOKEN_EXCHANGE"}}}]' "$PROVIDER_ARN" "$SCOPE")"
      aws bedrock-agentcore-control update-gateway-target \
        --gateway-identifier "$GW" --target-id "$TID" --region "$REGION" \
        --name snowflake \
        --target-configuration "$TARGET_CONFIG" \
        --credential-provider-configurations "$CRED"
      echo "snowflake gateway target credential -> OAUTH/TOKEN_EXCHANGE (Gateway-brokered OBO)"
    EOT
  }
}

output "snowflake_function_url" {
  value = aws_lambda_function_url.snowflake.function_url
}

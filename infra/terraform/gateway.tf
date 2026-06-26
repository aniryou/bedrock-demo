# AgentCore Gateway: exposes the stub services as MCP tools via OpenAPI targets,
# with the outbound Identity credential and the Cedar policy engine attached.
# The OpenAPI specs are published to the artifacts bucket by bedrock-demo-stubs and
# read here via data sources (no sibling-folder files).

data "aws_s3_object" "sap_openapi" {
  bucket = var.artifacts_bucket
  key    = "stubs/sap.openapi.json"
}

data "aws_s3_object" "orders_openapi" {
  bucket = var.artifacts_bucket
  key    = "stubs/order_actions.openapi.json"
}

resource "aws_bedrockagentcore_gateway" "this" {
  name          = "${var.name_prefix}-gateway"
  role_arn      = aws_iam_role.gateway.arn
  protocol_type = "MCP"

  # Inbound auth = Microsoft Entra user JWT (CUSTOM_JWT): the agent forwards the user
  # identity and Cedar authorizes on the OAuthUser dimension (policy.tf). The agent/source
  # pin lives in allowed_audience.
  authorizer_type = "CUSTOM_JWT"

  authorizer_configuration {
    custom_jwt_authorizer {
      # v1 discovery (inbound user token is v1: iss=https://sts.windows.net/<tenant>/).
      discovery_url    = "https://login.microsoftonline.com/${var.entra_tenant_id}/.well-known/openid-configuration"
      allowed_audience = ["api://${var.entra_agent_app_id}"]
    }
  }

  depends_on = [time_sleep.gateway_iam] # RACE 1: wait for gateway IAM role propagation

  # Policy (authorization control) — Cedar policies gate the tool calls.
  policy_engine_configuration {
    arn  = aws_bedrockagentcore_policy_engine.this.policy_engine_arn
    mode = "ENFORCE"
  }
}

resource "aws_bedrockagentcore_gateway_target" "sap" {
  gateway_identifier = aws_bedrockagentcore_gateway.this.gateway_id
  name               = "sap"
  description        = "Dummy SAP credit API (OpenAPI target)"

  target_configuration {
    mcp {
      open_api_schema {
        inline_payload {
          payload = replace(
            data.aws_s3_object.sap_openapi.body,
            "https://REPLACE_WITH_LAMBDA_FUNCTION_URL",
            trimsuffix(aws_lambda_function_url.sap.function_url, "/")
          )
        }
      }
    }
  }

  # Outbound Identity: the Gateway SigV4-signs the request to the Lambda Function URL
  # (AuthType=AWS_IAM) with its execution role. `service = "lambda"` is the SigV4 service
  # AWS documents for OpenAPI/MCP targets behind a Lambda Function URL.
  credential_provider_configuration {
    gateway_iam_role {
      service = "lambda"
    }
  }
}

# Second target: order actions (flagging). Cedar policy `permit_flag` authorizes it.
resource "aws_bedrockagentcore_gateway_target" "orders" {
  gateway_identifier = aws_bedrockagentcore_gateway.this.gateway_id
  name               = "orders"
  description        = "Order actions (flagging) OpenAPI target"

  target_configuration {
    mcp {
      open_api_schema {
        inline_payload {
          payload = replace(
            data.aws_s3_object.orders_openapi.body,
            "https://REPLACE_WITH_LAMBDA_FUNCTION_URL",
            trimsuffix(aws_lambda_function_url.order_actions.function_url, "/")
          )
        }
      }
    }
  }

  credential_provider_configuration {
    gateway_iam_role {
      service = "lambda"
    }
  }
}

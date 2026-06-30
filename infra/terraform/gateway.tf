# AgentCore Gateway: exposes the stub services as MCP tools, with the outbound Identity
# credential and the Cedar policy engine attached. The sap/orders targets are native Lambda
# (ARN) targets — the Gateway invokes the function directly via lambda:InvokeFunction, carrying
# an inline tool schema (no Function URL, no SigV4). The snowflake target is OpenAPI (its spec +
# OBO egress live in snowflake_lambda.tf).

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
  description        = "Dummy SAP credit API (Lambda target)"

  # Native Lambda target: the Gateway invokes the function directly (lambda:InvokeFunction),
  # passing the tool args as the event and the tool name in client_context. The tool name MUST
  # stay getCreditStatus so the MCP tool is `sap___getCreditStatus` (policy.tf Cedar action +
  # the agent both pin it).
  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.sap.arn
        tool_schema {
          inline_payload {
            name        = "getCreditStatus"
            description = "Get the SAP credit status for a customer."
            input_schema {
              type = "object"
              property {
                name        = "customer_id"
                type        = "string"
                description = "Customer id, e.g. C-001."
                required    = true
              }
            }
          }
        }
      }
    }
  }

  # The Gateway invokes the Lambda as its own execution role (iam.tf grants
  # lambda:InvokeFunction; the function's resource policy allows the AgentCore service principal).
  credential_provider_configuration {
    gateway_iam_role {}
  }
}

# Second target: order actions (flagging). Cedar policy `permit_flag` authorizes it.
resource "aws_bedrockagentcore_gateway_target" "orders" {
  gateway_identifier = aws_bedrockagentcore_gateway.this.gateway_id
  name               = "orders"
  description        = "Order actions (flagging) Lambda target"

  # Native Lambda target. Tool name MUST stay flagOrder so the MCP tool is `orders___flagOrder`
  # (policy.tf Cedar action + the agent both pin it).
  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.order_actions.arn
        tool_schema {
          inline_payload {
            name        = "flagOrder"
            description = "Flag an OPEN order for human review."
            input_schema {
              type = "object"
              property {
                name        = "order_id"
                type        = "string"
                description = "Order id to flag, e.g. O-1003."
                required    = true
              }
              property {
                name        = "reason"
                type        = "string"
                description = "Why the order is being flagged for review."
                required    = true
              }
            }
          }
        }
      }
    }
  }

  credential_provider_configuration {
    gateway_iam_role {}
  }
}

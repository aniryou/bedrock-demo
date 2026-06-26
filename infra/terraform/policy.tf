# AgentCore Policy: Cedar engine + policies gating the gateway tool calls (SAP credit
# read + order flagging). This is the sole authorization layer. The engine is attached
# to the Gateway in gateway.tf.

locals {
  # The Gateway is CUSTOM_JWT, so Cedar authorizes the Entra user on the OAuthUser
  # dimension; the agent/source pin lives in the gateway's allowed_audience (gateway.tf).
  #
  # cedar_guard is the `when {}` condition shared by the 3 policies. It must NOT be
  # trivially-true: the AgentCore policy engine runs semantic validation (default
  # FAIL_ON_ANY_FINDINGS) and rejects `when { true }` as "Overly Permissive" — it provably
  # allows every request for the principal/action/resource tuple -> UPDATE_FAILED. AgentCore
  # exposes each inbound JWT claim as a Cedar TAG (principal.hasTag/getTag), NOT
  # principal.claims[...]. Requiring the delegated-scope claim to exist both passes the
  # guardrail (not provably-true) and admits any authenticated Entra user (their OBO/user
  # token always carries `scp`). To tighten, match a specific scope value, e.g.
  # `principal.getTag("scp") like "*access_as_user*"`.
  cedar_principal = "AgentCore::OAuthUser"
  cedar_guard     = "principal.hasTag(\"scp\")"
}

resource "aws_bedrockagentcore_policy_engine" "this" {
  name        = "${local.name_prefix_us}_policies" # AgentCore requires underscores
  description = "Order-triage authorization (Cedar)"
}

resource "aws_bedrockagentcore_policy" "sap_read" {
  name             = "permit_sap_read"
  description      = "Permit reading SAP credit status through the gateway"
  policy_engine_id = aws_bedrockagentcore_policy_engine.this.policy_engine_id
  depends_on       = [time_sleep.target_actions] # RACE 2: wait for target actions to register

  definition {
    cedar {
      statement = <<-EOT
        permit (
          principal is ${local.cedar_principal},
          action == AgentCore::Action::"sap___getCreditStatus",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.this.gateway_arn}"
        ) when {
          ${local.cedar_guard}
        };
      EOT
    }
  }
}

# Authorizes flagging through the gateway.
resource "aws_bedrockagentcore_policy" "flag" {
  name             = "permit_flag"
  description      = "Permit flagging an order for review through the gateway"
  policy_engine_id = aws_bedrockagentcore_policy_engine.this.policy_engine_id
  depends_on       = [time_sleep.target_actions] # RACE 2: wait for target actions to register

  definition {
    cedar {
      statement = <<-EOT
        permit (
          principal is ${local.cedar_principal},
          action == AgentCore::Action::"orders___flagOrder",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.this.gateway_arn}"
        ) when {
          ${local.cedar_guard}
        };
      EOT
    }
  }
}

# Authorizes the Snowflake analytics tool through the gateway. The four fixed read ops
# (getOrders/getOrder/getCustomer/listCustomers) collapsed into one `ask`: the Lambda now
# proxies Cortex Analyst over the ORDERS_SV semantic view, so Cedar's role here shifts from
# per-operation gating to "may this principal use the Snowflake analytics tool at all".
# Fine-grained row/column governance moves into the semantic view + Snowflake RLS/RBAC,
# enforced under the user's OBO token (see docs/adr/0008). The guard still admits any
# authenticated Entra user (their OBO token carries `scp`).
resource "aws_bedrockagentcore_policy" "snowflake_read" {
  name             = "permit_snowflake_ask"
  description      = "Permit the Snowflake analytics (ask) tool through the gateway"
  policy_engine_id = aws_bedrockagentcore_policy_engine.this.policy_engine_id
  depends_on       = [time_sleep.target_actions] # RACE 2: wait for target actions to register

  definition {
    cedar {
      statement = <<-EOT
        permit (
          principal is ${local.cedar_principal},
          action == AgentCore::Action::"snowflake___ask",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.this.gateway_arn}"
        ) when {
          ${local.cedar_guard}
        };
      EOT
    }
  }
}

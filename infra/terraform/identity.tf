# AgentCore Identity: outbound credential providers. The SAP/orders stubs have no API-key
# provider — their Lambda Function URLs are AuthType=AWS_IAM, invoked by the Gateway's
# IAM role via SigV4 (see gateway.tf, credential_provider_configuration.gateway_iam_role).

# Outbound API-key provider for the Snowflake data Lambda. Its Function URL stays
# AuthType=NONE + X-API-Key because its single Gateway egress slot carries the Entra OBO
# TOKEN_EXCHANGE credential, not SigV4 (see snowflake_lambda.tf).
resource "aws_bedrockagentcore_api_key_credential_provider" "snowflake" {
  name    = "snowflake-api-key"
  api_key = var.snowflake_api_key
}

# --- Entra OBO credential provider ---------------------------------------------
# OBO is a RUNTIME flow (GetWorkloadAccessTokenForJWT(inbound user JWT) →
# GetResourceOauth2Token(oauth2_flow=ON_BEHALF_OF_TOKEN_EXCHANGE, scopes=[session:role-any])),
# not a provider setting. Count-guarded on the Entra creds (TF_VAR_entra_*) so it vanishes
# when unset — zero impact on the SigV4 stack.
#
# MicrosoftOauth2 vendor WITH `tenant_id`:
#   * `tenant_id` makes discovery tenant-specific (login.microsoftonline.com/<tenant>/v2.0/...),
#     so it works for personal/guest accounts too. Omitting it defaults to `/common`, which
#     fails personal accounts with AADSTS500202.
#   * The vendor adds `requested_token_use=on_behalf_of` ITSELF — the agent passes NO custom
#     param (a CustomOauth2 + JWT_AUTHORIZATION_GRANT provider omits it → AADSTS900144).
# `tenant_id` is only on the AWSCC (Cloud Control) resource, not hashicorp/aws v6 — hence awscc.
# The Entra OBO client secret is stored in AWS Secrets Manager (value injected out-of-band).
# We reference it by ARN so the secret VALUE never lands in this stack's Terraform state.
# This data source reads only metadata (the ARN), not the value.
data "aws_secretsmanager_secret" "entra_obo" {
  count = var.entra_agent_app_id != "" ? 1 : 0
  name  = "order-triage/entra-agent-client-secret"
}

resource "awscc_bedrockagentcore_o_auth_2_credential_provider" "entra_obo" {
  count                      = var.entra_agent_app_id != "" ? 1 : 0
  name                       = "entra-obo"
  credential_provider_vendor = "MicrosoftOauth2"

  oauth_2_provider_config_input = {
    microsoft_oauth_2_provider_config = {
      client_id = var.entra_agent_app_id
      tenant_id = var.entra_tenant_id
      # clientSecretSource=EXTERNAL: AgentCore reads the secret from the referenced Secrets
      # Manager secret (JSON key "client_secret") at runtime — it is NOT passed inline, so it
      # does not persist in Terraform state.
      client_secret_source = "EXTERNAL"
      client_secret_config = {
        secret_id = data.aws_secretsmanager_secret.entra_obo[0].arn
        json_key  = "client_secret"
      }
    }
  }
}

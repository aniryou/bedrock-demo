# Service roles. Broad demo policies — tighten to least privilege for production.

locals {
  agentcore_assume = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# --- AgentCore Runtime execution role -----------------------------------------
resource "aws_iam_role" "runtime" {
  name               = "${var.name_prefix}-runtime"
  assume_role_policy = local.agentcore_assume
}

resource "aws_iam_role_policy" "runtime" {
  name = "runtime"
  role = aws_iam_role.runtime.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Effect = "Allow"
          Action = [
            "bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream",
            "bedrock-agentcore:*", "bedrock:Retrieve", "bedrock:RetrieveAndGenerate",
            "logs:*", "xray:PutTraceSegments", "xray:PutSpans",
            "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:GetAuthorizationToken"
          ]
          Resource = "*"
        },
        {
          # OBO: GetResourceOauth2Token reads the credential provider's client_secret
          # (an AgentCore-managed Secrets Manager secret, prefix `bedrock-agentcore-identity!`)
          # using the CALLER's role — so the runtime needs GetSecretValue on it. Without this,
          # the OBO exchange fails AccessDenied and the user-authority path errors.
          Effect   = "Allow"
          Action   = ["secretsmanager:GetSecretValue"]
          Resource = "arn:aws:secretsmanager:*:*:secret:bedrock-agentcore-identity!*"
        }
      ],
      # Converse/ConverseStream with guardrailConfig invokes the guardrail under this action;
      # without it every guarded inference returns AccessDenied. Scoped to the base guardrail
      # ARN (no version suffix — the version is a request parameter, not part of the resource
      # ARN, so the base ARN covers all published versions). Omitted when the guardrail is off.
      var.enable_guardrail ? [
        {
          Effect   = "Allow"
          Action   = ["bedrock:ApplyGuardrail"]
          Resource = aws_bedrock_guardrail.order_triage[0].guardrail_arn
        }
      ] : []
    )
  })
}

# --- Gateway role -------------------------------------------------------------
# The Gateway's execution role (inbound auth is CUSTOM_JWT, gateway.tf). Three request-time
# jobs: SigV4-sign the AWS_IAM SAP/orders Function URLs; broker the snowflake target's OBO
# token exchange (reading the credential provider's secret as the caller); and evaluate the
# Cedar policy engine attached in ENFORCE mode (policy.tf). Least-privileged to the
# actions/resources those jobs use — see ADR-0006.
resource "aws_iam_role" "gateway" {
  name               = "${var.name_prefix}-gateway"
  assume_role_policy = local.agentcore_assume
}

resource "aws_iam_role_policy" "gateway" {
  name = "gateway"
  role = aws_iam_role.gateway.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Direct invoke of the SAP + order-actions Lambda targets (native AgentCore Lambda
        # targets, gateway.tf): the Gateway calls lambda:InvokeFunction as this role. Each
        # function's resource policy also allows the AgentCore service principal (sap_lambda.tf /
        # order_actions_lambda.tf), so both invoke paths are covered. The snowflake target is an
        # OBO Function URL (AuthType=NONE) — not IAM-invoked — so it is intentionally absent.
        Sid    = "InvokeLambdaTargets"
        Effect = "Allow"
        Action = ["lambda:InvokeFunction"]
        Resource = [
          aws_lambda_function.sap.arn,
          aws_lambda_function.order_actions.arn,
        ]
      },
      {
        # OBO brokering for the snowflake target's grant_type=TOKEN_EXCHANGE egress
        # (snowflake_lambda.tf): the Gateway is the caller of the two-step on-behalf-of flow
        # GetWorkloadAccessTokenForJWT -> GetResourceOauth2Token (the entra-obo provider). When
        # entra_agent_app_id == "" the target keeps its X-API-Key egress instead and the Gateway
        # reads the key via GetResourceApiKey, so both paths are granted.
        # Resource = "*": these token-mint actions authorize against several required resource
        # types at once (credential-provider, the default token-vault, and the workload identity
        # the Gateway creates implicitly) — not all surfaced as Terraform attributes — so pinning
        # them risks a silent AccessDenied that breaks user impersonation. The least-privilege win
        # here is the ACTION set: three read/token-fetch actions, not bedrock-agentcore:* (which
        # also allowed gateway / target / policy mutation). See ADR-0006.
        Sid    = "OboTokenBrokering"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
          "bedrock-agentcore:GetResourceOauth2Token",
          "bedrock-agentcore:GetResourceApiKey",
        ]
        Resource = "*"
      },
      {
        # Cedar policy-engine evaluation. The Gateway runs a policy engine in ENFORCE mode
        # (policy.tf, attached in gateway.tf), so for every MCP ListTools + tool call it
        # evaluates Cedar via Policy in AgentCore AS THIS ROLE: GetPolicyEngine reads the engine
        # config, AuthorizeAction evaluates a call, and PartiallyAuthorizeActions lists the
        # caller's authorized tools (the ListTools path). Without these the Gateway returns
        # "Insufficient Permissions for Policy Evaluation" on ListTools and default-denies every
        # tool call. AuthorizeAction / PartiallyAuthorizeActions require BOTH resource types.
        # Scoped to the gateway + policy-engine resource types in this account/region, NOT the
        # exact ARNs: the role policy must exist BEFORE the gateway (the gateway waits on it via
        # time_sleep.gateway_iam, cold_start.tf), so referencing those resources here would form
        # a dependency cycle. See ADR-0006.
        Sid    = "EvaluateCedarPolicyEngine"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetPolicyEngine",
          "bedrock-agentcore:AuthorizeAction",
          "bedrock-agentcore:PartiallyAuthorizeActions",
        ]
        Resource = [
          "arn:aws:bedrock-agentcore:${var.region}:${local.account_id}:policy-engine/*",
          "arn:aws:bedrock-agentcore:${var.region}:${local.account_id}:gateway/*",
        ]
      },
      {
        # Provider-secret reads performed with the CALLER's (this) role while resolving the
        # egress credential, two distinct cases:
        #   * snowflake-api-key provider — its api_key is passed inline at create time, so
        #     AgentCore stores it in an AgentCore-managed secret (prefix
        #     `bedrock-agentcore-identity!`) that GetResourceApiKey reads on the X-API-Key path.
        #   * entra-obo provider — clientSecretSource=EXTERNAL, so GetResourceOauth2Token reads
        #     the EXTERNAL secret (order-triage/entra-agent-client-secret) DIRECTLY at
        #     TOKEN_EXCHANGE time (verified: the caller, not the create-time deploy role, reads it).
        # Scoped to exactly those two secrets — NOT order-triage/* (which holds the Snowflake RSA
        # key the gateway must never read) and NOT all secrets. The entra secret ARN is added only
        # when OBO is configured (var.entra_agent_app_id). See ADR-0006.
        Sid    = "ReadCredentialProviderSecrets"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = concat(
          ["arn:aws:secretsmanager:*:*:secret:bedrock-agentcore-identity!*"],
          var.entra_agent_app_id != "" ? [data.aws_secretsmanager_secret.entra_obo[0].arn] : []
        )
      },
    ]
  })
}

# --- Knowledge Base role ------------------------------------------------------
resource "aws_iam_role" "kb" {
  name = "${var.name_prefix}-kb"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "kb" {
  name = "kb"
  role = aws_iam_role.kb.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket", "s3vectors:*", "bedrock:InvokeModel"]
      Resource = "*"
    }]
  })
}

# --- Memory execution role (long-term strategy extraction uses a model) -------
resource "aws_iam_role" "memory" {
  name               = "${var.name_prefix}-memory"
  assume_role_policy = local.agentcore_assume
}

resource "aws_iam_role_policy" "memory" {
  name = "memory"
  role = aws_iam_role.memory.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = "*" }]
  })
}

# --- SAP Lambda execution role ------------------------------------------------
resource "aws_iam_role" "sap_lambda" {
  name = "${var.name_prefix}-sap-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sap_lambda_basic" {
  role       = aws_iam_role.sap_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

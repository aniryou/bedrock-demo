# GitHub Actions -> AWS auth substrate for the CD pipeline (see docs/playbooks/cd-setup.md).
#
# Two OIDC-assumable roles, no long-lived keys:
#   * publish role  - assumed by the agent-build.yml + stubs-release.yml workflows to push
#                     the image to ECR and artifacts to S3. Tightly scoped.
#   * deploy role   - assumed by deploy.yml (gated) + the infra-ci.yml PR plan
#                     job to run terraform. Broad by default (terraform touches many
#                     services); SCOPE THIS DOWN past a demo (see var.deploy_policy_arn).
#
# Output the role ARNs into the repo secrets AWS_PUBLISH_ROLE_ARN / AWS_DEPLOY_ROLE_ARN.

variable "github_org" {
  type        = string
  default     = "aniryou"
  description = "GitHub org/user that owns the CD repo."
}

variable "create_github_oidc_provider" {
  type        = bool
  default     = true
  description = "Create the account-level GitHub OIDC provider. Set false if one already exists and pass existing_oidc_provider_arn."
}

variable "existing_oidc_provider_arn" {
  type        = string
  default     = ""
  description = "Used only when create_github_oidc_provider=false."
}

variable "deploy_policy_arn" {
  type        = string
  default     = ""
  description = "Optional managed-policy ARN override for the deploy role. Empty (default) attaches the generated least-privilege policy (aws_iam_policy.deploy_perms). Set only to pin a specific managed policy."
}

locals {
  oidc_provider_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : var.existing_oidc_provider_arn

  # Mono-repo: every workflow runs from aniryou/bedrock-demo. The publish role trusts
  # repo:<org>/bedrock-demo:* (used by agent-build.yml / stubs-release.yml); the deploy
  # role trusts :environment:production (deploy.yml) and :pull_request (infra-ci plan).
  publish_repos = ["bedrock-demo"]
  deploy_repos  = ["bedrock-demo"]
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # AWS validates GitHub's OIDC via its own trust store; the thumbprint is still a
  # required field. These are GitHub's published intermediate-CA thumbprints.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

# ---- Publish role (agent + stubs CI) ------------------------------------------
data "aws_iam_policy_document" "publish_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [for r in local.publish_repos : "repo:${var.github_org}/${r}:*"]
    }
  }
}

resource "aws_iam_role" "publish" {
  name               = "${var.name_prefix}-ci-publish"
  assume_role_policy = data.aws_iam_policy_document.publish_trust.json
}

data "aws_iam_policy_document" "publish_perms" {
  # ECR: auth token is account-wide; push/pull scoped to the agent repo.
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
    ]
    resources = [aws_ecr_repository.agent.arn]
  }
  # S3: write kb/ and stubs/ into the artifacts bucket.
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.artifacts.arn]
  }
  statement {
    actions   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.artifacts.arn}/kb/*", "${aws_s3_bucket.artifacts.arn}/stubs/*"]
  }
}

resource "aws_iam_role_policy" "publish" {
  name   = "publish"
  role   = aws_iam_role.publish.id
  policy = data.aws_iam_policy_document.publish_perms.json
}

# ---- Deploy role (infra terraform) --------------------------------------------
data "aws_iam_policy_document" "deploy_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      # Environment-pinned: only the `production` deployment environment (with required
      # reviewers, see deploy.yml) can assume the privileged deploy role — NOT any branch/PR.
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [for r in local.deploy_repos : "repo:${var.github_org}/${r}:environment:production"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "${var.name_prefix}-ci-deploy"
  assume_role_policy = data.aws_iam_policy_document.deploy_trust.json
}

# Least-privilege deploy policy: only the services ../terraform manages. This is a
# STARTING point — refine with IAM Access Analyzer from a real deploy's CloudTrail
# before production (pass var.deploy_policy_arn to override entirely).
data "aws_iam_policy_document" "deploy_perms" {
  statement {
    sid       = "AgentCore"
    actions   = ["bedrock-agentcore:*"] # most AgentCore actions lack resource-level scoping today
    resources = ["*"]
  }
  statement {
    sid = "BedrockKnowledgeBase"
    actions = [
      "bedrock:CreateKnowledgeBase", "bedrock:UpdateKnowledgeBase", "bedrock:DeleteKnowledgeBase",
      "bedrock:GetKnowledgeBase", "bedrock:ListKnowledgeBases",
      "bedrock:CreateDataSource", "bedrock:UpdateDataSource", "bedrock:DeleteDataSource", "bedrock:GetDataSource",
      "bedrock:TagResource", "bedrock:UntagResource", "bedrock:ListTagsForResource",
    ]
    resources = ["*"]
  }
  statement {
    sid = "BedrockGuardrail"
    actions = [
      "bedrock:CreateGuardrail", "bedrock:UpdateGuardrail", "bedrock:DeleteGuardrail",
      "bedrock:GetGuardrail", "bedrock:ListGuardrails",
      "bedrock:CreateGuardrailVersion", "bedrock:DeleteGuardrailVersion",
    ]
    # Guardrail ids are server-generated, and ListGuardrails has no resource scope, so *.
    resources = ["*"]
  }
  statement {
    # invocation_logging.tf: account+region Bedrock model-invocation logging is a
    # SINGLETON with no resource-level scoping. Refresh reads Get*, apply writes Put*.
    sid = "BedrockModelInvocationLogging"
    actions = [
      "bedrock:GetModelInvocationLoggingConfiguration",
      "bedrock:PutModelInvocationLoggingConfiguration",
      "bedrock:DeleteModelInvocationLoggingConfiguration",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "S3Vectors"
    actions   = ["s3vectors:*"]
    resources = ["*"]
  }
  statement {
    sid = "Lambda"
    actions = [
      "lambda:CreateFunction", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration",
      "lambda:DeleteFunction", "lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionCodeSigningConfig", "lambda:ListVersionsByFunction",
      "lambda:TagResource", "lambda:UntagResource", "lambda:AddPermission", "lambda:RemovePermission", "lambda:GetPolicy",
      "lambda:CreateFunctionUrlConfig", "lambda:UpdateFunctionUrlConfig", "lambda:DeleteFunctionUrlConfig", "lambda:GetFunctionUrlConfig",
    ]
    resources = ["arn:aws:lambda:*:${data.aws_caller_identity.current.account_id}:function:${var.name_prefix}-*"]
  }
  statement {
    sid = "IamManageDemoRoles"
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
      # The AWS provider always calls ListInstanceProfilesForRole before DeleteRole (to detach any
      # instance profiles first); without it every role delete 403s even though DeleteRole is granted.
      "iam:ListInstanceProfilesForRole",
      "iam:CreatePolicy", "iam:DeletePolicy", "iam:GetPolicy", "iam:GetPolicyVersion", "iam:CreatePolicyVersion", "iam:DeletePolicyVersion", "iam:ListPolicyVersions",
      "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy",
    ]
    # The GitHub OIDC provider (aws_iam_openid_connect_provider.github) is bootstrap-only
    # (applied with operator creds); the deploy role runs only ../terraform (the main stack),
    # which never manages it — so no iam:*OpenIDConnectProvider action / oidc-provider here.
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.name_prefix}-*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/${var.name_prefix}-*",
    ]
  }
  statement {
    sid       = "PassRoleScopedToDemoServices"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.name_prefix}-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["bedrock-agentcore.amazonaws.com", "bedrock.amazonaws.com", "lambda.amazonaws.com"]
    }
  }
  statement {
    sid = "SecretsScoped"
    actions = [
      "secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret", "secretsmanager:CreateSecret",
      "secretsmanager:PutSecretValue", "secretsmanager:TagResource", "secretsmanager:DeleteSecret",
      "secretsmanager:GetResourcePolicy", # refresh reads the secret's resource policy
    ]
    resources = [
      "arn:aws:secretsmanager:*:${data.aws_caller_identity.current.account_id}:secret:order-triage/*",
      "arn:aws:secretsmanager:*:${data.aws_caller_identity.current.account_id}:secret:bedrock-agentcore-identity!*",
    ]
  }
  statement {
    # Actor resolution (ADR-0007) reads the Graph app-creds secret's metadata via a data source to
    # wire its ARN into the resolver Lambda. The secret is seeded out-of-band (`make seed-graph-secret`)
    # and never written from here, so this is read-only; its hyphenated name (`order-triage-graph-
    # resolver-*`) sits outside the `order-triage/` slash prefix above. GetResourcePolicy backs the
    # data source's `policy` attribute. The Lambda reads the value at runtime with its own role.
    sid       = "GraphResolverSecretRead"
    actions   = ["secretsmanager:DescribeSecret", "secretsmanager:GetResourcePolicy"]
    resources = ["arn:aws:secretsmanager:*:${data.aws_caller_identity.current.account_id}:secret:${var.name_prefix}-graph-resolver-*"]
  }
  statement {
    sid = "EcrLogsXrayReadAndManage"
    actions = [
      "ecr:DescribeRepositories", "ecr:DescribeImages", "ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
      "logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:DescribeLogGroups", "logs:PutRetentionPolicy",
      "logs:TagResource", "logs:UntagResource", "logs:ListTagsForResource",
      # observability.tf manages aws_cloudwatch_log_resource_policy.xray_spans (Transaction Search)
      "logs:DescribeResourcePolicies", "logs:PutResourcePolicy", "logs:DeleteResourcePolicy",
      # observability.tf memory log + trace delivery (APPLICATION_LOGS->CWL log group, TRACES->XRAY):
      # the vended-logs delivery source/destination/delivery API.
      "logs:PutDeliverySource", "logs:GetDeliverySource", "logs:DeleteDeliverySource", "logs:DescribeDeliverySources",
      "logs:PutDeliveryDestination", "logs:GetDeliveryDestination", "logs:DeleteDeliveryDestination", "logs:DescribeDeliveryDestinations",
      "logs:CreateDelivery", "logs:GetDelivery", "logs:DeleteDelivery", "logs:UpdateDeliveryConfiguration", "logs:DescribeDeliveries",
      # invocation_logging.tf: the per-log-group PII data-protection (mask) policy on the
      # Bedrock model-invocation-logging group (Audit + Deidentify). Refresh reads it, apply writes it.
      "logs:GetDataProtectionPolicy", "logs:PutDataProtectionPolicy", "logs:DeleteDataProtectionPolicy",
      "sts:GetCallerIdentity", "xray:*",
    ]
    resources = ["*"]
  }
  statement {
    sid       = "S3DemoBuckets"
    actions   = ["s3:GetObject", "s3:GetObjectTagging", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:GetBucketLocation"]
    resources = ["arn:aws:s3:::${var.name_prefix}-*", "arn:aws:s3:::${var.name_prefix}-*/*"]
  }
  # The awscc provider (Entra OBO OAuth2 credential provider + workload identity) drives the
  # AWS Cloud Control API, whose IAM actions live under the cloudformation: prefix; the
  # underlying calls are bedrock-agentcore:* (granted above). Cloud Control doesn't support
  # resource-ARN scoping for these, so they sit on "*".
  statement {
    sid = "CloudControlForAwscc"
    actions = [
      "cloudformation:GetResource", "cloudformation:GetResourceRequestStatus",
      "cloudformation:CreateResource", "cloudformation:UpdateResource",
      "cloudformation:DeleteResource", "cloudformation:ListResources",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "deploy_perms" {
  name   = "${var.name_prefix}-ci-deploy-perms"
  policy = data.aws_iam_policy_document.deploy_perms.json
}

resource "aws_iam_role_policy_attachment" "deploy" {
  role       = aws_iam_role.deploy.name
  policy_arn = var.deploy_policy_arn != "" ? var.deploy_policy_arn : aws_iam_policy.deploy_perms.arn
}

# --- Observability grants — SEPARATE managed policy ---------------------------
# The primary deploy_perms policy is at the IAM managed-policy size cap (6144 chars), so
# the CloudWatch / SNS / Application-Signals / KB-logging statements live in their own
# policy attached to the same role (effective perms = union of both attachments).
data "aws_iam_policy_document" "deploy_perms_obs" {
  statement {
    # CloudWatch dashboards, alarms (static + composite + anomaly), Contributor Insights
    # rules, Logs Insights saved queries, and the metric reads the SLO create validates
    # against (GetMetricData). Limited/no resource-level scoping -> "*".
    sid = "CloudWatchMonitoring"
    actions = [
      "cloudwatch:PutDashboard", "cloudwatch:DeleteDashboards", "cloudwatch:GetDashboard", "cloudwatch:ListDashboards",
      "cloudwatch:PutMetricAlarm", "cloudwatch:DeleteAlarms", "cloudwatch:DescribeAlarms", "cloudwatch:DescribeAlarmsForMetric",
      "cloudwatch:PutCompositeAlarm", "cloudwatch:EnableAlarmActions", "cloudwatch:DisableAlarmActions",
      "cloudwatch:PutAnomalyDetector", "cloudwatch:DeleteAnomalyDetector", "cloudwatch:DescribeAnomalyDetectors",
      "cloudwatch:PutInsightRule", "cloudwatch:DeleteInsightRules", "cloudwatch:DescribeInsightRules",
      "cloudwatch:EnableInsightRules", "cloudwatch:DisableInsightRules",
      "cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics", "cloudwatch:ListMetrics",
      "cloudwatch:TagResource", "cloudwatch:UntagResource", "cloudwatch:ListTagsForResource",
      "logs:PutQueryDefinition", "logs:DeleteQueryDefinition", "logs:DescribeQueryDefinitions",
    ]
    resources = ["*"]
  }
  statement {
    sid = "SnsAlerts"
    actions = [
      "sns:CreateTopic", "sns:DeleteTopic", "sns:GetTopicAttributes", "sns:SetTopicAttributes",
      "sns:Subscribe", "sns:Unsubscribe", "sns:GetSubscriptionAttributes", "sns:ListSubscriptionsByTopic",
      "sns:TagResource", "sns:UntagResource", "sns:ListTagsForResource",
    ]
    resources = ["arn:aws:sns:*:${data.aws_caller_identity.current.account_id}:${var.name_prefix}-*"]
  }
  statement {
    # awscc_applicationsignals_service_level_objective via Cloud Control. The CC create+
    # STABILIZE (read-back) handler calls a moving set of App-Signals reads — Create then
    # GetServiceLevelObjective, ListServiceLevelObjectiveExclusionWindows, ListTagsForResource,
    # etc. — which surface one failed deploy at a time. App Signals is a small, bounded
    # service and this deploy role legitimately owns the SLO lifecycle, so grant the whole
    # action set rather than chase the read-back list. (Cloud Control verbs themselves are
    # under cloudformation:* — CloudControlForAwscc, in deploy_perms.)
    sid       = "ApplicationSignalsSLO"
    actions   = ["application-signals:*"]
    resources = ["*"]
  }
  statement {
    # Bedrock-side authorization to vend KB ingestion logs to the CloudWatch delivery
    # (the logs:Put*Delivery* trio is already in deploy_perms). IAM-only action.
    sid       = "KbVendedLogDelivery"
    actions   = ["bedrock:AllowVendedLogDeliveryForResource"]
    resources = ["*"]
  }
  statement {
    # The FAILED-ingestion CloudWatch Logs metric filter (no native metric exists).
    # Describe is required for refresh/plan on subsequent runs.
    sid       = "LogsMetricFilter"
    actions   = ["logs:PutMetricFilter", "logs:DeleteMetricFilter", "logs:DescribeMetricFilters"]
    resources = ["*"]
  }
  statement {
    # create-online-evaluation-config (run by THIS deploy role via the evaluations.tf
    # terraform_data local-exec) validates that the CALLER can access the field-index policy
    # of the trace log groups in its dataSourceConfig (aws/spans + the runtime -DEFAULT group);
    # without it the create fails "Access denied when accessing index policy for aws/spans".
    # (The exec role has its own copy of these in evaluations.tf, for query time.)
    sid       = "EvalDataSourceIndexAccess"
    actions   = ["logs:DescribeIndexPolicies", "logs:PutIndexPolicy", "logs:DescribeFieldIndexes", "logs:GetLogGroupFields"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "deploy_perms_obs" {
  name   = "${var.name_prefix}-ci-deploy-obs-perms"
  policy = data.aws_iam_policy_document.deploy_perms_obs.json
}

resource "aws_iam_role_policy_attachment" "deploy_obs" {
  count      = var.deploy_policy_arn != "" ? 0 : 1
  role       = aws_iam_role.deploy.name
  policy_arn = aws_iam_policy.deploy_perms_obs.arn
}

# ---- Plan role (PR plan job) --------------------------------------------------
# Read-only, assumable ONLY from pull_request — keeps the privileged (environment-gated)
# deploy role out of the untrusted PR path entirely. Wire to AWS_PLAN_ROLE_ARN in infra-ci.yml.
data "aws_iam_policy_document" "plan_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [for r in local.deploy_repos : "repo:${var.github_org}/${r}:pull_request"]
    }
  }
}

resource "aws_iam_role" "plan" {
  name               = "${var.name_prefix}-ci-plan"
  assume_role_policy = data.aws_iam_policy_document.plan_trust.json
}

resource "aws_iam_role_policy_attachment" "plan_readonly" {
  role       = aws_iam_role.plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# Bedrock model-invocation logging behind a PII mask. Account+region-level capture of every
# InvokeModel/Converse call: token counts, modelId, identity, and (text + embedding)
# request/response bodies — the canonical AWS-native source for per-call token counts. It is
# a singleton (one config per region).
#
# CRITICAL ORDERING (non-reversible): the PII data-protection mask
# (aws_cloudwatch_log_data_protection_policy.bedrock_invocations) MUST exist on the log
# group BEFORE the logging configuration writes its first record — any record that lands
# before the mask is stored unmasked permanently and cannot be masked retroactively. The
# depends_on enforces this; never split the apply so the config lands before the policy.

locals {
  # Managed PII identifiers masked on the invocation-log group. Generic Name/Address are
  # not valid CloudWatch Logs managed identifiers (they would reject the policy); free-text
  # customer names have no managed identifier and remain unmasked.
  bedrock_pii_identifiers = [
    "arn:aws:dataprotection::aws:data-identifier/EmailAddress",
    "arn:aws:dataprotection::aws:data-identifier/PhoneNumber-US",
    "arn:aws:dataprotection::aws:data-identifier/Ssn-US",
    "arn:aws:dataprotection::aws:data-identifier/DriversLicense-US",
    "arn:aws:dataprotection::aws:data-identifier/CreditCardNumber",
  ]
}

resource "aws_cloudwatch_log_group" "bedrock_invocations" {
  name              = "/aws/bedrock/${var.name_prefix}/modelinvocations"
  retention_in_days = var.bedrock_invocation_log_retention_days
}

# Bedrock-trusted role that lets the service write invocation records to the group.
# Trust is scoped by SourceAccount + SourceArn so only this account's Bedrock can assume it.
resource "aws_iam_role" "bedrock_invocation_logging" {
  name = "${var.name_prefix}-bedrock-invocation-logging"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = var.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:aws:bedrock:${var.region}:${var.account_id}:*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "bedrock_invocation_logging" {
  name = "write-invocation-logs"
  role = aws_iam_role.bedrock_invocation_logging.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = ["${aws_cloudwatch_log_group.bedrock_invocations.arn}:*"]
    }]
  })
}

# PII mask — exactly two statements (Audit then Deidentify) with IDENTICAL
# DataIdentifier arrays; Audit carries a FindingsDestination ({} = no separate sink).
resource "aws_cloudwatch_log_data_protection_policy" "bedrock_invocations" {
  log_group_name = aws_cloudwatch_log_group.bedrock_invocations.name
  policy_document = jsonencode({
    Name    = "${var.name_prefix}-bedrock-pii-mask"
    Version = "2021-06-01"
    Statement = [
      { Sid = "Audit", DataIdentifier = local.bedrock_pii_identifiers, Operation = { Audit = { FindingsDestination = {} } } },
      { Sid = "Deidentify", DataIdentifier = local.bedrock_pii_identifiers, Operation = { Deidentify = { MaskConfig = {} } } },
    ]
  })
}

resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  # PII mask MUST exist first (see header); the role policy must exist before Bedrock writes.
  depends_on = [
    aws_cloudwatch_log_data_protection_policy.bedrock_invocations,
    aws_iam_role_policy.bedrock_invocation_logging,
  ]
  logging_config {
    text_data_delivery_enabled      = true # nova-lite = text + embedding only
    embedding_data_delivery_enabled = true
    image_data_delivery_enabled     = false
    video_data_delivery_enabled     = false
    # large_data_delivery_s3_config DELIBERATELY UNSET: bodies >100KB are TRUNCATED in
    # CloudWatch, not spilled to a Bedrock-managed S3 path (which the CWL mask would NOT
    # cover). Setting it would reintroduce an unmasked-PII surface.
    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.bedrock_invocations.name
      role_arn       = aws_iam_role.bedrock_invocation_logging.arn
    }
  }
}

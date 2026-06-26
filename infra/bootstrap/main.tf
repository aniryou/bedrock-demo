# Bootstrap: the publish targets the component repos write to. Apply this FIRST;
# then the agent/stubs CIs publish their artifacts here; then apply ../terraform.
#
#   ECR   <- order-triage-agent CI pushes the ARM64 image
#   S3    <- agent publishes kb/ ; stubs publish stubs/*.zip + *.openapi.json

resource "aws_ecr_repository" "agent" {
  name         = "${var.name_prefix}-agent"
  force_delete = true
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_s3_bucket" "artifacts" {
  bucket        = "${var.name_prefix}-artifacts-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

# Container for the Entra OBO client secret. Terraform creates the secret but NOT its value
# (no aws_secretsmanager_secret_version here) — the value is injected out-of-band by the
# orchestrator (`seed_entra_secret` / put-secret-value) so it never enters any Terraform
# state. The main stack reads it by ARN via clientSecretSource=EXTERNAL (../terraform/identity.tf).
resource "aws_secretsmanager_secret" "entra_obo" {
  name        = "order-triage/entra-agent-client-secret"
  description = "Entra agent (OBO) client secret as JSON {\"client_secret\":\"...\"}; value injected out-of-band, never via Terraform."
}

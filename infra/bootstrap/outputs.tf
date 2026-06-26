# Feed these to the component CIs (as secrets) and to ../terraform (as vars).
output "ecr_repository_url" {
  value       = aws_ecr_repository.agent.repository_url
  description = "ECR_REPOSITORY_URL secret for the agent-build CI; agent_image_uri = this:latest."
}

output "artifacts_bucket" {
  value       = aws_s3_bucket.artifacts.bucket
  description = "ARTIFACTS_BUCKET secret for agent + stubs CIs; artifacts_bucket var for ../terraform."
}

output "ci_publish_role_arn" {
  value       = aws_iam_role.publish.arn
  description = "AWS_PUBLISH_ROLE_ARN secret for the agent-build + stubs-release CIs."
}

output "ci_deploy_role_arn" {
  value       = aws_iam_role.deploy.arn
  description = "AWS_DEPLOY_ROLE_ARN secret for the deploy job (environment-gated)."
}

output "ci_plan_role_arn" {
  value       = aws_iam_role.plan.arn
  description = "AWS_PLAN_ROLE_ARN secret for the infra-ci PR plan job (read-only)."
}

# AgentCore Registry has no Terraform resource (in either the aws or awscc
# provider), so register the agent/tools/skills via the retained boto3 script
# (idempotent, fail-soft) once the gateway + runtime exist. Runs from the repo root
# (where the `infra` python package + registry/manifest.json live).
resource "terraform_data" "registry" {
  input            = var.region # echoed so the destroy provisioner can read it via self.input
  triggers_replace = [filemd5("${path.module}/../registry/manifest.json")]
  depends_on = [
    aws_bedrockagentcore_gateway_target.sap,
    aws_bedrockagentcore_agent_runtime.this,
  ]

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    command     = "uv run python -m infra.register"
    environment = {
      AWS_REGION = var.region
    }
  }

  # Registry has no TF resource, so plain `terraform destroy` would leak it (and
  # without this, every redeploy mints a fresh duplicate). Tear it down on destroy/replace.
  # Destroy provisioners may only reference self/count/each — hence self.input.
  provisioner "local-exec" {
    when        = destroy
    working_dir = "${path.module}/.."
    command     = "uv run python -m infra.deregister"
    environment = {
      AWS_REGION = self.input
    }
  }
}

# Cold-start hardening for AgentCore eventual-consistency races on a from-scratch
# `make deploy`. Both time_sleep resources sleep ONLY on create — re-applies /
# `make redeploy` over an existing stack are no-ops (no triggers), and
# destroy_duration=0s keeps `make destroy` from being delayed. depends_on is
# metadata-only, so adding the gates below does not force-replace any resource.

# RACE 1 — IAM is eventually consistent AFTER the gateway role + its inline policy
# resources complete. CreateGateway can 403 ("security token included in the request
# is invalid") if it runs before the role has propagated. Gate the gateway behind this.
resource "time_sleep" "gateway_iam" {
  depends_on       = [aws_iam_role.gateway, aws_iam_role_policy.gateway]
  create_duration  = var.gateway_iam_propagation_delay
  destroy_duration = "0s"
}

# RACE 2 — gateway targets report status=READY before their OpenAPI-derived actions
# (sap___*, orders___*, snowflake___*) are queryable by the Cedar policy engine; the
# actions register asynchronously after the target reports READY. Creating a policy too
# early → CREATE_FAILED "unrecognized action ...". Hold long enough for all three targets'
# actions to register. If a from-scratch apply ever still hits "unrecognized action", bump
# this duration or swap for a polling null_resource — the wiring (targets → here →
# policies) is identical either way.
resource "time_sleep" "target_actions" {
  depends_on = [
    aws_bedrockagentcore_gateway_target.sap,
    aws_bedrockagentcore_gateway_target.orders,
    aws_bedrockagentcore_gateway_target.snowflake,
  ]
  create_duration  = var.target_actions_propagation_delay
  destroy_duration = "0s"
}

# Contingencies (documented, intentionally NOT wired — only the two races above occur in
# practice, and pre-gating the rest would slow every apply):
#  - If a gateway target ever fails on an invalid/missing credential provider, add
#    depends_on (or a short time_sleep) from the targets to
#    aws_bedrockagentcore_api_key_credential_provider.snowflake.
#  - If `infra.register` keeps logging "skipped/None", that is a depends_on-breadth gap in
#    registry.tf (it waits only on the sap target + runtime) — widen it to the orders +
#    snowflake targets and the 3 policies. That's a correctness fix, not a time_sleep.

# ADR-0010: Move the sap/orders Gateway targets to native Lambda (ARN) targets

**Status:** Proposed — **pending AWS support-case confirmation** of the SigV4 root cause (below).
The code/Terraform change is implemented and `tf-validate`-green, but **not applied** (deploy is
human-gated). The native-Lambda-target architecture is the chosen direction regardless of the
exact 403 cause.
**Date:** 2026-06-30
**Deciders:** Anil Choudhary
**Related:** [ADR-0006](0006-gateway-role-least-privilege.md) (this **supersedes its D1** — the
`lambda:InvokeFunctionUrl`-only grant), [ADR-0009](0009-snowflake-function-url-direct-call-hardening.md)
(snowflake is now the *only* Function URL), [ADR-0001](0001-user-impersonation-obo.md) (the OBO
snowflake path is unchanged). RCA writeup: [`research/agentcore-gateway-functionurl-sigv4-403.md`](../research/agentcore-gateway-functionurl-sigv4-403.md).

## Context

The `sap___getCreditStatus` and `orders___flagOrder` tool calls fail at runtime with the agent
surfacing "An error occurred. Please retry later." The RCA found this is a hard **HTTP 403
Forbidden** at the SAP/orders Lambda **Function URL `AWS_IAM` auth gate**, *before* the Lambda
runs (gateway `APPLICATION_LOGS`, req `d8afaea4`). The failure splits exactly along the auth
model: every SigV4 / `AuthType=AWS_IAM` Function-URL target fails; the only non-SigV4 target —
snowflake (`AuthType=NONE` + Entra OBO bearer) — succeeds. IAM is provably correct on both halves
(the gateway role's identity policy grants `lambda:InvokeFunctionUrl`; each function's resource
policy allows that role; the IAM policy simulator returns `allowed`), and a SigV4-signed
(`service=lambda`) GET to the URL as another principal returns 200. So the fault is the Gateway's
**outbound SigV4 egress to the `AWS_IAM` Function URL** not being accepted as the gateway
principal — **not** a missing IAM permission.

## Decision

Move `sap` and `orders` off the Function-URL SigV4 egress onto **native AgentCore Gateway Lambda
(ARN) targets** — the Gateway invokes the function directly via `lambda:InvokeFunction`, carrying
an inline tool schema. This eliminates the failing SigV4-to-Function-URL leg entirely while
**keeping IAM authorization** (no public surface). `snowflake` is unchanged (it keeps its
`AuthType=NONE` Function URL reached by the OBO bearer — a different, working path).

## Options considered

- **Native Lambda (ARN) target (chosen).** Removes the failing egress path; keeps IAM auth; no
  public URL. Costs a stub-handler rewrite (below).
- **`AuthType=NONE` Function URL + X-API-Key** (the snowflake-style egress). **Rejected** — makes
  sap/orders internet-invocable (principal `*`); a security regression that contradicts the
  IAM/Gateway boundary ADR-0009 preserves for all-but-the-illustrative-snowflake backend.
- **Add IAM permissions.** Rejected — IAM is already provably correct; more permissions cannot
  fix a signature/canonicalization-level rejection.
- **`terraform_data` + AWS CLI** to create the targets (the snowflake-OBO-egress pattern). Held in
  reserve only if the provider's native `lambda {}` block proves unusable; native HCL validated, so
  not needed.

## Consequences

- **Stub handlers rewritten.** A native Lambda target delivers the tool args as a flat JSON event
  (not an HTTP request), so `sap`/`order_actions` `lambda_handler.py` drop Mangum and dispatch on
  `context.client_context.custom['bedrockAgentCoreToolName']`, calling the `app.py` route function
  directly. The FastAPI apps (local `make sap`/`order-actions`, hermetic tests) are unchanged.
  This is a **stubs release** — the new zips must be published before the infra apply.
- **Inline tool schema replaces OpenAPI** for these two targets; their `openapi.json` becomes local
  docs only. Tool names are pinned to `getCreditStatus` / `flagOrder` so the MCP tool ids
  (`sap___getCreditStatus`, `orders___flagOrder`) — which Cedar (`policy.tf`) and the agent
  hard-reference — are preserved.
- **Gateway role grant flips** `lambda:InvokeFunctionUrl` → `lambda:InvokeFunction` on the two
  function ARNs (**supersedes ADR-0006 D1**); each function gains an `aws_lambda_permission` for
  the `bedrock-agentcore.amazonaws.com` service principal scoped to this account's gateways
  (covering both the role and service-principal invoke paths).
- **Attack surface shrinks:** the two `AuthType=AWS_IAM` Function URLs are removed; snowflake's is
  the only remaining Function URL.

## Risks

- **Root cause is inferred, not proven** (the decisive test — sign as `role/order-triage-gateway`
  — isn't runnable read-only; the role trusts only `bedrock-agentcore.amazonaws.com`). Hence Status
  = Proposed pending the AWS support case. The native-Lambda target is preferable regardless, so
  the fix stands even if AWS pinpoints a Function-URL-side cause.
- **Invoke principal uncertainty:** whether AgentCore invokes as the gateway role or the service
  principal at runtime. Mitigated by granting **both** (identity policy on the role + resource
  policy for the service principal). If a `READY`-but-`AccessDenied` appears at invoke time, the
  resource-policy `principal` is the lever.
- **Empty `gateway_iam_role {}` credential block** for the Lambda target is HCL-valid but its
  API-level acceptance is unverified offline — confirm at `terraform plan` against live.
- **Apply ordering:** the stub zip must be published *before* the infra apply, or live tool calls
  hit the new targets with old (Mangum) code.

## Action items

- [ ] **AWS support case** — confirm the Function-URL SigV4 403 cause (service/host signed,
      `x-amz-content-sha256` over the body). Draft: `research/agentcore-gateway-functionurl-sigv4-403.md`.
- [ ] Publish the stub zips (`stubs-release.yml`) **before** the gated `make deploy`.
- [ ] After apply, verify via the gateway `APPLICATION_LOGS` (`isError=false`) + a fresh
      `/aws/lambda/order-triage-sap` invocation stream.
- [ ] **Regenerate the architecture diagrams when deployed** — `data-plane.md` (mermaid + prose),
      `specs.json` → `security/data-plane/end-to-end` SVGs (via the `architecture-skill`), and the
      README still describe the sap/orders Function-URL/SigV4 egress (current live state).

## References

- [AWS Lambda function targets for AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html);
  `CreateGatewayTarget` API; `hashicorp/aws` `aws_bedrockagentcore_gateway_target` (`mcp.lambda`).

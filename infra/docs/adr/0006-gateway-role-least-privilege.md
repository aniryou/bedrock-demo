# ADR-0006: Least-privilege scoping of the AgentCore Gateway IAM role

**Status:** Accepted — implemented in `terraform/iam.tf` and **verified live end-to-end 2026-06-24** (deployed to 953472632913/us-west-2; `make status` triage of O-1003 succeeded and Snowflake `QUERY_HISTORY` shows the order read ran as the OBO user `SVC_TRIAGE_TEST_ENTRA`/`ORDER_TRIAGE_RO`, not the service user). The final policy has **four** statements — two more than the first cut, because live testing surfaced two load-bearing pieces of `bedrock-agentcore:*` that static reasoning missed (Cedar policy evaluation, and the EXTERNAL OBO client-secret read). See "The two live-test corrections".
**Date:** 2026-06-24
**Deciders:** Anil Choudhary (proposer); platform + security owners
**Related:** [ADR-0001](0001-user-impersonation-obo.md) (the Gateway-brokered OBO `TOKEN_EXCHANGE` this role brokers), the security view [`../architecture/security-architecture.md`](../architecture/security-architecture.md) (where the over-permission was flagged), the OBO runbook [`../playbooks/entra-obo-setup.md`](../playbooks/entra-obo-setup.md), and `policy.tf` (the Cedar policy engine this role must evaluate).

## Context

The AgentCore Gateway's execution role (`aws_iam_role.gateway`, `terraform/iam.tf`) carried a single broad statement:

```hcl
Action   = ["lambda:InvokeFunctionUrl", "lambda:InvokeFunction", "secretsmanager:GetSecretValue", "bedrock-agentcore:*"]
Resource = "*"
```

This was over-permissive relative to the rest of the stack, which is tightly scoped: the snowflake-query Lambda role gets `GetSecretValue` on **exactly its one** Snowflake secret ARN (`snowflake_lambda.tf`), and the runtime role only on the `bedrock-agentcore-identity!*` prefix (`iam.tf`). The Gateway role, by contrast, could read **every secret in the account** — including the Snowflake RSA private key (`order-triage/snowflake-*`) and any unrelated workload's secret — and perform **every** AgentCore action (~213, including `CreateGateway` / `DeleteGateway` / `UpdateGatewayTarget` / policy-engine + credential-provider lifecycle). It was flagged as a known caveat in `security-architecture.md`; this ADR is the remediation.

**What the role actually does at request time** (inbound auth is `CUSTOM_JWT`, `gateway.tf`). Three jobs:

1. **SigV4 to the SAP + order-actions targets.** Both Function URLs are `AuthType = AWS_IAM` with `gateway_iam_role { service = "lambda" }` (`gateway.tf`), so the Gateway SigV4-signs as this role. Required action: `lambda:InvokeFunctionUrl` (not `InvokeFunction`). The URLs' resource policy already pins the principal to this role (`sap_lambda.tf`/`order_actions_lambda.tf`). The snowflake Function URL is `AuthType = NONE` — never IAM-invoked.
2. **OBO brokering for the snowflake target.** When `entra_agent_app_id` is set, the snowflake target's egress is `grant_type = TOKEN_EXCHANGE` (`snowflake_lambda.tf`), and the **Gateway** performs the two-step on-behalf-of flow as the caller: `GetWorkloadAccessTokenForJWT` → `GetResourceOauth2Token` (`entra-obo` provider). When `entra_agent_app_id == ""`, it falls back to the `X-API-Key` egress, read via `GetResourceApiKey`.
3. **Cedar policy evaluation.** The Gateway runs a policy engine in `ENFORCE` mode (`policy.tf`, attached in `gateway.tf`). On every MCP `ListTools` and tool call it evaluates Cedar via Policy in AgentCore **as this role**.

## Decision

Replace the wildcard with four least-privileged statements (`iam.tf:aws_iam_role_policy.gateway`):

**D1 — `lambda:InvokeFunctionUrl` on exactly the two SigV4 targets** (`aws_lambda_function.sap.arn`, `aws_lambda_function.order_actions.arn`). Dropped the unused `lambda:InvokeFunction`; the snowflake function is absent (its URL is `AuthType = NONE`). _**Superseded by [ADR-0010](0010-sap-orders-native-lambda-targets.md):** sap/orders are now native Lambda targets, so the action is `lambda:InvokeFunction` (the SigV4 Function-URL egress was the source of a 403). Job #1 above changes accordingly._

**D2 — the OBO token-mint actions, Resource = `*`.** `GetWorkloadAccessTokenForJWT` + `GetResourceOauth2Token` (OBO) + `GetResourceApiKey` (the count-guarded `X-API-Key` fallback); both egress configs granted statically so the role is correct whether or not OBO is enabled. **Resource stays `*`** because these token-mint actions authorize against several required resource types at once (`oauth2credentialprovider`/`apikeycredentialprovider`, the default `token-vault`, and the `workload-identity` the Gateway creates implicitly), not all exposed as Terraform attributes; pinning risks a silent `AccessDenied` that breaks impersonation. The win is the **action** restriction (three read/token actions, not all of `bedrock-agentcore:*`).

**D3 — Cedar policy-engine evaluation, scoped to the gateway + policy-engine resource types.** `GetPolicyEngine` + `AuthorizeAction` + `PartiallyAuthorizeActions` (AWS's documented required set for a Gateway with Policy in AgentCore), on `arn:…:policy-engine/*` and `arn:…:gateway/*` in this account/region (`var.region` + `local.account_id`). **Not** the exact ARNs: the role policy must exist *before* the gateway (the gateway waits on it via `time_sleep.gateway_iam`, `cold_start.tf`), so referencing the gateway/policy-engine resources here forms a dependency cycle. Account+region+type scoping is AWS's documented fallback and a large improvement over `Resource = "*"` (all resource types).

**D4 — `GetSecretValue` on the two provider secrets the caller actually reads.** A `concat()` of `arn:…:secret:bedrock-agentcore-identity!*` (the AgentCore-managed `snowflake-api-key` value, read by `GetResourceApiKey`) **and** — only when OBO is configured — the **exact** `order-triage/entra-agent-client-secret` ARN (`data.aws_secretsmanager_secret.entra_obo[0].arn`), which `GetResourceOauth2Token` reads at `TOKEN_EXCHANGE` time because the `entra-obo` provider uses `clientSecretSource = EXTERNAL`. Scoped to those two only — **not** `order-triage/*` (which holds the Snowflake RSA key) and not all secrets.

## The two live-test corrections

The first implementation had only D1, D2, and a D4 that granted **only** `bedrock-agentcore-identity!*`. Deploying it and running `make status` failed twice, each failure naming a load-bearing piece of the old `bedrock-agentcore:*` / broad-secret grant that static reasoning had missed. This is exactly the breadth the task's CAUTION anticipated.

1. **Cedar policy evaluation (→ D3).** `ListTools` failed `"Insufficient Permissions for Policy Evaluation"`. The Gateway runs the Cedar engine in `ENFORCE` mode, and per AWS's *Gateway + Policy in AgentCore IAM Permissions* doc the execution role needs `AuthorizeAction` + `PartiallyAuthorizeActions` + `GetPolicyEngine` (on the gateway + policy-engine resources) — none of which is among the OBO/egress actions. `bedrock-agentcore:*` had silently covered them.
2. **EXTERNAL OBO client secret read by the caller (→ D4).** After D3, the snowflake tool call failed `"Token exchange failed: insufficient permissions for token exchange."` CloudTrail showed the gateway role denied `GetSecretValue` on `order-triage/entra-agent-client-secret`. **This corrected a wrong inference in the first draft of this ADR**, which claimed the EXTERNAL secret is read by AgentCore at provider-create time, not by the caller. It is read by the caller (the Gateway), live, on every exchange — `clientSecretSource = EXTERNAL` dereferences the customer secret at token-mint time using the caller's role. (The runtime role's `bedrock-agentcore-identity!*`-only grant worked for the earlier *in-agent* OBO because that predated this gateway-brokered, EXTERNAL-source arrangement; the runtime no longer brokers OBO, so its scope is moot.)

Each correction was found by a deploy → invoke → read-the-error loop, not by reading docs alone.

## Options considered

- **A — leave the wildcard (rejected).** Lets the Gateway read the Snowflake RSA key + every secret and run any AgentCore management action.
- **B — narrow actions, keep Resource = `*` everywhere (rejected as final shape).** Leaves `GetSecretValue` on `*` — the grant that exposes the RSA key. D4 scopes it.
- **C — fully pin every resource ARN (adopted where possible: D1, D4-entra; impossible for D2/D3).** D1 and the entra secret in D4 ARE pinned to exact ARNs. D2's token-mint actions need multiple resource types incl. the implicit workload identity; D3's Cedar actions would form a Terraform dependency cycle if they referenced the gateway/policy-engine resources — so both are type-scoped, not ID-pinned.
- **D — explicit `Deny` on `GetWorkloadAccessTokenForUserId` (noted, not adopted).** Redundant: D2 is an exact-name allow-list with no `GetWorkloadAccessToken*` wildcard, so the user-id variant is already not granted.

## Consequences

- **Blast radius drops sharply** (verified by `aws iam simulate-principal-policy`): the role can no longer read the Snowflake RSA key (`order-triage/snowflake-*` → `implicitDeny`), any `order-triage/*` secret other than the entra client secret, or any unrelated secret; it cannot create/delete gateways/targets, mutate the policy engine, or manage credential providers (`CreateGateway`/`DeleteGateway` → `implicitDeny`). It retains exactly: invoke two named Function URLs, mint OBO/API-key tokens, evaluate its own Cedar engine, and read the two provider secrets.
- **OBO impersonation is preserved and proven** — the order read runs as the calling human's mapped Snowflake user under RLS, not the shared service account.
- **Static where it can be:** both egress configs and both fallback paths are granted unconditionally except the entra secret ARN (count-guarded on `entra_agent_app_id`), so toggling OBO needs no other gateway-policy change.

## Verification (live, 2026-06-24)

- `terraform fmt -check -recursive` + `terraform validate` pass; `make tf-validate` passes end-to-end with creds. `terraform apply` = in-place update of `aws_iam_role_policy.gateway` only, `0 destroyed`.
- `make status` (ROPC test user `svc-triage-test@…` → Snowflake `SVC_TRIAGE_TEST_ENTRA`) returns a complete triage of O-1003 with **no** `McpError` / permission error.
- Snowflake `QUERY_HISTORY` (`INFORMATION_SCHEMA.QUERY_HISTORY` as ACCOUNTADMIN): the order `SELECT` ran as `USER_NAME = SVC_TRIAGE_TEST_ENTRA`, `ROLE_NAME = ORDER_TRIAGE_RO`, `SUCCESS` — the OBO-impersonated user, **not** `SVC_ORDER_TRIAGE`. (A separate `SVC_ORDER_TRIAGE` SELECT is the order-actions status-check X-API-Key service path — a different consumer by design, not a fallback of the agent's read.)
- `aws iam simulate-principal-policy`: the needed actions are `allowed`; the RSA-key read, arbitrary-secret reads, gateway management, and `InvokeFunctionUrl` on the snowflake fn are `implicitDeny`.
- CloudTrail: the entra-secret `GetSecretValue` transitioned `AccessDenied` (pre-fix) → `OK` (post-fix), with no residual gateway-role denials during the successful invoke.

## Risks

- **R1 — residual `Resource = "*"` on the three OBO token-mint actions (D2).** Mitigated by the tight action allow-list (read/token-fetch only) and the secret scope in D4 (the sensitive read is the `GetSecretValue`, now pinned). Fully resource-scoping these is a future refinement, gated on a live OBO CloudTrail trace exposing the exact resource ARNs (and the multi-required-resource-type behaviour).
- **R2 — entra-secret ARN match on rotation.** D4 pins the exact current ARN (`…entra-agent-client-secret-LjgyvK`) via the data source. Secrets Manager keeps the 6-char suffix stable across `put-secret-value` rotations (only a full delete+recreate changes it), and the data source re-resolves on every apply, so rotation via `make seed-entra-secret` is safe. A delete+recreate of the secret would need a re-apply (the data source picks up the new ARN automatically). The Entra **client secret value** still expires 2026-12-17 (separate concern, `../playbooks/entra-obo-setup.md`).
- **R3 — OBO-off (`entra_agent_app_id == ""`) path not live-tested.** The `X-API-Key` fallback (`GetResourceApiKey` + `bedrock-agentcore-identity!*`) is granted but was not exercised (the deployed stack runs OBO-on). Low risk: the actions/secret it needs are present and simulate as `allowed`.

## Action items

- [x] `make tf-validate`, `make deploy`, `make status` + Snowflake `QUERY_HISTORY` confirm OBO runs as `SVC_TRIAGE_TEST_ENTRA` (R2 of the original draft — **closed**, verified live).
- [ ] If/when a config exercises OBO-off, confirm the `X-API-Key` fallback path live (R3).
- [ ] Optional: resource-scope D2 once a live OBO CloudTrail trace confirms the exact authorized resources (R1).

## References

- AWS — *AgentCore Gateway and Policy in AgentCore IAM Permissions* (`policy-permissions.html`: the execution role's `AuthorizeAction` / `PartiallyAuthorizeActions` / `GetPolicyEngine` on the gateway + policy-engine ARNs). *Actions, resources, and condition keys for Amazon Bedrock AgentCore* (`GetWorkloadAccessTokenForJWT` / `GetResourceOauth2Token` / `GetResourceApiKey`). *Set up outbound authorization for your gateway*.
- Internal — `terraform/iam.tf` (`aws_iam_role_policy.gateway`, `.runtime`), `terraform/gateway.tf`, `terraform/policy.tf` (Cedar engine, `ENFORCE`), `terraform/cold_start.tf` (`time_sleep.gateway_iam` — the dependency-cycle constraint), `terraform/snowflake_lambda.tf` (`terraform_data.snowflake_obo_egress`), `terraform/identity.tf` (`entra-obo` `clientSecretSource = EXTERNAL`), `docs/playbooks/entra-obo-setup.md`, ADR-0001.

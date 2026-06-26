# ADR-0009: Defer hardening the snowflake Function URL's direct-call path

**Status:** Accepted — **hardening deferred** (no code/Terraform change). The direct-URL bypass is
an **accepted, recorded risk** while the snowflake target remains an *illustrative* demo backend;
option (a) (IAM-front the URL) is **rejected** outright because it would reverse the Gateway-brokered
OBO, and option (b) (validate the inbound JWT in the stub) is **deferred, not rejected** — it becomes
the chosen hardening if/when a revisit trigger fires. This homes the "tracked separately" follow-up
that [ADR-0008](0008-semantic-view-cortex-analyst.md) §Risks #6 deferred out of its migration scope.
**Date:** 2026-06-24
**Deciders:** Anil Choudhary (proposer); platform + security owners
**Related:** [ADR-0008](0008-semantic-view-cortex-analyst.md) §Risks #6 (where this was first flagged)
and §Risks #5 (the `CUSTOMERS` RLS gap that bounds the residual exposure), [ADR-0001](0001-user-impersonation-obo.md)
(the Gateway-brokered OBO `TOKEN_EXCHANGE` this decision preserves), [ADR-0006](0006-gateway-role-least-privilege.md)
(the single-credential-slot facts this analysis rests on), `terraform/snowflake_lambda.tf`
(`aws_lambda_function_url.snowflake` + `aws_lambda_permission.snowflake_url` + `terraform_data.snowflake_obo_egress`),
`../../../stubs/snowflake_stub/app.py` (`_user_token`).

## Context

The snowflake-query Lambda's Function URL is publicly invocable and the stub does not validate the
inbound bearer:

- `aws_lambda_function_url.snowflake` is `authorization_type = "NONE"`, and
  `aws_lambda_permission.snowflake_url` grants `lambda:InvokeFunctionUrl` to `principal = "*"`
  (`snowflake_lambda.tf`) — anyone on the internet can reach the URL.
- `snowflake_stub/app.py:_user_token` extracts a non-empty `Authorization: Bearer <token>` and
  forwards it verbatim to **Cortex Analyst** (`/api/v2/cortex/analyst/message`) and the **SQL API**
  (`/api/v2/statements`) with token-type `OAUTH`. It performs **no** signature / `aud` / `iss` / `exp`
  check — it relies entirely on **Snowflake** to validate the token.

**What is — and is not — in the enforcement path.** For a request that arrives *through the Gateway*,
inbound `CUSTOM_JWT` auth + the Cedar `permit_snowflake_ask` policy (`policy.tf`) gate the call, and
the Gateway's OBO `TOKEN_EXCHANGE` egress injects the per-user Snowflake bearer (`snowflake_lambda.tf`,
[ADR-0001](0001-user-impersonation-obo.md)). For a *direct* caller of the Function URL, **the Gateway
and Cedar are not in the path at all.** The only remaining boundary is Snowflake's own External-OAuth
token validation + that user's RBAC and row-access policy. So any holder of a valid Snowflake-audience
OBO/External-OAuth token — including a captured/replayed token within its lifetime — can `POST /ask`
directly and bypass Gateway/Cedar. (This predates the ADR-0008 migration: the prior fixed-SQL
`_authorize` forwarded the bearer unvalidated too.)

**The constraint that shapes the options** ([ADR-0006](0006-gateway-role-least-privilege.md) establishes
it). An AgentCore Gateway target has exactly **one** outbound credential slot. `sap`/`orders` fill it
with `gateway_iam_role { service = "lambda" }` (SigV4) — which is *why* their Function URLs are
`AuthType = AWS_IAM`, invoked only by the Gateway role. The `snowflake` target fills that same slot
with `OAUTH / grant_type = TOKEN_EXCHANGE` (the per-user OBO bearer). SigV4-signing and OBO-bearer
injection are **mutually exclusive on one target** — so the snowflake URL cannot be `AWS_IAM` *and*
keep the Gateway-brokered OBO that the whole RLS/per-user-attribution story depends on.

## Decision

**D1 — Do not change the auth posture now.** Keep the Function URL `authorization_type = "NONE"` and
the stub's forward-unvalidated behaviour. Record the direct-URL bypass as an **accepted risk** rather
than implementing either hardening option in this change.

**D2 — Preserve Gateway-brokered OBO as load-bearing; reject option (a).** The native AgentCore
`TOKEN_EXCHANGE` — where the *Gateway* brokers the on-behalf-of token and the agent/stubs carry **no**
OBO code — is the demo's core authorization win ([ADR-0001](0001-user-impersonation-obo.md),
[ADR-0006](0006-gateway-role-least-privilege.md)). Option (a) (front the URL with `AWS_IAM`) would, per
the single-slot constraint, force the OBO exchange back **into the Lambda** (receive the raw inbound
JWT via a side header; call `GetWorkloadAccessTokenForJWT` / `GetResourceOauth2Token` in-process). That
reverses the design across repos and re-introduces exactly what ADR-0001 engineered away. It is
**rejected**, not merely deferred.

**D3 — Treat the Snowflake backend as illustrative; this is the hinge of the deferral.** The `/ask`
Lambda exists to demonstrate a *governed-data Gateway target*; the specific backing service is
incidental and could be any system. Given that demo scope, the marginal security value of hardening
*this particular* public URL is low relative to the architectural cost of doing so. That trade-off — not
a technical blocker on option (b) — is why hardening is deferred.

**D4 — Record option (b) as the chosen future hardening, with concrete revisit triggers.** If the
scope assumption in D3 stops holding, validate `signature + aud + iss + exp` in `_user_token` against
the Entra OIDC discovery document before forwarding (see Action items for the prerequisite). Capture
the one fact that can't be obtained while the stack is torn down — the OBO-exchanged token's exact
`aud` / `iss` / version — on first live deploy, so a later implementation is not guesswork.

## Options considered

- **A — `AWS_IAM`-front the URL + move OBO into the Lambda (REJECTED, D2).** Restores a true
  "only the Gateway role may invoke" boundary, but the single credential slot means the Gateway can no
  longer inject the user bearer, so the Lambda must broker OBO itself. Multi-repo, regressive, and
  reverses the native Gateway-brokered OBO that is the demo's point.
- **B — Validate the inbound JWT in `_user_token` before forwarding (DEFERRED, D4 — the chosen shape
  if scope changes).** Self-contained in the stub (+ a little Terraform to pass tenant id + expected
  audience as Lambda env). Rejects forged / expired / wrong-issuer / wrong-audience tokens at an edge
  *we* control, pinned tighter than Snowflake's own integration. **Partial by construction:** it does
  **not** restore Gateway/Cedar to the enforcement path, and it does **not** stop replay of a valid,
  live, Snowflake-audience token (Snowflake remains the authority for those). Do not oversell it at
  revisit time.
- **C — Defer / accept as a recorded risk (CHOSEN).** No code change; the residual boundary stays
  "Snowflake token validation + user RBAC/RLS"; the Gateway-brokered OBO design and the demo's
  simplicity are preserved.
- **D — Eliminate the URL via a Snowflake-managed MCP server as a native Gateway target (strategic
  end-state).** This is [ADR-0008](0008-semantic-view-cortex-analyst.md) Option B: it deletes the
  Lambda + Function URL entirely, so this risk **dissolves** rather than being mitigated. Blocked on
  reconciling its OAuth model with Entra External OAuth + Gateway OBO; tracked in ADR-0008. **Prefer
  this over (b)** if a revisit coincides with pursuing the managed-MCP end-state.

## Consequences

- **The direct-URL bypass persists (accepted).** A holder of a valid Snowflake-audience token can
  `POST /ask` directly, bypassing Gateway/Cedar; the residual boundary is Snowflake's token validation
  + the user's RBAC/RLS. It is bounded by the row-access policy on `ORDERS.region` (order rows are
  per-user scoped) **but** note [ADR-0008](0008-semantic-view-cortex-analyst.md) §Risks #5 — `CUSTOMERS`
  is unpoliced, so a region-scoped user reaching customer attributes directly is not region-scoped.
- **The Gateway-brokered OBO design stays intact** and the demo stays simple. No Terraform/stub change,
  nothing to deploy, no new failure modes introduced.
- **The follow-up now has a home and a rationale.** ADR-0008 §Risks #6 / its action item point here;
  this ADR records *why* it is deferred and *when* it should be revisited, instead of a dangling TODO.

## Risks & open questions

1. **Replay window (the part option (b) can't close).** A captured valid OBO/External-OAuth token can
   be replayed against the URL within its lifetime. Only network/identity isolation (option a) or
   removing the URL (option d) closes this; (b) does not. Mitigants today: token lifetime + Snowflake
   RLS/RBAC.
2. **Deferral rationale (D3) is scope-dependent.** If the Snowflake target stops being illustrative —
   handles real confidential data outside the controlled demo, or becomes a productionized path — the
   trade-off flips and option (b) (at minimum) should be implemented. Tracked as a revisit trigger.
3. **The prerequisite for (b) can't be obtained while torn down.** The exact `aud` / `iss` / version of
   the OBO-exchanged Snowflake token (App-ID-URI vs bare GUID audience; v1 vs v2 issuer) can only be
   confirmed against a live token. Capture it on first live deploy (Action items) so (b) is
   implementable without guesswork.

## Revisit triggers (when this deferral expires)

- The snowflake backend becomes a real / productionized data path rather than a demo target, or begins
  handling confidential data outside the controlled demo account.
- The Function URL is exposed beyond the demo account / intended audience.
- The team pursues the managed-MCP-server end-state ([ADR-0008](0008-semantic-view-cortex-analyst.md)
  Option B) — take option (d) (which removes the URL) in preference to (b).

## Action items

- [ ] **On first live deploy**, decode one real OBO-exchanged Snowflake token and record its `aud`,
      `iss`, and token version here + in `docs/playbooks/entra-obo-setup.md`, so option (b) can be implemented
      without guessing the claim shape.
- [ ] **If any revisit trigger fires**, implement option (b): validate `signature + aud + iss + exp` in
      `snowflake_stub/app.py:_user_token` against the Entra discovery doc (PyJWT `PyJWKClient`;
      `pyjwt`/`cryptography` are already deps) before forwarding; wire `entra_tenant_id` + the expected
      Snowflake audience (derivable from `entra_obo_scope`'s `api://<snowflake-app>`, overridable) as
      Lambda env from Terraform; add hermetic tests (mint test JWTs with a throwaway RSA key, mock
      JWKS). **Prefer option (d)** (managed MCP server) if revisiting alongside ADR-0008 Option B.
- [ ] Keep [ADR-0008](0008-semantic-view-cortex-analyst.md) §Risks #6 + its action item pointing here.

## References

- AWS — *Lambda Function URL authorization* (`AuthType` `NONE` vs `AWS_IAM`); *AgentCore Gateway
  outbound authorization / credential providers* (a target's single credential configuration —
  `gateway_iam_role` SigV4 vs `oauth` `TOKEN_EXCHANGE`); Snowflake *External OAuth* token validation.
- Internal — `terraform/snowflake_lambda.tf` (`aws_lambda_function_url.snowflake`,
  `aws_lambda_permission.snowflake_url`, `terraform_data.snowflake_obo_egress`),
  `terraform/gateway.tf` (inbound `CUSTOM_JWT`, the SigV4 targets), `terraform/policy.tf`
  (`permit_snowflake_ask`), `../../../stubs/snowflake_stub/app.py` (`_user_token`),
  [ADR-0008](0008-semantic-view-cortex-analyst.md), [ADR-0006](0006-gateway-role-least-privilege.md),
  [ADR-0001](0001-user-impersonation-obo.md).

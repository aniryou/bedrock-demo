# ADR-0001: On-behalf-of user impersonation for the order-triage agent

**Status:** Accepted — implemented & validated end-to-end 2026-06-22. **Built with Microsoft Entra ID** as the IdP (not the originally-scoped Cognito, which couldn't do the OBO token exchange — RFC 8693/7523); the OBO is brokered by the **Gateway** (`grant_type=TOKEN_EXCHANGE`), not in-agent. See the runbook [`../playbooks/entra-obo-setup.md`](../playbooks/entra-obo-setup.md).
**Date:** 2026-06-20 (decided) · 2026-06-22 (implemented)
**Deciders:** Anil Choudhary (proposer); platform + security owners; order-triage-knowledge owner (for the ontology change in D2)

## Context

Today the order-triage agent invokes Snowflake, SAP, and the order-actions service using its **own service identity**. Authorization is single-sided — the Gateway/Cedar layer checks only that *the agent* may call a tool; there is no *user* dimension anywhere in the chain. Concretely:

- **Inbound:** `aws_bedrockagentcore_gateway` is `authorizer_type = "AWS_IAM"` (SigV4 as the runtime role) — `../../terraform/gateway.tf`. The runtime entrypoint sees only `session_id` — `../../../agent/src/order_triage/runtime.py`. No human identity reaches the runtime.
- **Authorization:** Cedar policies permit on `principal is AgentCore::IamEntity` + `principal.id like "*<runtime_role>*"` — `../../terraform/policy.tf`. Pure agent-identity authz.
- **Outbound:** a static `X-API-Key` injected per target by AgentCore Identity API-key credential providers — `../../terraform/identity.tf`.
- **Snowflake:** the query Lambda signs a `KEYPAIR_JWT` as **one** service user, role `AGENT_RO` (SELECT-only), against the SQL REST API — `../../../stubs/snowflake_stub/snowflake_client.py`. Every query runs as that single account.
- **SAP:** stub gated only by the static key; no user dimension.

**Goal.** Real agents impersonate the requesting human, so effective authorization = **intersection of (agent permission, enforced by Gateway/Cedar) AND (user permission, enforced by the backend once the real user identity is passed)**.

**Forces / constraints.**
- Enterprise wants per-user accountability and least privilege, not a shared service account.
- The model must scale across *many* agents without bespoke per-agent design.
- This Snowflake account is constrained: **SSO and PAT auth both currently fail; only key-pair works** (see `snowflake-data-path`). External OAuth is a *distinct* mechanism but is **unproven** here.
- The demo must be convincing end-to-end, but the impersonation path cannot be a faked claim pass-through — it must be enforced by the systems of record.

Prior research (two adversarially-verified multi-agent passes against AWS / Snowflake / SAP primary docs) established the feasible chain and ruled out a common misconception (Snowflake WIF — see Option D).

## Decision

Adopt **full native on-behalf-of (OBO) impersonation**, with the privileged-vs-not classification **declared in the enterprise ontology**. Two coupled decisions:

**D1 — Authorization architecture.** Move to: user IdP token → AgentCore Runtime + Gateway `CUSTOM_JWT` inbound authorizer → AgentCore Identity **OBO token exchange** (`GetWorkloadAccessTokenForJWT` → `GetResourceOauth2Token` with `ON_BEHALF_OF_TOKEN_EXCHANGE`, RFC 8693/7523) → **Snowflake External OAuth** (token claim → Snowflake user; scope `session:role:AGENT_RO` yields a true intersection) and **SAP OAuth 2.0 SAML Bearer** (runs as the Business User). Cedar moves from `IamEntity` to `OAuthUser`; the agent path is pinned at the IAM/source layer. **Two outbound credential paths coexist** — a service-identity path for non-privileged actions and an OBO path for privileged ones. "Full native OBO" does **not** mean everything is impersonated.

**D2 — Ontology-driven privilege.** Whether an action requires user authority is a **declarative, enterprise-wide property of the action**, classified in `order-triage-knowledge` and **decided in that repo's ADR-0001** (enterprise-owned); it is summarized here because it drives D1's credential routing — not coded per agent. Two distinct axes:
- **Data classification** (already exists): `public | internal | confidential | restricted` on object types / properties — drives Snowflake masking / row-access and whether a *read* needs user identity.
- **Action authority** (new field on `actionType`): `authority: agent | user` — drives the credential path. A sane default is derived in the build (`user` if the target object is `confidential`+ or the action mutates; else `agent`), with an explicit override.

The ontology declares the **what** ("this action requires user authority", "this data is confidential"). The agent's binding layer owns the **how** (which IdP, Snowflake role, credential-provider ARN). This boundary is the same discipline already applied to `datasource` ("source-of-truth, not a runtime table").

**Consent model (clarification).** The chosen OBO token-exchange path is **silent** — it brokers the inbound JWT directly and mints downstream tokens *without* a per-resource consent screen. The user's inbound login **is** the authorization. An explicit standing "allow this agent to act as you on Snowflake" screen is a *3LO `USER_FEDERATION`* pattern, not OBO; per-action "do this now?" approval is an *application-layer* concern (see Operational Notes).

## Options Considered

### Authorization architecture

#### Option A: Status quo — agent identity only
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low (no change) |
| User accountability | None |
| Security posture | Shared service account; confused-deputy risk |

**Pros:** nothing to build. **Cons:** no user dimension; fails the goal. **Rejected.**

#### Option B: Tier-B hybrid — user identity enforced in our Lambda
`CUSTOM_JWT` inbound + Cedar `OAuthUser` policies, but keep the `KEYPAIR_JWT` transport and have the Snowflake/SAP Lambdas enforce the user dimension in code.

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium |
| Account risk | Low (no External OAuth dependency) |
| Fidelity | Lower — user enforcement is our code, not the system of record |

**Pros:** demonstrates the intersection without betting on External OAuth in this account. **Cons:** the security boundary for the user half sits in app code, not Snowflake/SAP. **Retained as the fallback** for Snowflake only if the spike (below) fails.

#### Option C: Full native OBO — **chosen**
Real per-user RBAC enforced by Snowflake (External OAuth) and SAP (SAML bearer Business User).

| Dimension | Assessment |
|-----------|------------|
| Complexity | High |
| Account risk | Medium — depends on External OAuth working here (unproven) |
| Fidelity | Highest — systems of record enforce the user |
| Blast radius | High — SigV4→JWT changes every runtime caller |

**Pros:** genuine intersection; per-user accountability; non-bypassable enforcement. **Cons:** end-to-end inbound-auth change; Snowflake users must exist + be mapped; account risk.

#### Option D: Snowflake WIF (the "WEF" hypothesis) — **rejected for impersonation**
Workload Identity Federation is **secretless workload auth**: it maps the agent's AWS IAM role to **one** Snowflake **service** user. It carries no human identity and yields no per-user RBAC. **Retained, but repurposed** as the secretless Tier-0 service credential (a fast-follow that retires the stored key-pair), not as an impersonation mechanism.

### Privilege classification mechanism

| Option | Assessment | Verdict |
|--------|------------|---------|
| A: Hardcode per-agent (per-tool flags in code) | Duplicated across agents; drifts; not the enterprise source of truth | Rejected |
| B: Ontology-driven (`classification` + `authority`) | Declarative, inherited by every consumer, governed via PR; reuses the existing `classification` field + scaffolded `governance.yaml` | **Chosen** |
| C: IdP/Cedar scopes only | Captures roles but not data classification; not where "what is privileged" belongs | Insufficient alone (used *downstream* of B) |

## Trade-off Analysis

- **Native OBO vs Tier-B.** Native gives true backend RBAC and accountability but rides entirely on Snowflake External OAuth working in this account, and carries a large blast radius (a runtime is **SigV4 XOR JWT** — flipping to JWT means the orchestrator, CLI, and CD callers must all present a user token). Tier-B sidesteps the account risk but moves the user-enforcement boundary into our own Lambda code — weaker and less convincing. We accept the native risk **but gate it behind a spike** and keep Tier-B as a Snowflake-only fallback.
- **Ontology-driven vs hardcoded.** The ontology centralizes the policy and lets every agent inherit it, at the cost of a schema + governance change and tighter build/CD coupling. Mitigated because the `classification` field and an empty `governance.yaml` (with `classifications`, `roles`, `actionPolicies`, `objectPolicies`) already exist — we are filling a reserved slot, not inventing a concept.
- **WIF.** Not a substitute for impersonation; complementary secretless transport for the Tier-0 path.

## Consequences

**Becomes easier**
- Per-user accountability and least-privilege intersection, enforced by the systems of record.
- One place (the ontology) declares privilege; new actions inherit the policy automatically.
- Cedar policies and Gateway target wiring can be **generated** from the same ontology classification.
- Static shared API keys are removed from the outbound path.

**Becomes harder / new burden**
- Must stand up an IdP (**Microsoft Entra ID**) and JWT inbound auth; the CLI/CD callers must present user tokens (the CD pipeline was built for this; the former `bedrock-demo-orchestrator` was since archived and its ops absorbed into `bedrock-demo-infra`).
- Snowflake users must exist and be mapped to the token claim (SCIM/auto-provisioning recommended).
- The SAP SAML signing key becomes an **impersonate-anyone** secret — guard it at least as tightly as the Snowflake key.
- Two credential paths to maintain; the ontology schema + governance become security-relevant (PR gating, audit).

**Will need to revisit**
- If External OAuth fails in-account → fall back to Tier-B for Snowflake only (SAP + Gateway/Cedar still go native).
- Refresh-token TTL and re-consent policy (see Operational Notes); whether to derive action authority from data classification vs declare it explicitly.

## Operational Notes (verified)

**Consent & token caching (the "don't re-authenticate every call" answer).** AgentCore Identity caches outbound tokens in a KMS-encrypted **Token Vault**, keyed by **(agent workload identity × user id × provider)**. For 3LO `USER_FEDERATION`, the first call surfaces an authorization URL via the `@requires_access_token` `on_auth_url` callback; the user consents **once**; subsequent calls return the cached token. When the access token (~1–2 h) expires, AgentCore silently uses the stored **refresh token** (~30 d default) — "if a valid refresh token is stored, AgentCore skips the user federation flow." Re-prompt occurs only when the refresh token expires/is revoked, scopes change, or `force_authentication=True`. The **OBO exchange path we chose is silent** — no per-resource consent screen. Inbound authentication (WHO, the IdP/SSO session) and outbound authorization (WHAT) are separate layers; SSO means the consent screen, when shown, reuses the live IdP session (click "Allow", no credential re-entry — an OIDC property, not AgentCore's).

**Testability.** The AWS console interactive test / `boto3.invoke_agent_runtime` **cannot** exercise this — invokes run as the operator's SigV4 identity, with no field for a user bearer token. Test instead by minting an **Entra** user token and invoking with `Authorization: Bearer`: (a) the runtime's `CUSTOM_JWT` authorizer trusts the Entra discovery URL + the agent-app audience (`api://<agent-app>`, v1 token); (b) mint a test bearer token from Entra — auth-code + loopback listener, or ROPC for a headless test user (see `../playbooks/entra-obo-setup.md`); (c) invoke via a raw HTTPS POST to the runtime's `/invocations`, or run `make status`, which mints a ROPC user token and invokes the live CUSTOM_JWT runtime end-to-end. (There is a SigV4-compatible `X-Amzn-Bedrock-AgentCore-Runtime-User-Id` header, but AWS flags it as *unverified* — not the production intersection path.)

**Per-action authorization placement.** AgentCore has **no built-in interactive per-tool-call approval**; the only native per-tool gate is automatic Cedar policy (authorization, not an interactive human gate). The "authorize every time, unless always-allow" behavior is an **application-layer** concern — implement it in the agent (e.g. a Strands `BeforeToolInvocation` hook / MCP elicitation), driven by the ontology `authority` flag, with a remembered "always allow for this session". This is UX/governance; the security boundary remains Cedar (agent) ∩ Snowflake/SAP RBAC (user).

**Snowflake data tiering.** A single table can carry role-branching **row-access** + **masking** policies that test `CURRENT_ROLE()` / `IS_ROLE_IN_SESSION()`: the agent's service role (`AGENT_RO`) sees the broad/public tier, while a per-user External OAuth OBO session sees the restricted tier. Same SQL, different identity → different rows — the tier is enforced by the data layer, not branching code. Broad (Tier-0) tools keep the `KEYPAIR_JWT`/service path unchanged; restricted (Tier-1) tools require the inbound JWT + OBO.

## Risks

1. **External OAuth in this account (highest).** The entire Tier-1 path depends on it; SSO and PAT already fail here. **Mitigation:** the gating spike (Action Item 1).
2. **SigV4→JWT blast radius.** Every runtime caller must present a user token. **Mitigation:** stage the inbound change (Action Item 3) before flipping outbound.
3. **SAP SAML signing key.** Impersonate-anyone authority. **Mitigation:** Secrets Manager + scoped access; prefer an IdP-issued assertion over self-minting if feasible.
4. **Ontology/CD coupling.** Privilege now ships via the knowledge→agent cascade. **Mitigation:** pin per release (already the case); fail-fast coverage check (Action Item 6).

## Action Items

1. [x] **Spike (gating) — done.** Snowflake `EXTERNAL_OAUTH` (AZURE) integration proven end-to-end with Entra: a SQL REST call with `X-Snowflake-Authorization-Token-Type: OAUTH` runs as the mapped Snowflake user. Native (Option C) chosen.
2. [x] **Ontology — done.** `authority` added to the ontology schema; actions classified; the default derived in `build/validate.py`; `governance.yaml` populated.
3. [x] **Done.** Stood up **Microsoft Entra ID** (not Cognito); added `CUSTOM_JWT` inbound on the runtime; allowlisted `Authorization`; threaded the user identity through `../../../agent/src/order_triage/runtime.py`.
4. [x] **Done.** Gateway flipped to `CUSTOM_JWT` (`terraform/gateway.tf`); `policy.tf` rewritten to `OAuthUser` with the Cedar guard `principal.hasTag("scp")`; the agent path pinned at the IAM/source layer.
5. [x] **Snowflake done; SAP deferred.** OBO is now brokered by the **Gateway** (the snowflake target's `grant_type=TOKEN_EXCHANGE` egress in `terraform/snowflake_lambda.tf`), not in-agent. Snowflake External OAuth is live. SAP SAML-bearer OBO is **not yet wired** (open follow-up).
6. [~] **Superseded by the gateway-only design.** Credential routing moved out of the agent: the Gateway brokers OBO per target and Cedar authorizes, so the agent no longer maps `action → credential path`. `ACTION_IMPLEMENTATIONS` + `_assert_action_coverage()` remain in the agent as the skill→tool coverage gate.
7. [ ] **Fast-follow (open):** adopt Snowflake WIF for the Tier-0 service path (secretless; retire the key-pair).
8. [x] **Done (re-shaped).** The CD pipeline presents user tokens to the JWT-inbound runtime; the former `bedrock-demo-orchestrator` was archived and its deploy/ops absorbed into `bedrock-demo-infra`.

## References

- AWS Bedrock AgentCore: inbound JWT authorizer, runtime OAuth, on-behalf-of token exchange, identity authentication / token vault, runtime header allowlist.
- Snowflake: External OAuth security integration, OAuth scopes / `session:role:`, row-access & masking policies, Workload Identity Federation, SQL REST API authentication.
- SAP: OAuth 2.0 SAML Bearer Assertion (RFC 7522) / principal propagation.
- Internal: memory `user-impersonation-obo-design`, `snowflake-data-path`, `knowledge-repo-enterprise-scope`.

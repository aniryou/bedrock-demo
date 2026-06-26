# ADR-0008: Snowflake data tool → Cortex Analyst over a semantic view (SPIKE Option A)

**Status:** Accepted — implemented across `bedrock-demo-stubs` (the `snowflake_stub` `/ask` proxy),
`bedrock-demo-infra` (`snowflake/semantic_view.sql`, `policy.tf`), and the `order-triage-agent` tool
docstrings. **Not yet live-verified** against the deployed account (the stack is currently torn down;
`make redeploy` restores it). The semantic-view DDL and the Cortex Analyst REST contract must be
validated against the live Snowflake account on first apply (see Action items).
**Date:** 2026-06-24
**Deciders:** Anil Choudhary (proposer); platform + security owners
**Related:** the research spike [`../research/snowflake-semantic-views-spike.md`](../research/snowflake-semantic-views-spike.md)
(Option A is implemented here), [ADR-0001](0001-user-impersonation-obo.md) (the Gateway-brokered OBO
`TOKEN_EXCHANGE` this tool rides on — unchanged), [ADR-0006](0006-gateway-role-least-privilege.md)
(the Gateway role that brokers it), `policy.tf` (the Cedar policy collapsed here), and the
`order-triage-knowledge` ADR-0001 (why the ontology is intentionally *not* re-pointed — see D5).

## Context

The agent's Snowflake tool answered exactly **four canned questions** — `getOrders`, `getOrder`,
`listCustomers`, `getCustomer` — backed by hand-written parameterized SQL templates in
`snowflake_stub/snowflake_client.py`. Every new question meant new Lambda code + a new OpenAPI op +
a redeploy, and aggregations/trends ("total open order value by region for enterprise customers")
were impossible. The agent has **zero schema knowledge** by design; the four ops *are* the schema.

A **semantic view** (`CREATE SEMANTIC VIEW`, GA) encodes the business model — logical tables,
relationships, facts, dimensions, metrics, synonyms — as a schema-level Snowflake object. Paired with
**Cortex Analyst** (`POST /api/v2/cortex/analyst/message`, which *generates* SQL but does not run it),
it turns the tool from four lookups into open-ended **governed** analytics with **no Lambda code per
question**. The control plane we already validated — Gateway (Cedar) → OpenAPI target → Lambda →
Entra-OBO `TOKEN_EXCHANGE` → Snowflake RLS/RBAC — is untouched: the **same OBO bearer** that already
reaches the SQL API also reaches Cortex Analyst, so per-user row security is preserved by construction.

## Decision

Implement **SPIKE Option A**: keep the entire control plane and replace only the Lambda's fixed SQL
with a thin `ask → Cortex Analyst (generate SQL) → execute under the user's OBO token → return rows`
proxy.

**D1 — One agent tool, `ask`.** `snowflake_stub` exposes a single `POST /ask {question}` op
(`operationId: ask` → MCP tool `snowflake___ask`). The Lambda calls Cortex Analyst against
`ORDER_TRIAGE_DB.PUBLIC.ORDERS_SV`, then executes the generated SQL via the existing
`snowflake_client.query()` (reused verbatim) under the same token. The four GET ops and their SQL
templates are deleted.

**D2 — `ask` is OBO-only; no service fallback.** An analyst query must be attributable to a human for
RLS to mean anything, so `/ask` requires the forwarded user bearer and returns **401** without one
(`X-API-Key` is not accepted on `/ask`). Cortex Analyst and the generated SQL both run with token-type
`OAUTH`, so the row-access policy on `ORDERS.region` scopes the result per user (`ANIL_ENTRA` → Europe,
`JINCE_ENTRA` → Asia). No role is sent — the user's grants decide.

**D3 — Cedar shifts from per-op gating to tool-level gating.** `policy.tf`'s `permit_snowflake_read`
(four actions) becomes `permit_snowflake_ask` (one action, `snowflake___ask`). Cedar now answers "may
this principal use the Snowflake analytics tool at all" (still `principal.hasTag("scp")`);
**fine-grained row/column governance moves into the semantic view + Snowflake RLS/RBAC.** This is an
intentional authorization-architecture shift: Cedar is no longer the row/column boundary for Snowflake
data — Snowflake is, under the user's identity.

**D4 — A narrow service-path status read survives, off the agent surface.** `order_actions_stub`
enforces its OPEN-only flag rule by reading one order's status server-to-server (no user in the loop).
That dependency keeps a single `GET /orders/{id}` route on the key-pair `AGENT_RO` service path —
**deliberately excluded from `openapi.json`** so the Gateway never surfaces it as an agent tool. So
"drop the service fallback" (D2) applies to the *analytics* tool; the service path lives on only for
this internal contract.

**D5 — The enterprise ontology is intentionally NOT re-pointed.** The SPIKE's Phase 4 suggested setting
the ontology `datasourceKind` to `snowflake_semantic_view`. We did **not** do this: in
`order-triage-knowledge`, `SalesOrder` is `backing: { datasource: sap }` (the enterprise system of
record) and `classification: confidential`, and that repo's ADR-0001 is explicit that the ontology
declares the **what** (classification — which already routes order reads to user-authority/OBO), never
the **how** (the runtime backing), and that `datasource` is "source-of-truth, **not a runtime table**".
The demo's Snowflake/semantic-view is the consumer's runtime binding, not the enterprise SoR; re-pointing
it would corrupt the enterprise model. The migration is already correctly anticipated by the ontology —
via `classification`, not via the datasource.

## Options considered

- **A — Cortex Analyst behind the existing Lambda/Gateway (CHOSEN).** Lowest risk; reuses the validated
  auth/Cedar/observability wiring; auth is "free" (same bearer hits both Snowflake REST endpoints).
- **B — Snowflake-managed MCP server as a native Gateway target.** Strategic end-state (deletes the
  Lambda + OpenAPI), but blocked on reconciling its OAuth model (`OAUTH_CLIENT=CUSTOM`, `DEFAULT_ROLE`
  only) with our Entra External-OAuth + Gateway OBO egress. Deferred to a follow-up spike.
- **C — Agent calls Cortex Analyst directly.** Rejected: bypasses Gateway/Cedar, discards the repo's
  authorization thesis.

## Consequences

- New, non-trivial cost vs ~$0 today: Cortex Analyst bills ~0.067 credits/message (~$0.13–0.15/question)
  **plus** warehouse compute to run the SQL. CloudWatch token plumbing does **not** capture this
  (it is Snowflake-side) — cost visibility needs `CORTEX_ANALYST_USAGE_HISTORY` / account usage views.
  Fold a line item into `../research/finops-spike.md`.
- Latency: two REST round trips (generate + execute) vs one fixed query.
- Accuracy is now probabilistic (NL→SQL). Mitigate with tight synonyms/comments in the view, a Cortex
  Analyst verified-query repository, and an eval set wired into the AgentCore online Evaluations harness
  — do not rely on `/ask` for a demo path without an eval set.
- The semantic-view DDL becomes an owned infra artifact (`snowflake/semantic_view.sql`), applied with
  the other post-`setup.sql` scripts via `make apply-sql` and subject to the same drift caveats as RLS.

## Risks & open questions

1. **Cortex Analyst must accept the Entra External-OAuth bearer** at `/api/v2/cortex/analyst/message`
   (expected — standard Cortex REST endpoint, same token type the SQL API already accepts). Confirm live.
2. **Cross-region inference.** The account is ap-southeast-1; Cortex Analyst's LLM likely needs
   `CORTEX_ENABLED_CROSS_REGION` (`AWS_APJ` → ap-northeast-1, or `ANY_REGION`). Account-wide setting with
   data-egress implications — confirm + accept before relying on `/ask`. Left commented in
   `semantic_view.sql`.
3. **`CREATE SEMANTIC VIEW` grammar is exact.** The DDL is modelled on the SPIKE's illustrative form;
   validate against the live account on first apply (column/clause errors are reported precisely).
4. **Cedar granularity loss** (D3) — accepted and recorded.
5. **`CUSTOMERS` is unpoliced, so the per-user RLS guarantee is partial (highest open item).** The
   row-access policy (`rls.sql`) is keyed on `ORDERS.region` only; `CUSTOMERS` is deliberately master
   data with no policy. `ORDERS_SV` exposes `CUSTOMERS` as a first-class logical table (name, tier,
   `credit_limit`, region), so Cortex Analyst can emit a customers-only query and a region-scoped user
   would see all customers' attributes (including `credit_limit`). The `/ask` tool description and these
   docs were corrected to scope the guarantee to **order rows** (not customer master data). To make the
   guarantee total, either (a) add a region row-access policy to `CUSTOMERS` (note the vocabulary
   mismatch: customers use `NA/EU/APAC`, orders/entitlements use `Asia/Africa/Europe/NA` — the policy
   must normalize), or (b) drop `credit_limit` + the standalone customer dimensions from the view so
   customer attributes are only reachable through an RLS-filtered order join. **Decision owner: data
   governance** — left as a follow-up; the prior fixed-SQL design also returned customer data broadly,
   so this is a clarified-and-bounded existing posture, not a new leak.
6. **The snowflake Function URL is `AuthType=NONE` and the stub does not validate the inbound JWT**
   (it forwards the bearer to Snowflake, which validates it). This predates this migration — the OBO
   `TOKEN_EXCHANGE` egress occupies the target's single credential slot, so the URL can't also be
   `AWS_IAM` without rework, and the old `_authorize` likewise forwarded the token unvalidated. It means
   Gateway/Cedar are not in the enforcement path for a *direct* caller of the Function URL; the residual
   boundary is Snowflake's own token validation + the user's RBAC/RLS. Defense-in-depth follow-up
   (IAM-front the URL, or validate `aud`/`iss`/`exp` before forwarding) — out of scope for the data-tool
   migration; the analysis + decision now live in [ADR-0009](0009-snowflake-function-url-direct-call-hardening.md)
   (hardening **deferred**: option a — IAM-front — is rejected as it would reverse the Gateway-brokered
   OBO; option b — validate the JWT — is the chosen shape if a revisit trigger fires).

## Review findings folded in

An adversarial multi-agent review of this change confirmed and the implementation now handles: the SQL
API's **async (HTTP 202)** path (`query()` polls the statement handle rather than silently returning
zero rows), **partitioned results** (additional partitions are fetched and concatenated), and **HTTP
errors** (`SnowflakeError` carries Snowflake's message; `/ask` maps it to a 502, and `ask()` degrades
to empty rows + an `explanation` when the generated SQL fails to execute). The two governance items
above (#5, #6) were surfaced by the same review and are recorded rather than silently changed.

## Action items

- [ ] Apply `snowflake/semantic_view.sql` after `setup.sql`:
      `make apply-sql FILES="snowflake/rls.sql snowflake/semantic_view.sql snowflake/test_user.sql"`;
      fix any DDL grammar errors the live account reports.
- [ ] Decide + enable `CORTEX_ENABLED_CROSS_REGION` (uncomment in `semantic_view.sql` or set out-of-band).
- [ ] Build an eval question set + expected-rows fixtures; wire into online Evaluations.
- [ ] Add a Cortex cost line item to `../research/finops-spike.md` + a Snowflake usage-view dashboard.
- [ ] **Governance decision (#5):** add a `CUSTOMERS` region row-access policy (with the
      `NA/EU/APAC` → `Asia/Africa/Europe/NA` normalization) **or** narrow `ORDERS_SV` so customer
      attributes are only reachable via an RLS-filtered order join — or accept customers as broadly
      readable master data and keep the corrected wording.
- [ ] **Defense-in-depth (#6):** IAM-front the snowflake Function URL or validate `aud`/`iss`/`exp`
      in `_user_token` before forwarding (pre-existing) — **decision recorded in
      [ADR-0009](0009-snowflake-function-url-direct-call-hardening.md): deferred** (revisit triggers there).
- [ ] Spike Option B (managed MCP server) once its OAuth model is confirmed against Entra External OAuth.

## References

- [`../research/snowflake-semantic-views-spike.md`](../research/snowflake-semantic-views-spike.md) — the research spike (Option A).
- [Cortex Analyst REST API](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api)
- [CREATE SEMANTIC VIEW](https://docs.snowflake.com/en/sql-reference/sql/create-semantic-view)
- [Cross-region inference](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cross-region-inference)

# Spike — Snowflake Semantic Views + Cortex Analyst: replacing the current Snowflake integration

**Status:** Research spike (no code changed) · **Date:** 2026-06-24 · **Author:** anil_choudhary@mckinsey.com

---

## 1. TL;DR / recommendation

The current Snowflake path is **text → fixed OpenAPI ops → hand-written parameterized SQL** in the
`snowflake_stub` Lambda. It can answer exactly four canned questions (`getOrders`, `getOrder`,
`listCustomers`, `getCustomer`). Every new question = new Lambda code + a new OpenAPI op.

A **Semantic View** is a GA, schema-level Snowflake object that encodes the business model (logical
tables, relationships, facts, dimensions, metrics, synonyms). It is consumed three ways: by **Cortex
Analyst** (natural-language → SQL via REST), by BI tools, and by direct SQL (`SEMANTIC_VIEW(...)`).
Pairing a semantic view with Cortex Analyst turns the agent's Snowflake tool from "4 canned lookups"
into **open-ended governed analytics** ("total open order value by region for enterprise customers")
with **no Lambda code per question**.

**Recommended migration — Option A (lowest risk):** keep the entire validated AgentCore control plane
(Gateway MCP → OpenAPI target → Lambda → Entra-OBO → RLS/RBAC) and replace only the Lambda's *fixed
SQL* with a thin **ask → Cortex Analyst (generate SQL) → execute under the user's OBO token → return
rows** proxy. The hard-won auth/Cedar/observability wiring is untouched, and the **same Entra OBO
bearer token already in the request reaches both Cortex Analyst and the SQL API** — so per-user
RLS/RBAC is preserved by construction. The ontology schema already lists `snowflake_semantic_view` as
a valid `datasourceKind`, so this migration was anticipated by design.

**Strategic end-state — Option B (evaluate next):** retire the Lambda entirely in favour of the
**Snowflake-managed MCP server** (`CREATE MCP SERVER` exposing a `CORTEX_ANALYST_MESSAGE` tool) as a
native Gateway MCP target. Blocked on one open question: reconciling the managed MCP server's OAuth
model with our existing Entra **External OAuth** integration and AgentCore Gateway OBO egress (see §10).

---

## 2. What a Semantic View is

`CREATE SEMANTIC VIEW` is a **schema-level object** (GA, not preview) that stores business semantics
in the database. Components:

| Component | Meaning |
|---|---|
| **Logical tables** (`TABLES`) | Business entities (orders, customers) mapped to physical tables/views; carry PK/unique constraints, synonyms, comments. |
| **Relationships** (`RELATIONSHIPS`) | Joins between logical tables on shared keys (incl. ASOF / range joins). |
| **Facts** (`FACTS`) | Row-level numeric attributes (e.g. `amount`); building blocks for metrics. |
| **Dimensions** (`DIMENSIONS`) | Categorical/grouping attributes — who/what/where/when (status, region, tier, date). |
| **Metrics** (`METRICS`) | Aggregations over facts (`SUM`, `AVG`, `COUNT`, window/semi-additive). |
| **Synonyms / comments** | Documentation + NL aliases that help Cortex Analyst map language → model. |

DDL skeleton:

```sql
CREATE OR REPLACE SEMANTIC VIEW <name>
  TABLES        ( logicalTable [, ...] )
  RELATIONSHIPS ( relationshipDef [, ...] )
  FACTS         ( factExpr [, ...] )
  DIMENSIONS    ( dimensionExpr [, ...] )
  METRICS       ( metricExpr [, ...] )
  [ COMMENT = '...' ] [ AI_SQL_GENERATION '...' ] [ COPY GRANTS ];
```

Authoring privileges: `CREATE SEMANTIC VIEW` on the schema + `SELECT` on every underlying table/view.
The creating role owns the view. Consumers need `SELECT` **on the semantic view** to query it (and
that's exactly the grant Cortex Analyst checks).

Semantic Views are the **recommended** replacement for legacy YAML "semantic model" files — they live
in the database, get full RBAC/governance/sharing, and support derived/multi-table metrics. (Legacy
YAML on a stage still works and is accepted by the same APIs.)

## 3. How a semantic view is consumed (3 paths)

1. **Cortex Analyst REST API** — `POST /api/v2/cortex/analyst/message`. Body takes `semantic_view`
   (fully-qualified name) **or** `semantic_model_file` (stage YAML) **or** `semantic_models[]` (let
   Analyst pick), plus `messages` (the NL question) and `stream`. **It returns SQL (and suggestions),
   it does not execute it** — you run the returned `statement` yourself (this is the key integration
   fact for us). Auth via `Authorization` header + `X-Snowflake-Authorization-Token-Type`
   (OAuth / key-pair JWT / PAT). **Generated SQL runs in the caller's security context** → RBAC,
   row-access policies, and masking all apply automatically.
2. **Snowflake-managed MCP server** — `CREATE MCP SERVER ... FROM SPECIFICATION $$ <yaml> $$` exposing
   a `CORTEX_ANALYST_MESSAGE` tool over the semantic view. Standard MCP over HTTPS (JSON-RPC 2.0, MCP
   revision `2025-11-25`) at
   `https://<account>/api/v2/databases/{db}/schemas/{schema}/mcp-servers/{name}`.
3. **Direct SQL** — `SELECT ... FROM SEMANTIC_VIEW(<name> DIMENSIONS ... METRICS ...)` for
   deterministic, code-defined queries (no LLM).

## 4. What we'd be replacing (current state, verified in repo)

Path today (Gateway-brokered, live & validated 2026-06-22):

```
agent → AgentCore Gateway (MCP, Cedar hasTag("scp")) → Snowflake OpenAPI target
      → snowflake_stub Lambda (FastAPI) → snowflake_client.query() → Snowflake SQL REST API
```

- **SQL is NOT LLM-generated.** `snowflake_stub/snowflake_client.py` holds a static `_ORDER_SELECT`
  template and builds `WHERE` clauses from validated filter params as `?` bindings. The agent system
  prompt has **zero schema knowledge**; the tool surface is 4 fixed ops.
- **Data model:** `ORDER_TRIAGE_DB.PUBLIC.ORDERS` + `CUSTOMERS`, warehouse `ORDER_TRIAGE_WH`
  (account `GA20262`, ap-southeast-1). 12 seed orders / 6 customers.
- **Auth (dual-path):** (a) **OBO** — Gateway TOKEN_EXCHANGE mints an Entra OAuth token, injected as
  `Bearer`; Lambda forwards it to Snowflake as `token_type=OAUTH`; Snowflake's External-OAuth
  integration maps `upn` → `LOGIN_NAME` and enforces RLS. (b) **Service** — key-pair JWT as
  `SVC_ORDER_TRIAGE` / `AGENT_RO` for non-user reads.
- **Governance:** row-access policy on `ORDERS.region` (e.g. `ANIL_ENTRA`→Europe, `JINCE_ENTRA`→Asia);
  Cedar gates the Gateway action; Snowflake RLS/RBAC is the final boundary.

Key files: [snowflake_client.py](../../../stubs/snowflake_stub/snowflake_client.py),
[app.py](../../../stubs/snowflake_stub/app.py),
[openapi.json](../../../stubs/snowflake_stub/openapi.json),
[setup.sql](../../snowflake/setup.sql),
[rls.sql](../../snowflake/rls.sql),
[gateway.tf](../../terraform/gateway.tf),
[identity.tf](../../terraform/identity.tf),
[ontology.schema.json](../../../knowledge/schema/ontology.schema.json) (already allows
`snowflake_semantic_view`).

## 5. Why migrate (the business case)

| Today (fixed SQL) | With Semantic View + Cortex Analyst |
|---|---|
| 4 canned lookups; new question ⇒ new Lambda code + OpenAPI op + redeploy | Any question the model supports; **zero code per question** |
| No aggregations / trends ("total open value by region for enterprise tier" impossible) | Governed metrics & group-bys out of the box |
| Business logic scattered in Python `WHERE`-builders | Business logic centralised, versioned, ownable in one DB object |
| Schema knowledge nowhere (agent blind) | Semantic layer is the single source of truth, reusable by BI too |

If the demo's narrative is "an analyst asks the agent business questions," the fixed-SQL design is the
ceiling. Semantic Views raise it without weakening governance.

## 6. Target architecture options

### Option A — Cortex Analyst behind the existing Lambda/Gateway (RECOMMENDED)

Keep Gateway, OpenAPI target, Cedar, OBO egress, observability. Change only the Lambda:

```
agent → Gateway (Cedar) → OpenAPI target → Lambda:
   POST /ask {question}
     1. call /api/v2/cortex/analyst/message  (semantic_view=ORDER_TRIAGE_DB.PUBLIC.ORDERS_SV,
                                               Bearer = the OBO token already in hand)  → SQL
     2. execute that SQL via /api/v2/statements (same OBO token → user's RLS/RBAC)        → rows
     3. return {sql, rows, explanation}
```

- **Lowest risk:** the validated control plane (Cedar `hasTag("scp")`, OBO TOKEN_EXCHANGE,
  CloudWatch GenAI traces) is untouched.
- **Auth is essentially free:** the same Entra OBO bearer reaches *both* Snowflake REST endpoints;
  no new identity provider, no new mapping. (Reuses the exact `upn`→`LOGIN_NAME` mapping from the
  `snowflake-obo-user-mapping` finding.)
- `snowflake_client.query()` is reused verbatim for step 2; `_ORDER_SELECT` templates are deleted.
- The service key-pair path can stay for any non-user reads, or be **dropped** for the analyst tool
  (simplification — see §10) since the analyst flow should always run as the user for RLS.

### Option B — Snowflake-managed MCP server as a native Gateway target (strategic)

`CREATE MCP SERVER` with a `CORTEX_ANALYST_MESSAGE` tool over the semantic view; register its
`/api/v2/.../mcp-servers/<name>` endpoint as an **MCP target** on AgentCore Gateway. **Deletes the
Lambda + OpenAPI spec entirely.** Native, less code to own.

Friction / unknowns: the managed MCP server documents an OAuth 2.0 model using a **Snowflake** OAuth
security integration (`OAUTH_CLIENT=CUSTOM`) and the connecting user's `DEFAULT_ROLE` (no secondary
roles; PATs discouraged). We must confirm it accepts our **External OAuth (Entra)** bearer via the
Gateway OBO egress, or accept a second integration. Limits: 50 tools/server, 250 KB response cap on
SQL/analyst tools, non-streaming, recursion depth 10, no MCP resources/prompts/roots/sampling.

### Option C — Agent calls Cortex Analyst directly (NOT recommended)

Bypasses Gateway/Cedar. Discards the repo's entire authz thesis. Rejected.

**Decision:** ship **A** now; spike **B** as a follow-up once its OAuth model is confirmed against
Entra External OAuth.

## 7. Concrete semantic view for our model (illustrative — validate against `CREATE SEMANTIC VIEW`)

```sql
CREATE OR REPLACE SEMANTIC VIEW ORDER_TRIAGE_DB.PUBLIC.ORDERS_SV
  TABLES (
    orders    AS ORDER_TRIAGE_DB.PUBLIC.ORDERS    PRIMARY KEY (order_id)
              WITH SYNONYMS ('sales orders','tickets') COMMENT = 'Customer orders to triage',
    customers AS ORDER_TRIAGE_DB.PUBLIC.CUSTOMERS  PRIMARY KEY (customer_id)
              WITH SYNONYMS ('accounts','clients')   COMMENT = 'Customer accounts'
  )
  RELATIONSHIPS (
    order_customer AS orders (customer_id) REFERENCES customers (customer_id)
  )
  FACTS (
    orders.amount           AS orders.amount,
    customers.credit_limit  AS customers.credit_limit
  )
  DIMENSIONS (
    orders.status     AS orders.status      WITH SYNONYMS ('order state'),
    orders.channel    AS orders.channel,
    orders.region     AS orders.region,
    orders.created_at AS orders.created_at  WITH SYNONYMS ('order date'),
    customers.tier    AS customers.tier     WITH SYNONYMS ('segment'),
    customers.name    AS customers.name
  )
  METRICS (
    orders.total_amount     AS SUM(orders.amount)   WITH SYNONYMS ('order value','revenue'),
    orders.order_count      AS COUNT(orders.order_id),
    orders.avg_order_value  AS AVG(orders.amount)
  )
  COMMENT = 'Order-triage semantic model for Cortex Analyst';
```

This single object lets Cortex Analyst answer e.g. *"total open order value by region for enterprise
customers in the last 90 days"* — impossible with today's fixed templates — while `ORDERS.region`
RLS still scopes rows per OBO user. Lives next to `setup.sql`/`rls.sql` and is bootstrapped the same
way.

## 8. Auth & governance impact

- **OBO / RLS:** preserved with **zero new auth plumbing** in Option A — same bearer hits Analyst +
  SQL APIs; Snowflake runs generated SQL in the user's context so RLS/RBAC/masking auto-apply.
- **Cedar:** today Cedar gates four discrete Snowflake actions. After migration the agent has one
  `ask` action, so Cedar's role shifts from *per-operation* gating to *"may this principal use the
  Snowflake analytics tool at all"* (still `hasTag("scp")`); **fine-grained row/column governance
  moves into the semantic view + Snowflake RLS/RBAC.** This is an intentional authz-architecture
  shift — document it (ADR) so reviewers know Cedar is no longer the column/row boundary here.
- **Read-only safety:** LLM-generated SQL executes under a SELECT-only role (`AGENT_RO` / the OBO
  user's grants) + RLS, so blast radius is bounded by Snowflake grants. Option B's
  `SYSTEM_EXECUTE_SQL` can additionally enforce read-only at the tool level.

## 9. Cost (FinOps)

New, non-trivial cost vs ~$0 today:

- **Cortex Analyst:** message-based — **~6.7 credits / 100 messages (~0.067 credits/message)**; only
  HTTP 200 responses bill; cost is flat regardless of tokens. Standalone API billed per 1,000
  messages. Invoked **via Cortex Agents** instead, it switches to the token-based AI-Credit model.
- **AI credits** priced ~**$2.00 (global) / $2.20 (regional)** per credit on-demand (no capacity
  discount) → order-of-magnitude **~$0.13–0.15 per question** for generation, **plus warehouse
  compute** to execute the returned SQL. Confirm exact credit *type* and account rate.
- **Action:** fold into [FINOPS-SPIKE.md](finops-spike.md) — add a Cortex line item; the existing
  `requestMetadata`/EMF token plumbing won't capture Cortex message cost (that's Snowflake-side), so
  cost visibility needs Snowflake `CORTEX_ANALYST_USAGE_HISTORY` / account usage views, not just
  CloudWatch.

## 10. Risks & open questions

1. **Accuracy / determinism (highest).** NL→SQL can be wrong. Mitigate with Cortex Analyst's
   **verified query repository (VQR)**, tight synonyms/comments in the view, and wiring questions
   into the **existing AgentCore online Evaluations** harness (see `observability-spike`). Don't ship
   without an eval set.
2. **Regional availability.** Account is ap-southeast-1; Cortex Analyst likely needs
   **cross-region inference** enabled (`CORTEX_ENABLED_CROSS_REGION = AWS_APJ` or `ANY_REGION`;
   APJ routes to ap-northeast-1). Confirm + accept data-egress/region implications **before** build.
3. **Option B OAuth reconciliation.** Does the managed MCP server accept our Entra **External OAuth**
   bearer (vs requiring its own Snowflake `OAUTH_CLIENT=CUSTOM` integration)? Needs a POC. Also
   `DEFAULT_ROLE`-only / no secondary roles may not fit our role model.
4. **Latency.** Two REST round trips (generate + execute) vs one fixed query today.
5. **Cedar granularity loss** (see §8) — accept and document.
6. **Service-path simplification.** With analyst-as-user, the key-pair `AGENT_RO` path may become
   dead for Snowflake; decide whether to keep it for non-user reads or remove it.
7. **Maintenance.** The semantic view DDL becomes an owned infra artifact (bootstrap + drift); add to
   `snowflake_bootstrap.py`.

## 11. Migration plan (Option A)

| Phase | Work | Files |
|---|---|---|
| 0. Prereqs | Enable cross-region inference; confirm credit rate; create eval question set | account params; eval harness |
| 1. Semantic view | Author + bootstrap `ORDERS_SV`; grant `SELECT` to OBO users + `AGENT_RO` | new `snowflake/semantic_view.sql`, `scripts/snowflake_bootstrap.py` |
| 2. Lambda proxy | Replace fixed-SQL ops with `POST /ask`: Analyst-generate → execute under OBO → return | [snowflake_client.py](../../../stubs/snowflake_stub/snowflake_client.py), [app.py](../../../stubs/snowflake_stub/app.py), [openapi.json](../../../stubs/snowflake_stub/openapi.json) |
| 3. Gateway/Cedar | Re-point OpenAPI op; collapse 4 actions → 1 `ask`; keep `hasTag("scp")` | [gateway.tf](../../terraform/gateway.tf), [policy.tf](../../terraform/policy.tf) |
| 4. Agent | Update tool description so the model passes the user's NL question through; set `datasourceKind: snowflake_semantic_view` in ontology | [ontology/](../../../knowledge/ontology/), agent tool surface |
| 5. Eval + observe | Run eval set; verify RLS still scopes per user (`ANIL_ENTRA`→Europe etc.); add Cortex cost view | Evaluations, FinOps |
| 6. ADR | Record the Cedar→semantic-layer authz shift + Option-B follow-up | `docs/adr/0003-semantic-view-cortex-analyst.md` |

**Effort:** ~Option A is a few days (mostly Lambda rewrite + view authoring + eval); Option B is a
separate spike gated on the OAuth POC.

## 12. Prerequisites checklist

- [ ] Cross-region inference enabled for ap-southeast-1 / APJ (or `ANY_REGION`).
- [ ] `CREATE SEMANTIC VIEW` privilege for the bootstrap role; `SELECT` on `ORDERS`/`CUSTOMERS`.
- [ ] `SELECT` on the semantic view granted to each OBO Snowflake user + `AGENT_RO`.
- [ ] Confirmed: External-OAuth (Entra) bearer is accepted by `/api/v2/cortex/analyst/message`
      (expected — it's a standard Cortex REST endpoint).
- [ ] Eval question set + expected-rows fixtures.
- [ ] FinOps line item + Snowflake usage-view dashboard for Cortex cost.

---

## Sources

- [Overview of semantic views — Snowflake Docs](https://docs.snowflake.com/en/user-guide/views-semantic/overview)
- [CREATE SEMANTIC VIEW — Snowflake Docs](https://docs.snowflake.com/en/sql-reference/sql/create-semantic-view)
- [YAML specification for semantic views — Snowflake Docs](https://docs.snowflake.com/en/user-guide/views-semantic/semantic-view-yaml-spec)
- [SEMANTIC_VIEW construct — Snowflake Docs](https://docs.snowflake.com/en/sql-reference/constructs/semantic_view)
- [Cortex Analyst — Snowflake Docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst)
- [Cortex Analyst REST API — Snowflake Docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api)
- [Snowflake-managed MCP server — Snowflake Docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp)
- [Snowflake-Labs/mcp (Cortex AI MCP server) — GitHub](https://github.com/Snowflake-Labs/mcp)
- [Cortex Agents — Snowflake Docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents)
- [Authenticating Snowflake REST APIs — Snowflake Docs](https://docs.snowflake.com/en/developer-guide/snowflake-rest-api/authentication)
- [Configure Microsoft Entra ID for External OAuth — Snowflake Docs](https://docs.snowflake.com/en/user-guide/oauth-azure)
- [Cross-region inference — Snowflake Docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cross-region-inference)
- [Snowflake AI pricing — Snowflake Docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex/pricing)
- [Security & governance best practices for Snowflake Intelligence — Snowflake Blog](https://www.snowflake.com/en/blog/security-governance-practices-snowflake-intelligence/)
- [Cortex Analyst pricing & cost monitoring — select.dev](https://select.dev/posts/snowflake-cortex-analyst-overview-pricing-and-cost-monitoring)

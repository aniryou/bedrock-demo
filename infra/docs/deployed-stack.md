# The deployed stack — a guided console tour

This is what `make deploy` actually puts in the AWS console. The
[architecture diagrams](architecture/end-to-end.md) show the system in the abstract; this page
is the **concrete counterpart** — real screenshots of the live order-triage stack, walking each
plane in the order a request flows through it, with a link to the Terraform that created each
piece so you can jump from "what it looks like" to "what built it".

> Screenshots are from a live deploy (region **us-west-2**, model **Nova Lite**); account IDs,
> ARNs, client/tenant IDs, and the `api://` URIs are redacted. **Planes 1–7** are created by
> `terraform apply` from [`infra/terraform/`](../terraform/) — see the
> [deploy runbook](playbooks/deploy.md) to stand it up yourself. **Sections 8–9** cover the two
> systems the stack *federates with* — the Entra tenant and the Snowflake account — which are
> provisioned on their own paths (noted in each).

**The tour, plane by plane:**

1. [Runtime](#1--runtime--where-the-agent-runs) — where the agent runs
2. [Gateway](#2--gateway--the-one-door-to-the-back-office) — the one door to the back office
3. [Authorization](#3--authorization--cedar-decides-every-tool-call) — Cedar decides every tool call
4. [Memory](#4--memory--what-the-agent-remembers) — what the agent remembers
5. [Identity](#5--identity--how-the-agent-proves-who-its-acting-as) — how the agent proves who it's acting as
6. [Guardrail](#6--guardrail--the-prompt-attack-screen) — the prompt-attack screen
7. [Observability](#7--observability--watching-it-run) — watching it run

…and the two systems it federates with (provisioned outside the AWS stack):

8. [Entra](#8--entra--the-obo-app-registrations) — the OBO identity provider
9. [Snowflake](#9--snowflake--tables-rls-and-the-semantic-view) — the OBO trust, tables, RLS, semantic view

---

## 1 · Runtime — where the agent runs

The **AgentCore Runtime** is the managed home for the agent. Terraform registers the agent's
arm64 container image (built and pushed by CI to ECR) as a runtime named `order_triage`, and
gives it **endpoints** — stable addresses clients invoke without caring which image version is
behind them. Each `terraform apply` cuts a new immutable **version**; the endpoint is just
re-pointed, so callers never change. This is the box the chat client (`app/`) actually calls.

![AgentCore Runtime console — the order_triage runtime, its ARN and ECR source, two endpoints, and Version 1](images/01%20-%20runtime.png)

**Terraform:** [`runtime.tf`](../terraform/runtime.tf) — the runtime + endpoint.

---

## 2 · Gateway — the one door to the back office

The agent never holds a database credential or calls a Lambda directly. Every back-office read
and write goes through the **AgentCore Gateway**, which exposes the back-office services as MCP
tools the model can call. The gateway's headline settings: **inbound auth** is a `CUSTOM_JWT`
authorizer that only accepts tokens minted by the demo's Microsoft Entra tenant, and its
**policy engine is set to *enforce*** — so no tool call happens without an authorization
decision (that's plane 3).

![Gateway console — order-triage-gateway details, the interceptor Lambdas, the associated policy engine, and the Entra inbound-auth block](images/02%20-%20gateway.png)

Behind the gateway sit three **targets** — `orders`, `sap`, and `snowflake` — each a back-office
stub published as an OpenAPI schema. This is the list of tools the agent can reach.

![Gateway inbound-auth detail and the three targets: orders, sap, snowflake — all MCP / OpenAPI](images/03%20-%20gateway%20-%20auth.png)

**Terraform:** [`gateway.tf`](../terraform/gateway.tf) — the gateway, its inbound `CUSTOM_JWT`
authorizer, and the three targets. The backends themselves are
[`sap_lambda.tf`](../terraform/sap_lambda.tf),
[`order_actions_lambda.tf`](../terraform/order_actions_lambda.tf), and
[`snowflake_lambda.tf`](../terraform/snowflake_lambda.tf).

### The Snowflake target — reading *as the signed-in user*

The Snowflake target is the interesting one, because it's where **on-behalf-of (OBO)** happens.
Its **outbound auth** uses the `entra-obo` provider with a **token-exchange grant**: when the
agent calls this tool, the gateway swaps the user's inbound token for a per-user Snowflake token,
so the query runs under *that human's* identity — and Snowflake row-level security decides what
they're allowed to see. (Orders and SAP credit, by contrast, are read on the agent's own
identity — that split is the heart of the design, see [ADR-0001](adr/0001-user-impersonation-obo.md).)

![Snowflake target details — outbound auth via entra-obo, token-exchange grant, and the inline OpenAPI schema](images/04%20-%20gateway%20-%20target.png)

The target carries its API contract **inline** as an OpenAPI spec: a single `/ask` operation that
takes a natural-language question and returns generated SQL plus result rows. The `BearerAuth`
scheme is the OBO per-user token, and the responses spell out the `401` (missing user token) and
`502` (Snowflake error) cases.

![Inline OpenAPI schema, part 1 — the Snowflake Analytics API, BearerAuth as the OBO token, and the AskRequest schema](images/05%20-%20gateway%20-%20api%20spec%20-%201.png)

![Inline OpenAPI schema, part 2 — the AskResponse schema: question, generated SQL, result rows, row count, explanation](images/06%20-%20gateway%20-%20api%20spec%20-%202.png)

![Inline OpenAPI schema, part 3 — the /ask operation, request body, and the 200 / 401 / 502 responses](images/07%20-%20gateway%20-%20api%20spec%20-%203.png)

**Terraform:** the targets and their inline schemas live in
[`gateway.tf`](../terraform/gateway.tf); the OBO outbound-auth provider is in
[`identity.tf`](../terraform/identity.tf) (plane 5).

---

## 3 · Authorization — Cedar decides every tool call

Enforcement mode "on" (plane 2) points at a **Cedar policy engine**, `order_triage_policies`.
This is the agent's allow-list: three policies, each **verified and active**, that say which
tools the agent may call. If a tool isn't permitted, the gateway refuses — the agent can't
reach a back-office action just because it decided to.

![Policy engine console — order_triage_policies, enforced on the gateway, with three verified policies](images/08%20-%20gateway%20-%20policies%20-%201.png)

The same policies viewed from the gateway side, alongside the gateway's own live metrics
(invocations, latency, error rate) — a reminder that every one of those invocations passed a
Cedar check first.

![Associated policies on the gateway plus the gateway's observability summary](images/09%20-%20gateway%20-%20policies%20-%202.png)

Drilling into one policy, `permit_snowflake_ask`, shows the actual rule in **Cedar**: *permit*
the `OAuthUser` principal to take the `snowflake___ask` action on this gateway, **when** the
principal carries the right scope tag. Plain, auditable, and decoupled from the agent code.

![The permit_snowflake_ask policy — its Cedar source, principal, action, resource, and scope condition](images/10%20-%20gateway%20-%20policies%20-%20permissions.png)

**Terraform:** [`policy.tf`](../terraform/policy.tf) — the policy engine and the three Cedar
policies. Why least-privilege here: [ADR-0006](adr/0006-gateway-role-least-privilege.md).

---

## 4 · Memory — what the agent remembers

So the agent isn't amnesiac between turns, AgentCore **Memory** stores per-user conversation
history. Short-term memory holds raw events (expiring after 90 days); three built-in **long-term
strategies** distil those events in the background into durable, retrievable knowledge: **facts**
(semantic), **preferences** (user-preference), and **summaries** (summarization). All three show
**active** here, keyed to the signed-in user so one analyst never sees another's context.

![Memory console — order_triage_memory details and the three active long-term strategies: facts, preferences, summaries](images/11%20-%20memory.png)

Memory is observable in its own right: how often events are written, how often long-term memory
is retrieved, and how many durable memories have been extracted (9, here).

![Memory observability — create-event and retrieve metrics, plus long-term memories extracted](images/12%20-%20memory%20-%20observability.png)

**Terraform:** [`memory.tf`](../terraform/memory.tf) — the memory store and its three strategies.
Why memory is on: [ADR-0002](adr/0002-agentcore-memory-activation.md).

---

## 5 · Identity — how the agent proves who it's acting as

The OBO swap in plane 2 needs credentials, and they live in **AgentCore Identity** as **outbound
auth** providers. There are two: `entra-obo` (a Microsoft OAuth2 client, used for the
token-exchange that lets the agent act *as the user* against Snowflake) and `snowflake-api-key`
(the agent's own API key for non-OBO access). The secrets behind them sit in a KMS-encrypted
token vault — never in Terraform state.

![AgentCore Identity console — two outbound-auth providers (entra-obo OAuth client, snowflake-api-key) and the KMS token vault](images/13%20-%20identity.png)

**Terraform:** [`identity.tf`](../terraform/identity.tf) — the credential providers. The Entra
client secret is seeded out-of-band (`make seed-entra-secret`); the full OBO wiring and its traps
are in the [Entra OBO runbook](playbooks/entra-obo-setup.md).

---

## 6 · Guardrail — the prompt-attack screen

Every model turn passes through a native **Bedrock Guardrail** configured as a **prompt-attack
input filter** (on by default). It deliberately runs **no PII policy** — this agent reads
customer PII end-to-end as part of its job, so masking happens at the telemetry layer (plane 7),
not on the live path. The guardrail has no standalone console page in this tour, but you can see
its effect as the **"Guardrail interventions"** counter on the executive and governance
dashboards below.

**Terraform:** [`guardrail.tf`](../terraform/guardrail.tf) — the guardrail and its version. The
reasoning (and why no PII policy): [ADR-0003](adr/0003-bedrock-guardrail.md).

---

## 7 · Observability — watching it run

Everything the runtime does emits telemetry. The **GenAI Observability** view in CloudWatch is
the front door: a rollup across the deployed agent — sessions, traces, token totals, error and
throttle rates.

![CloudWatch GenAI Observability — the order_triage agent rollup: sessions, traces, total tokens, error and throttle rates](images/14%20-%20observability.png)

Per endpoint, you get a per-span breakdown — traces, errors, and latency for every tool call and
model turn (here, `sap___getCreditStatus` and `snowflake___ask` next to the runtime-invoke and
`chat` spans, all error-free).

![Endpoint view (order_triage.DEFAULT) — per-span traces, errors, and latency across the agent's tool calls](images/15%20-%20observability%20-%20endpoint.png)

Drill into **sessions** to see each conversation — its traces, token spend, errors, and latency.
(The `webapp-*` IDs come from the chat client; `status-check-*` is the `make status` smoke test.)

![Sessions list — recent sessions (webapp + a smoke test) with traces, tokens, errors, and average trace latency](images/16%20-%20observability%20-%20session.png)

And into a single **trace** to see the agent's actual reasoning step by step — the spans for each
tool call and the agent's own thinking, captured as `gen_ai` events. This is the same trajectory
the chat client streams to the user, here preserved for debugging.

![A single trace — spans and events showing the agent's reasoning trajectory and tool calls](images/17%20-%20observability%20-%20trace.png)

### The custom dashboards

On top of the built-in views, Terraform provisions three purpose-built CloudWatch dashboards.

**Executive rollup** — the one-screen health check: success rate, p99 latency, an estimated cost
(token × rate), guardrail interventions, agent health, and trend lines for invocations and token
usage.

![order-triage-exec dashboard — success rate, p99 latency, estimated cost, guardrail interventions, and trends](images/18%20-%20observability%20-%20dashboard%20-%20exec.png)

**FinOps** — where the tokens (and therefore the money) go: token volume in/out, estimated cost,
top actors and sessions by token spend, spend by downstream model, and the easy-to-miss cost of
long-term memory processing.

The **Top actors** table reads as real names, not opaque ids. The runtime only ever stores the
Entra directory id — a PII-free GUID — and a small Graph lookup turns that id into a display name
when the dashboard renders. The same resolution runs on the governance audit table below. (See
[ADR-0007](adr/0007-actor-resolution.md).)

![order-triage-finops dashboard, part 1 — token volume, estimated cost, and the Top actors table with identities resolved to display names](images/19%20-%20observability%20-%20dashboard%20-%20finops%20-%201.png)

![order-triage-finops dashboard, part 2 — tokens by downstream model and the hidden cost of long-term memory processing](images/20%20-%20observability%20-%20dashboard%20-%20finops%20-%202.png)

**Governance / Audit** — the compliance view: an append-only, **PII-masked** record of every
model invocation, plus guardrail interventions, **Cedar authorization decisions by tool**, and
**OBO token-exchange success vs failure** — exactly the trail you'd want when asked "who saw what,
and was it allowed?"

![order-triage-governance dashboard, part 1 — the per-turn append-only model-invocation record (PII masked, actor column resolved to display names) and guardrail interventions](images/21%20-%20observability%20-%20dashboard%20-%20governance%20-%201.png)

![order-triage-governance dashboard, part 2 — Cedar authorization decisions by tool and OBO token-exchange success vs failure](images/22%20-%20observability%20-%20dashboard%20-%20governance%20-%202.png)

![order-triage-governance dashboard, part 3 — Cedar decisions by policy engine, OBO failures by type, and Knowledge Base access latency](images/23%20-%20observability%20-%20dashboard%20-%20governance%20-%203.png)

### Alarms and SLOs

Finally, the dashboards are backed by **CloudWatch alarms** — runtime system errors, throttles,
agent-unhealthy, OBO token-exchange failures, token-usage anomalies, and service faults — that
notify via SNS when something crosses a threshold. (They only page someone once `alert_email` is
set and confirmed.) App Signals **SLOs** track the same health as service-level objectives.

![CloudWatch alarms — the seven order-triage alarms, all OK](images/24%20-%20observability%20-%20slo.png)

**Terraform:** [`observability.tf`](../terraform/observability.tf) wires in the
[`modules/observability/`](../terraform/modules/observability/) module — the dashboards
([`dashboards.tf`](../terraform/modules/observability/dashboards.tf)), alarms
([`alarms.tf`](../terraform/modules/observability/alarms.tf)), and SLOs
([`slo.tf`](../terraform/modules/observability/slo.tf)). The design and FinOps rationale:
[ADR-0004](adr/0004-observability-finops.md).

---

## 8 · Entra — the OBO app registrations

Both the gateway's inbound auth (plane 2) and the on-behalf-of token exchange trust a
**Microsoft Entra** tenant. The main deploy doesn't build any of it — Entra is set up on its own,
either as Terraform in [`infra/entra/`](../entra/) or with the `make entra-setup` script.

OBO uses the classic **three-app, middle-tier** pattern, and all three apps are registered here.
One stands in for Snowflake — the *resource*, holding no secret of its own. One is the agent
itself — the *client* that carries a secret and runs the exchange. The third is a small daemon
that turns a user-id back into a display name for the dashboards (see
[ADR-0007](adr/0007-actor-resolution.md)).

![Entra app registrations — the three order-triage apps: snowflake (resource), agent (client + secret), graph-resolver (daemon)](images/25%20-%20entra%20-%20app-registrations.png)

The agent app's **API permissions** are where the exchange is authorized. Two delegated
permissions are listed — one to read the signed-in user, one for the Snowflake scope — and both
are admin-consented (the green "Granted for Default Directory"). That consent is what lets the
agent trade a user's sign-in token for a Snowflake token carrying *that user's* role.

![Entra agent-app API permissions — delegated Graph User.Read and the snowflake session:role-any scope, both admin-consented](images/26%20-%20entra%20-%20api-permissions.png)

The matching half lives on the resource app, under **Expose an API**. It publishes a single
scope, `session:role-any`, with admin-only consent. The exact name matters — it's the carrier
Snowflake expects, and getting it wrong is one of the classic OBO traps.

![Entra resource-app Expose an API — the api:// Application ID URI and the exposed session:role-any delegated scope](images/27%20-%20entra%20-%20expose-api.png)

**Provisioned by:** [`infra/entra/main.tf`](../entra/main.tf) — the three apps, the exposed
scope, the client secret, and admin consent. The traps to watch for are in the
[Entra OBO runbook](playbooks/entra-obo-setup.md); the reasoning behind the agent-vs-user split is
[ADR-0001](adr/0001-user-impersonation-obo.md).

---

## 9 · Snowflake — tables, RLS, and the semantic view

The OBO read finally lands in **Snowflake**. As with Entra, none of it comes from the main
deploy — it's seeded from the SQL in [`infra/snowflake/`](../snowflake/) with `make
snowflake-setup`, `make snowflake-obo`, and `make apply-sql`.

Row security can't do anything until the impersonated user *becomes* a Snowflake user, so that's
where it starts. A **security integration** called `ENTRA_OBO` checks each incoming Entra token
and matches its email to a Snowflake login. The effect: the session runs as the actual person —
say, `ANIL_ENTRA` — not the agent's service account.

Two settings on it are worth a look. The **issuer** points at the *v1* token endpoint, because
Snowflake's Azure connector accepts v1 tokens and quietly rejects v2 — a favourite OBO trap. And
**any-role mode** is on, so a user's token can carry the role scope from plane 8. Privileged roles
like `ACCOUNTADMIN` are blocked from signing in this way.

![Snowflake EXTERNAL_OAUTH security integration ENTRA_OBO — v1 sts.windows.net issuer, upn/email → login_name user mapping, any-role enabled, privileged roles blocked](images/28%20-%20snowflake%20-%20security-integration.png)

With identity settled, the data is simple: three tables in one schema — the orders to triage, the
customer master data, and a table mapping each user to the regions they may see. Below are the
twelve demo orders.

![Snowflake tables — the ORDER_TRIAGE_DB.PUBLIC schema (orders, customers, user_region_access) and the 12 demo orders](images/29%20-%20snowflake%20-%20tables.png)

**Row-level security** is a single row-access policy, `orders_region_rap`, on the orders table.
It reads plainly: the agent's own service account sees every region; an impersonated person sees
only the regions listed for them. Because it sits on the base table, it applies to *every* read —
whether the agent is acting for itself or for a user.

![Snowflake row access policy orders_region_rap — service identity sees all regions; impersonated users see only their entitled region(s)](images/30%20-%20snowflake%20-%20rls.png)

Last is the **semantic view**, `ORDERS_SV` — the model **Cortex Analyst** reads to turn the
agent's plain-language question into real SQL. It names the tables, how they join, and the
dimensions and metrics to group by, each with everyday synonyms. The row-access policy still
applies underneath, so answers stay scoped per user.

![Snowflake semantic view ORDERS_SV — logical tables, relationship, facts, dimensions with synonyms, and metrics](images/31%20-%20snowflake%20-%20semantic-view.png)

**Provisioned by:** the SQL in [`infra/snowflake/`](../snowflake/) —
[`setup.sql`](../snowflake/setup.sql) (schema, seed data, role),
[`rls.sql`](../snowflake/rls.sql) (the policy), and
[`semantic_view.sql`](../snowflake/semantic_view.sql). The `ENTRA_OBO` integration is created by
`make snowflake-obo`. Reasoning: [ADR-0008](adr/0008-semantic-view-cortex-analyst.md); the token
trust: [Entra OBO runbook](playbooks/entra-obo-setup.md).

---

## Where to go next

- **The system in the abstract** — [end-to-end lifecycle](architecture/end-to-end.md) and the
  per-plane [architecture diagrams](architecture/README.md).
- **The live request at wire level** — [data-plane.md](architecture/data-plane.md).
- **Stand it up yourself** — the [deploy runbook](playbooks/deploy.md); operating brief in
  [CLAUDE.md](../CLAUDE.md).
- **The decisions behind the boxes** — the [ADRs](adr/) (OBO, memory, guardrail, observability,
  Cedar least-privilege, semantic view).

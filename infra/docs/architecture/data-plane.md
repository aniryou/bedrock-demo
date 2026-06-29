# Detailed Runtime Data Plane

The **live request / data plane**: how one `InvokeAgentRuntime` call flows from an
Entra-authenticated caller, through the AgentCore Runtime and the Cedar-guarded
Gateway, out to the stub Lambdas, and into Snowflake **as the calling human** (OBO).
The grey **Observability** band is the *control plane* (telemetry, not request flow);
build/publish/deploy is documented in the [repo README](../../../README.md) and
[`playbooks/cd-setup.md`](../playbooks/cd-setup.md), and drawn as the [DevOps / CI-CD plane](devops-architecture.md). This is the
detailed sibling of the [end-to-end lifecycle](end-to-end.md) — the hero's request spine (`R1–R7`)
at wire level, expanding the identity / Cedar / OBO / RLS chain the hero folds.

**Legend** — official AWS (+ SaaS) icons, left → right. Edges: **solid dark** =
request / data path (numbered `1…6`) · **blue dashed** = identity / token / OBO ·
**grey** = supporting (reads, telemetry). Rounded boxes group by trust / responsibility.
The diagram is generated from [`specs.json`](specs.json) by the
[`architecture-skill` skill](README.md) — edit the spec, not the SVG.

![Detailed data plane — AWS architecture](data-plane-architecture.svg)

> **See also — subsystem deep-dives.** This page is the end-to-end *data plane*. For
> per-concern detail (each a different cross-section of the same call, in the same visual
> grammar), see the [plane index](README.md): [Agent](agent-architecture.md) ·
> [Knowledge](knowledge-architecture.md) · [Security](security-architecture.md) ·
> [Memory](memory-architecture.md) · [Observability](observability-architecture.md) ·
> [Evaluation](evaluation-architecture.md).

## Wire-level view (Mermaid)

The same flow as a detailed Mermaid diagram — finer-grained than the AWS-icon SVG above
(every Entra app, credential provider and auth path spelled out), and useful where an
AWS-icon render is overkill (PR diffs, ADRs). **Colour** — blue = identity, green =
compute, red = authorization (incl. the Guardrail), amber = data store, cyan = external
Snowflake, grey = observability (control plane).

```mermaid
flowchart LR
  classDef idp fill:#e8f0fe,stroke:#3367d6,color:#1a237e;
  classDef compute fill:#e6f4ea,stroke:#137333,color:#0b5394;
  classDef authz fill:#fce8e6,stroke:#c5221f,color:#b71c1c;
  classDef data fill:#fff3e0,stroke:#e8710a,color:#5f4100;
  classDef ext fill:#e1f5fe,stroke:#0277bd,color:#01579b;
  classDef obs fill:#eceff1,stroke:#546e7a,color:#263238;

  user(["Analyst / Caller<br/>(human)"]):::idp

  subgraph ENTRA_IN["Microsoft Entra ID — inbound (CUSTOM_JWT)"]
    direction TB
    feApp["Front-end app<br/>user sign-in"]:::idp
    agentApp["Agent app<br/>aud of inbound JWT<br/>access_as_user"]:::idp
  end

  subgraph RT["Amazon Bedrock AgentCore — Runtime · us-west-2"]
    direction TB
    endpoint["Runtime Endpoint (DEFAULT)<br/>CUSTOM_JWT authorizer<br/>allowed_audience = api://agent-app"]:::compute
    agent["AgentCore Runtime<br/>order_triage · arm64 · Strands loop"]:::compute
    tools["Local tools<br/>search_policies · describe_entity · load_skill"]:::compute
    mem[("AgentCore Memory<br/>facts · prefs · summaries")]:::data
  end

  subgraph BR["Amazon Bedrock"]
    direction TB
    model["Nova Lite<br/>amazon.nova-lite-v1:0<br/>ConverseStream"]:::compute
    guard["Bedrock Guardrail<br/>PROMPT_ATTACK input filter (async)<br/>default-on · enable_guardrail"]:::authz
    kb["Knowledge Base<br/>Titan Embed Text v2"]:::compute
    s3v[("S3 Vectors index")]:::data
  end

  subgraph ENTRA_OBO["Microsoft Entra ID — OBO egress"]
    direction TB
    oboProv["entra-obo provider<br/>MicrosoftOauth2 + tenant_id"]:::idp
    sfApp["Snowflake resource app<br/>api://.../session:role-any<br/>v1 tokens (upn, scp)"]:::idp
  end

  subgraph GW["AgentCore Gateway — MCP"]
    direction TB
    gwcore["MCP endpoint<br/>OpenAPI targets: sap · orders · snowflake"]:::compute
    cedar["Cedar Policy Engine (ENFORCE)<br/>principal = AgentCore::OAuthUser<br/>guard: principal.hasTag('scp')<br/>permit_sap_read · permit_flag · permit_snowflake_ask"]:::authz
    cpKey["snowflake-api-key provider<br/>(initial placeholder)"]:::authz
    cpObo["entra-obo OAuth2 provider<br/>(swapped in for OBO)"]:::authz
  end

  subgraph LAM["AWS Lambda — arm64 · Function URLs"]
    direction TB
    saplam["SAP credit stub<br/>FN URL: AWS_IAM"]:::compute
    ordlam["order-actions stub<br/>FN URL: AWS_IAM"]:::compute
    sflam["snowflake-query stub<br/>FN URL: NONE + X-API-Key"]:::compute
  end

  sm[("Secrets Manager<br/>Snowflake RSA key + config<br/>entra-obo client secret")]:::data

  subgraph SF["Snowflake · ap-southeast-1"]
    direction TB
    sfext["EXTERNAL_OAUTH (AZURE)<br/>upn → user · scp → role"]:::ext
    sfdb[("ORDER_TRIAGE_DB<br/>ORDERS · CUSTOMERS<br/>RLS by region")]:::data
  end

  subgraph OBS["CloudWatch — Observability · control plane (telemetry, not request flow)"]
    direction TB
    cwobs["CloudWatch GenAI Observability<br/>per-turn token EMF · X-Ray traces<br/>model-invocation log (PII-masked)<br/>dashboards · alarms · SLOs"]:::obs
  end

  %% ---- Inbound identity ----
  user -->|"1 · sign in"| feApp
  feApp -.->|"2 · user access token<br/>(aud = agent app)"| user
  user ==>|"3 · InvokeAgentRuntime<br/>Bearer: Entra user JWT"| endpoint
  endpoint -.->|"validate aud / iss / scp"| agentApp
  endpoint ==> agent

  %% ---- Agent reasoning ----
  agent ==>|"ConverseStream<br/>+ requestMetadata (agent/actor/session/turn)"| model
  model -->|"guardrailConfig<br/>(when BEDROCK_GUARDRAIL_ID + VERSION set)"| guard
  agent --> tools
  tools -->|"Retrieve"| kb
  kb --> s3v
  agent <-->|"read / write context"| mem
  agent ==>|"MCP tool calls<br/>(+ user JWT)"| gwcore

  %% ---- Authorization + OBO brokering ----
  gwcore -->|"authorize every call"| cedar
  gwcore --- cpKey
  gwcore --- cpObo
  cpObo -.->|"OBO: GetWorkloadAccessTokenForJWT<br/>then GetResourceOauth2Token<br/>ON_BEHALF_OF_TOKEN_EXCHANGE<br/>scope session:role-any"| oboProv
  oboProv -.->|"per-user Snowflake token<br/>(aud = sfApp)"| sfApp

  %% ---- Egress to backends ----
  gwcore ==>|"sap___getCreditStatus<br/>SigV4 · gateway IAM role"| saplam
  gwcore ==>|"orders___flagOrder<br/>SigV4 · gateway IAM role"| ordlam
  gwcore ==>|"snowflake___ask (NL question)<br/>Authorization: Bearer = OBO token<br/>(X-API-Key placeholder pre-OBO)"| sflam

  %% ---- Backend data paths ----
  ordlam -->|"status check · X-API-Key<br/>(OPEN-only)"| sflam
  sflam -.->|"reads RSA key + config"| sm
  sflam ==>|"user path: forward OBO Bearer<br/>token-type OAUTH"| sfext
  sflam -->|"service fallback: signs KEYPAIR_JWT<br/>SVC_ORDER_TRIAGE (AGENT_RO, read-only)"| sfext
  sfext ==> sfdb

  %% ---- Observability (control plane; telemetry, not request flow) ----
  endpoint -->|"app logs · traces"| cwobs
  agent -->|"per-turn token EMF"| cwobs
  gwcore -->|"app logs · traces"| cwobs
  model -->|"invocation logging (PII-masked)"| cwobs
```

## How to read it

**1 — Inbound identity (CUSTOM_JWT).** The human signs in to the Entra **front-end app**
and receives a user access token whose `aud` is the **agent app**. `InvokeAgentRuntime`
carries it as a Bearer; the Runtime Endpoint's **CUSTOM_JWT** authorizer validates
`aud`/`iss` and that `scp` is present before any agent code runs.

**2 — Agent reasoning.** The `order_triage` Strands agent streams to **Nova Lite**
(`ConverseStream`, tagging each call with `requestMetadata` for the audit log), retrieves
policy passages from the **Knowledge Base** (Titan v2 → S3 Vectors), reads/writes session
**Memory** (short-term events **and** active long-term retrieval — facts/prefs/summaries,
per-user `actor_id`), and reaches all backend data only through **MCP tool calls** to the
Gateway — propagating the user JWT. When `BEDROCK_GUARDRAIL_ID`/`VERSION` are set (default-on
via `enable_guardrail`), Strands attaches a **Bedrock Guardrail** `guardrailConfig` to the
model path — an async `PROMPT_ATTACK` input filter.

> **Model id:** the diagram shows the *deployed* model, **Nova Lite**
> (`amazon.nova-lite-v1:0` via `var.bedrock_model_id`). The agent's code default in
> `agent/src/order_triage/agent.py` (`BEDROCK_MODEL_ID` env) is `anthropic.claude-opus-4-8`;
> the Terraform-injected env var overrides it at deploy time.

**3 — Authorization (Cedar).** Every Gateway tool call is checked by the **Cedar Policy
Engine** in `ENFORCE` mode. The principal is `AgentCore::OAuthUser`; the guard
`principal.hasTag("scp")` admits any authenticated Entra user (a trivially-true
`when{true}` is rejected by the engine's semantic validation). Three permits map to the
tool actions: `permit_sap_read`, `permit_flag`, `permit_snowflake_ask` (one `snowflake___ask`
analytics action — fine-grained row/column governance is in the semantic view + Snowflake RLS,
see ADR-0008).

**4 — Egress credentials (the split).**
- **SAP & orders** targets use **SigV4** signed by the Gateway's IAM role against the
  `AWS_IAM`-locked Lambda Function URLs — no credential provider, no shared key.
- **snowflake** target uses **Entra OBO**: the Gateway exchanges the inbound user JWT for
  a per-user, Snowflake-scoped token (`GetWorkloadAccessTokenForJWT` →
  `GetResourceOauth2Token`, `ON_BEHALF_OF_TOKEN_EXCHANGE`, scope `session:role-any`) via
  the `entra-obo` provider and injects it as `Authorization: Bearer`.

**5 — Snowflake, as the human.** The snowflake-query Lambda has **two auth paths**:
- **User path (OBO):** when the Gateway forwards a Bearer token, the Lambda presents *that*
  to the Snowflake SQL REST API (`token-type OAUTH`). Snowflake's `EXTERNAL_OAUTH (AZURE)`
  integration maps `upn → user` and `scp → role`, so queries run **as the calling human**
  and **row-level security** returns only that user's entitled region.
- **Service fallback:** with no Bearer (e.g. the order-actions status check via `X-API-Key`),
  the Lambda signs a **KEYPAIR_JWT** as `SVC_ORDER_TRIAGE` (the read-only `AGENT_RO` role).

`order-actions` (`flagOrder`) is a thin write-side stub: it reads the order's status from
the snowflake-query Lambda (X-API-Key → service path), refuses anything not `OPEN`, and
records the flag.

**6 — Observability (control plane).** Off the request path, the Runtime and Gateway
deliver **application logs and X-Ray traces** to **CloudWatch GenAI Observability**; the
Runtime also emits a per-turn **token-usage EMF metric** (`OrderTriage/Agent`), and Bedrock
**model-invocation logging** captures each call's tokens/identity/IO behind a CloudWatch
data-protection PII mask. These feed the dashboards, alarms, SLOs and Contributor-Insights
rules. Per-trace **AgentCore Online Evaluations** (LLM-judge) is wired in IaC but
opt-in (`enable_online_evaluations`, default off) and is omitted here for clarity.

## One triage request (sequence)

The same flow as a step-by-step sequence — an analyst's prompt enters the
CUSTOM_JWT runtime; the agent loads memory, queries Snowflake as the user (OBO) for
orders and on its own identity (SigV4) for customers/credit, screens model turns through
the guardrail, retrieves KB policy, and may flag an order — every Gateway call Cedar-authorized:

```mermaid
sequenceDiagram
    autonumber
    actor A as Analyst
    participant RT as AgentCore Runtime (Strands)
    participant M as Nova Lite (Bedrock)
    participant G as Bedrock Guardrail
    participant MEM as AgentCore Memory
    participant KB as Knowledge Base (S3 Vectors)
    participant GW as Gateway + Cedar Policy
    participant SAP as SAP credit Lambda
    participant ORD as order-actions Lambda
    participant SF as Snowflake-query Lambda

    A->>RT: InvokeAgentRuntime (prompt = Triage order O-1003)
    RT->>MEM: load prior session context
    RT->>GW: snowflake___ask("orders to triage for O-1003's customer")
    GW->>GW: Cedar authorize (principal = Entra OAuthUser)
    GW->>SF: POST /ask (Entra OBO Bearer)
    SF->>SF: OBO Bearer (OAUTH) → Cortex Analyst (NL→SQL over ORDERS_SV) → run SQL on SQL API
    SF-->>RT: rows (as the user — RLS by region)
    loop agent reasoning loop
        RT->>G: ApplyGuardrail (PROMPT_ATTACK screen on input)
        G-->>RT: pass / blocked
        RT->>M: ConverseStream (prompt + tools + context)
        M-->>RT: next tool-call decision
        alt credit check
            RT->>GW: sap___getCreditStatus(customer)
            GW->>GW: Cedar authorize (principal = Entra OAuthUser)
            GW->>SAP: GET /credit-status (SigV4 · gateway IAM role)
            SAP-->>RT: on_hold / available_credit
        else policy guidance
            RT->>KB: Retrieve(high-value review policy)
            KB-->>RT: policy passages
        else flag order
            RT->>GW: orders___flagOrder(order)
            GW->>GW: Cedar authorize
            GW->>ORD: POST /orders/{id}/flag (SigV4 · gateway IAM role)
            ORD-->>RT: flagged = true
        end
    end
    RT->>MEM: persist facts / summary
    RT-->>A: streamed triage result (text/event-stream)
    Note over RT: emits per-turn token EMF metric + gen_ai spans (X-Ray)
```

# Architecture diagrams — order-triage AgentCore

A **[system overview](system-overview.md)** (start here) plus five detailed, code-grounded
cross-sections of the *same* `InvokeAgentRuntime` call into the CUSTOM_JWT-authorized
**AgentCore Runtime (`order_triage`)** running Strands over **Bedrock Nova Lite**. All six are
**AWS-style SVGs** (official AWS icons, left → right) generated from [`specs.json`](specs.json)
by [`generate.py`](generate.py). Every box traces to real code/IaC across the five-repo split
(`order-triage-agent`, `order-triage-knowledge`, `bedrock-demo-stubs`, `order-triage-webapp`,
`bedrock-demo-infra`); each plane lists its `## Provenance` so a reader can jump from a box to
the file behind it.

Read them as orthogonal planes of one system:

| # | Diagram | Plane it shows | Primary sources | Decision record |
|---|---|---|---|---|
| 0 | [System overview](system-overview.md) | **The whole map** — every subsystem in one L→R picture; start here | all of the below | — |
| 1 | [Agent Architecture](agent-architecture.md) | **Reasoning plane** — system-prompt assembly, the model⇄tools event loop, LOCAL vs Gateway/MCP tools, the three knowledge surfaces (ontology · skills · KB) | `../../../agent/src/order_triage/*`, `../../../knowledge/{ontology,kb,skills}`, infra `runtime.tf`/`gateway.tf`/`knowledge_base.tf` | [architecture.md](../architecture.md) |
| 2 | [Security Architecture](security-architecture.md) | **Identity / authorization plane** — Entra inbound CUSTOM_JWT, Cedar at the Gateway, the Guardrail, the agent-authority `SigV4` vs Entra-OBO `TOKEN_EXCHANGE` egress split, Snowflake `EXTERNAL_OAUTH` + RLS | infra `identity.tf`/`policy.tf`/`guardrail.tf`, agent `identity.py`/`gateway.py`, `../../../stubs/snowflake_stub`, `../../../app/app/entra.py` | [ADR-0001](../adr/0001-user-impersonation-obo.md), [ADR-0003](../adr/0003-bedrock-guardrail.md), [ADR-0006](../adr/0006-gateway-role-least-privilege.md) |
| 3 | [Memory Architecture](memory-architecture.md) | **Per-user state plane** — `actor_id`-keyed short-term events + the SEMANTIC / USER_PREFERENCE / SUMMARIZATION long-term strategies, the async write path vs the per-turn `<user_context>` read path | infra `memory.tf`, agent `memory.py`/`identity.py` | [ADR-0002](../adr/0002-agentcore-memory-activation.md) |
| 4 | [Observability Architecture](observability-architecture.md) | **Control plane** that the other four emit into — ADOT `gen_ai.*` spans → X-Ray Transaction Search, the EMF token metric, vended logs + PII mask, dashboards / alarms / SLOs / Contributor Insights | infra `terraform/modules/observability/*`, agent `runtime.py` (`_emit_usage_metric`) | [ADR-0004](../adr/0004-observability-finops.md) |
| 5 | [Evaluation Architecture](evaluation-architecture.md) | **Quality loop** — the offline pytest judge that gates the image, and AgentCore Online Evaluations grading sampled live `gen_ai` spans | infra `modules/observability/evaluations.tf`, agent `evals/` | [ADR-0005](../adr/0005-online-evaluations.md) |

## How the five relate

These diagrams decompose a single system along one shared spine. **Agent** is the reasoning
plane (how it thinks and acts); **Security** is the identity/authorization plane wrapped around
that reasoning (who is allowed to do what, *as whom* — the agent-authority `SigV4` vs Entra-OBO
Snowflake split is the heart of the design); **Memory** is the per-user state plane keyed by the
*same* Entra subject that drives OBO; **Observability** is the grey control plane that all four
others emit telemetry into (ADOT `gen_ai` spans to X-Ray Transaction Search, the per-turn EMF
token metric, the audience dashboards and alarms); and **Evaluation** closes the loop by grading
the runtime's `gen_ai` spans both offline (the CI gate that blocks the agent image) and online
(sampled live traces via AgentCore Online Evaluations).

The connective tissue kept identical across all five: the **AgentCore Runtime (`order_triage`)**
node, **Bedrock Nova Lite** (`amazon.nova-lite-v1:0`), the **AgentCore Gateway (MCP)**, **Cedar
Policy Engine (ENFORCE)**, **AgentCore Memory**, the Entra app set (`api://agent-app`,
`api://order-triage-snowflake`, the `entra-obo` provider), the **snowflake-query Lambda**, and
the `gen_ai`/`aws/spans` telemetry that Observability and Evaluation share.

## Scope convention

Every diagram states what it omits and defers the **live request / data plane** — the end-to-end
flow from the Entra-authenticated caller through the Gateway, the stub Lambdas, OBO, and into
Snowflake as the calling human — to the canonical [`../architecture.md`](../architecture.md).
The build / publish / deploy pipeline (GitHub Actions, OIDC, ECR/S3 artifacts) is omitted from
all of them; see the [repo README](../../README.md) and [CD setup](../playbooks/cd-setup.md).

## Visual grammar (shared by all six)

- **Official AWS icons**, laid out **left → right**. Each box is a subsystem; its sub-line names
  the parts (e.g. *AgentCore Gateway · Cedar ENFORCE · OBO broker*).
- **Edges** — **solid dark** = request / data path · **blue dashed** = identity / token / secret ·
  **grey** = supporting (incl. telemetry). Primary steps are numbered (`a/b/c` for a parallel
  fan-out, e.g. the `8a/8b/8c` SigV4-vs-OBO egress split in Security).
- **Rounded zones** group by trust / responsibility — a solid *AWS Cloud · us-west-2* boundary,
  dashed sub-zones (*AWS Lambda · Function URLs*), and the *Observability* control plane.

> Generated, not hand-drawn: each diagram is `<plane>-architecture.svg`, emitted by
> [`generate.py`](generate.py) from [`specs.json`](specs.json) —
> `uv run --with diagrams python docs/architecture/generate.py`. The official AWS icon PNGs come
> from the `diagrams` package (base64-embedded so GitHub renders the SVG inline); PNG fallbacks
> need `rsvg-convert` (`brew install librsvg`). See [`_awsviz.py`](_awsviz.py) for the node /
> edge / group grammar. **Edit the spec, never the SVG.**

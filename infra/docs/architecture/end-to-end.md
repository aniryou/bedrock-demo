# End-to-end lifecycle

The whole **order-triage AgentCore** system in **one frame** — every plane fused along the
lifecycle it actually runs: **author → build & gate → deploy → run → observe → evaluate → (loop
back)**. Read it as a **spine with two tributaries**. The **middle spine** is the live request
flow (`R1…R7`): an Entra-authenticated analyst through the AgentCore Runtime (Strands over
**Bedrock Nova Lite**) and the Cedar-guarded **AgentCore Gateway**, out to the stub Lambdas and
**Snowflake** *as the calling human*. The **top tributary** is the delivery pipeline (`B1…B6`):
the knowledge corpus and mono-repo through path-filtered CI, the offline eval gate, ECR/S3
artifacts, and a human-gated `terraform apply` that **provisions** the spine. The **bottom
tributary** is the observability control plane that every turn emits into; the single grey
**`eval findings → knowledge`** edge from Online Evaluations back to the corpus is what closes the
loop. This is the **hero / start-here** view — the eight focused planes below are its cross-sections.

**Legend** — official AWS icons, left → right. Edges: **solid dark** = request / data path · **blue dashed** = identity / token / secret · **grey** = supporting (incl. telemetry). **Two numbered tracks** keep the orthogonal stories apart: **`B1…B6`** = build & deploy, **`R1…R7`** = the live request; observe + loop-back edges are grey/unnumbered. Rounded boxes are trust / responsibility zones; **Snowflake sits outside the AWS Cloud boundary** (external `EXTERNAL_OAUTH` egress). The diagram is generated from [`specs.json`](specs.json) by the `architecture-skill` skill — edit the spec, not the SVG.

![End-to-end lifecycle — AWS architecture](end-to-end-architecture.svg)

## How to read it — two tracks and a loop

**Build & deploy track (`B1…B6`, top).** The enterprise **knowledge corpus** (ontology · skills ·
KB docs) lives in the mono-repo alongside the shared **`agent_kit`** lib; a push routes by folder
through **path-filtered CI**, and the **agent-build** publisher bakes the in-tree lib + knowledge
into an arm64 image (`B1`). The **offline
eval gate** — the pytest + LLM-judge suite over `cases.yaml` — must pass before the image is pushed
to **ECR** (`B2 → B3a`); **stubs-release** publishes the Lambda zips + OpenAPI to **S3** (`B3b`).
Both publishers `repository_dispatch` into the gated **`deploy.yml`** (`B4a/B4b`), which blocks on a
**manual approval** (`env:production`), assumes the **GitHub OIDC** role, and runs **`terraform
apply`** against S3 remote state (`B5`). The apply **provisions the runtime spine** (`B6`) — the one
bold vertical drop that ties build-time to run-time.

**Request track (`R1…R7`, middle — the spine).** The analyst signs into **Entra** and the app
invokes the Runtime with the user's `CUSTOM_JWT` Bearer (`R1–R3`). The Runtime streams to **Nova
Lite** behind the **Guardrail** (`R4`), consulting its **LOCAL knowledge tools**, the **Knowledge
Base**, and per-user **short/long-term Memory** in-process. Tool calls cross the **Cedar-`ENFORCE`d
Gateway** carrying the user JWT (`R5`), which fans out with the egress split that is the heart of
the design (`R6a/R6b/R6c`): **`SigV4` (agent authority)** to SAP credit + order-actions, **Entra-OBO
Bearer (user authority)** to snowflake-query. Snowflake then runs the query under `EXTERNAL_OAUTH` +
**RLS as the signed-in human** (`R7`).

**Observe + loop (grey, bottom).** Runtime telemetry lands in **X-Ray** (`gen_ai` spans) and
**CloudWatch Logs** (EMF token metric), feeding **Dashboards → Alarms → SNS** and **App Signals
SLOs**. **AgentCore Online Evaluations** grade sampled live `gen_ai` spans, and their findings feed
back to the **knowledge corpus** — the return edge that makes this a lifecycle, not a DAG.

## The eight planes, zoomed in

Every region of this map is a real subsystem; its detail — and the file behind each box — lives in
the matching cross-section, which lists its own `## Provenance`:

- [**Detailed data plane**](data-plane.md) — the spine (`R1…R7`) at wire level: Cedar, OBO `TOKEN_EXCHANGE`, Snowflake RLS, with a Mermaid sequence.
- [**Agent**](agent-architecture.md) — the reasoning loop (model ⇄ tools, the three knowledge surfaces, LOCAL vs Gateway/MCP tools).
- [**Knowledge**](knowledge-architecture.md) — the corpus: ontology Objects + Actions, Skills, KB; the `bindings.json` reverse index and the `action_implementations` Action→Gateway-tool seam.
- [**Security**](security-architecture.md) — Entra `CUSTOM_JWT`, Cedar at the Gateway, the `SigV4` (agent) vs Entra-OBO (user) egress split, Snowflake `EXTERNAL_OAUTH` + RLS.
- [**Memory**](memory-architecture.md) — per-user short-term events + the SEMANTIC / USER_PREFERENCE / SUMMARIZATION long-term strategies, keyed by the Entra subject.
- [**Observability**](observability-architecture.md) — ADOT `gen_ai` traces → X-Ray, the EMF token metric, vended logs + PII mask, dashboards / alarms / SLOs.
- [**Evaluation**](evaluation-architecture.md) — the offline pytest gate that blocks the image (`B2`) + Online Evaluations grading sampled live spans (bottom).
- [**DevOps / CI-CD**](devops-architecture.md) — the build & deploy track (`B1…B6`): path-filtered workflows, the `agent-build` / `stubs-release` publishers, OIDC, the human-gated apply.

## Provenance (by region)

The per-box file mapping lives in each plane's own `## Provenance`; this view's regions trace to:

- **Build & deploy track (`B1…B6`)** → `.github/workflows/*` (`agent-build.yml` bakes `../knowledge`; `stubs-release.yml`), `infra/bootstrap/github_oidc.tf` (OIDC `repo:aniryou/bedrock-demo:environment:production`), `deploy.yml`; runbook [`playbooks/cd-setup.md`](../playbooks/cd-setup.md). Offline eval gate → `agent/evals/` ([Evaluation](evaluation-architecture.md)).
- **Request spine (`R1…R7`)** → `app/`, the `agent/` runtime + its shared `agent_kit` plumbing, `infra/terraform/{runtime,gateway,policy,identity,*_lambda,guardrail}.tf`, `stubs/{sap,order_actions,snowflake}_stub`, `infra/snowflake/{setup,rls,semantic_view}.sql`. Wire-level detail in [data-plane.md](data-plane.md); identity in [security-architecture.md](security-architecture.md).
- **Knowledge corpus + LOCAL tools + KB** → `knowledge/{ontology,skills,kb}`, the `agent/` knowledge tools, `infra/terraform/knowledge_base.tf` ([Knowledge](knowledge-architecture.md)).
- **Memory (short/long-term)** → `infra/terraform/memory.tf` + the `agent/` memory plumbing ([Memory](memory-architecture.md)).
- **Observe + Online Evaluations** → `infra/terraform/modules/observability/*` + the `agent/` per-turn usage metric ([Observability](observability-architecture.md), [Evaluation](evaluation-architecture.md)).

## Scope & decisions

This map is **complete by design** — it deliberately fuses the build/publish/deploy pipeline, the
live request plane, and the telemetry/eval control plane that the focused planes each hold apart. For
a *simpler* read of any one concern, follow its plane link above. Decisions behind the boxes:
[ADR-0001](../adr/0001-user-impersonation-obo.md) (OBO), [-0002](../adr/0002-agentcore-memory-activation.md) (memory),
[-0003](../adr/0003-bedrock-guardrail.md) (guardrail), [-0004](../adr/0004-observability-finops.md) (observability/FinOps),
[-0005](../adr/0005-online-evaluations.md) (evals), [-0006](../adr/0006-gateway-role-least-privilege.md) (gateway role),
[-0008](../adr/0008-semantic-view-cortex-analyst.md) (semantic view + Cortex Analyst).

# bedrock-demo

A working **order-triage AI agent** on **Amazon Bedrock AgentCore**, delivered as a
single mono-repo. An analyst asks the agent to triage an order; the agent reads
orders/customers from Snowflake, checks SAP credit, retrieves policy from a Bedrock
Knowledge Base, and flags risky orders — every backend call **authorized by Cedar** and
brokered **on-behalf-of the signed-in user** (Entra → Snowflake OBO), so Snowflake RBAC/RLS
decides what each user can see. Deployed region: **us-west-2**; model: **Nova Lite**.

The repository is organized as five top-level folders, each with its own `README.md` and
`CLAUDE.md`; this root README is the hub that ties them together.

## The five components

| Folder | Role | Key hand-off |
|---|---|---|
| [`knowledge/`](knowledge/README.md) | Knowledge layer: ontology + skills + KB (source of truth) | skills/ontology/KB → baked into the agent image |
| [`agent/`](agent/README.md) | Strands agent on Bedrock AgentCore Runtime | arm64 image → ECR, KB docs → S3 → `infra/`; calls the stubs through the Gateway |
| [`stubs/`](stubs/README.md) | Back-office tool services (SAP · order-actions · Snowflake) | Lambda zips + OpenAPI → S3 → `infra/`; serve as the agent's Gateway targets |
| [`infra/`](infra/README.md) | Terraform: provisions the live AWS stack (the **orchestrator**) | consumes all the artifacts above; deploys Runtime/Gateway/Memory/Policy/KB/Guardrail/observability |
| [`app/`](app/README.md) | OBO sign-in client (the demo driver) | Entra user JWT → the deployed OBO runtime |

The flow is a pipeline: **knowledge** is the upstream source of truth → **agent** bakes it
into an image and calls **stubs** through the Gateway → **infra** provisions the live stack
from the agent + stubs artifacts → **app** drives the deployed runtime as a signed-in user.

## Repository structure

```text
bedrock-demo/
├── knowledge/            # ontology + skills + KB (file-based; git is the audit log)
├── agent/                # Strands agent + AgentCore Runtime entrypoint (arm64 image)
├── stubs/                # 3 FastAPI back-office stubs (SAP · orders · Snowflake) as Lambdas
├── infra/                # Terraform orchestrator: provisions the whole AWS stack
├── app/                  # FastAPI OBO chat client (the demo driver)
├── .github/workflows/    # path-filtered CI/CD (see CI/CD below)
├── .env                  # the SINGLE config file for the whole stack (gitignored)
└── README.md             # you are here
```

Each folder keeps its own `README.md` (full component docs + diagrams) and `CLAUDE.md`
(machine/agent operating notes). The one config file — `.env` at the root — is read by
`infra/` and `app/` as `../.env`; it holds the AWS, Entra, and Snowflake credentials and is
gitignored.

## Setup & usage

**Prerequisites**

- An **AWS account** + a deploy role/credentials (least-privilege; see [`infra/docs/playbooks/cd-setup.md`](infra/docs/playbooks/cd-setup.md)).
- An **Entra (Azure AD) tenant** + admin, for the OBO sign-in flow ([`infra/docs/playbooks/entra-obo-setup.md`](infra/docs/playbooks/entra-obo-setup.md)).
- A **Snowflake account**, for the order/customer data path ([`infra/docs/playbooks/snowflake-bootstrap.md`](infra/docs/playbooks/snowflake-bootstrap.md)).
- The single root **`.env`** (gitignored) — `make` resolves every `TF_VAR_*` and bootstrap output from it.
- Tooling: `make -C infra prereqs` installs `terraform>=1.10` + `uv` + `aws` (skip if already present).

**Deploy (happy path)** — driven from `infra/`:

```bash
cd infra
make prereqs           # one-time: install terraform>=1.10 + uv + aws (skip if present)
make preflight         # read-only access check (must pass before deploy)
make bootstrap         # ECR + artifacts bucket + secret container — note the outputs
make snowflake-setup   # seed Snowflake + populate the Secrets Manager secret
make seed-entra-secret # put the Entra OBO client secret in Secrets Manager (kept out of TF state)
# publish the agent image + stub zips/KB to the bucket (run agent-build.yml / stubs-release.yml, or build locally)
make deploy            # terraform apply, consuming the published artifacts
make ingest            # trigger KB ingestion (required after every fresh apply)
make status            # end-to-end smoke test: mints an Entra user token + one live triage invoke
```

Then drive the live runtime from the webapp:

```bash
cd app
cp .env.example .env   # set OBO_RUNTIME_ARN (from: terraform -chdir=../infra/terraform output -raw agent_runtime_arn)
./run.sh               # http://localhost:8000 — sign in as User A vs User B
```

Each component also runs standalone for local development — see its folder README
([knowledge](knowledge/README.md) · [agent](agent/README.md) · [stubs](stubs/README.md) ·
[infra](infra/README.md) · [app](app/README.md)).

## Architecture & visualizations

### System architecture

![Order-Triage AgentCore system architecture](infra/docs/system-architecture.svg)

> Generated from [`infra/docs/architecture_diagram.py`](infra/docs/architecture_diagram.py) —
> **regenerate, don't hand-edit** the SVG. Raster fallback: [`infra/docs/system-architecture.png`](infra/docs/system-architecture.png).
> For the **full runtime data plane** (CUSTOM_JWT identity, Cedar authorization, the
> PROMPT_ATTACK guardrail, the SigV4-vs-OBO egress split, per-user Snowflake RLS, and the
> per-turn token/trace telemetry) see [`infra/docs/architecture.md`](infra/docs/architecture.md),
> and the per-concern subsystem diagrams in [`infra/docs/architecture/`](infra/docs/architecture/README.md).

### CI/CD pipeline

Each component has its own **path-filtered workflow**: a change under a folder runs only that
component's checks, and a merge to `main` cascades to a **human-gated** `terraform apply`. The
publishers self-dispatch the deploy in-repo via `repository_dispatch`.

```mermaid
flowchart LR
    subgraph folders["Mono-repo folders (a change here…)"]
        direction TB
        kn["knowledge/"]
        ag["agent/"]
        st["stubs/"]
        inf["infra/"]
        ap["app/"]
    end

    subgraph ci["…runs only that component's CI (PR + push)"]
        direction TB
        knv["knowledge-validate.yml"]
        agc["agent-ci.yml"]
        stc["stubs-ci.yml"]
        infc["infra-ci.yml"]
        apc["app-ci.yml"]
    end

    subgraph publish["On merge to main → publish artifacts"]
        direction TB
        agb["agent-build.yml<br/>arm64 image → ECR · KB → S3"]
        str["stubs-release.yml<br/>zips + OpenAPI → S3"]
    end

    dep["deploy.yml<br/>🔒 manual approval → terraform apply"]
    live(["Live AgentCore stack"])

    kn --> knv
    ag --> agc
    st --> stc
    inf --> infc
    ap --> apc

    ag ==>|push main| agb
    kn ==>|"push main (in-tree skills)"| agb
    st ==>|push main| str

    agb -. "repository_dispatch:<br/>agent-image-published" .-> dep
    str -. "repository_dispatch:<br/>stubs-published" .-> dep
    dep --> live
```

| Workflow | Trigger (path-filtered) | Does |
|---|---|---|
| [`knowledge-validate.yml`](.github/workflows/knowledge-validate.yml) | PR/push · `knowledge/**` | validate ontology + bindings; drift gates; render overview |
| [`agent-ci.yml`](.github/workflows/agent-ci.yml) | PR/push · `agent/**` | ruff + hermetic unit tests + skill-manifest lint |
| [`stubs-ci.yml`](.github/workflows/stubs-ci.yml) | PR/push · `stubs/**` | ruff + FastAPI TestClient tests + Lambda-zip packaging |
| [`infra-ci.yml`](.github/workflows/infra-ci.yml) | PR/push · `infra/**` | `terraform fmt/validate` + ruff (+ opt-in live `plan`) |
| [`app-ci.yml`](.github/workflows/app-ci.yml) | PR/push · `app/**` | install deps + byte-compile the backend |
| [`agent-build.yml`](.github/workflows/agent-build.yml) | push main · `agent/**` or `knowledge/**` | bake in-tree knowledge → arm64 image → ECR + KB → S3 → cascade |
| [`stubs-release.yml`](.github/workflows/stubs-release.yml) | push main · `stubs/**` | build zips + OpenAPI → S3 → cascade |
| [`deploy.yml`](.github/workflows/deploy.yml) | `repository_dispatch` / manual | **human-gated** `terraform apply` against live state |

The publish→deploy cascade uses a PAT (`DISPATCH_TOKEN`) because a `GITHUB_TOKEN`-triggered
`repository_dispatch` deliberately does not start new runs. Full pipeline + secrets/vars
setup: [`infra/docs/playbooks/cd-setup.md`](infra/docs/playbooks/cd-setup.md).

### One triage request (the runtime data plane)

An analyst's prompt enters the CUSTOM_JWT runtime; the agent loads memory, queries Snowflake
as the user (OBO) for orders and on its own identity (SigV4) for customers/credit, screens
model turns through the guardrail, retrieves KB policy, and may flag an order — every Gateway
call Cedar-authorized:

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

### Per-component diagrams

- **Agent internals + ontology routing** — [`agent/README.md`](agent/README.md#architecture--visualizations)
- **Stubs runtime + build/deploy** — [`stubs/README.md`](stubs/README.md#architecture--visualizations)
- **Know-how stack (KB → Skills → Ontology) + feedback loop** — [`knowledge/README.md`](knowledge/README.md#architecture--visualizations)
- **OBO sign-in flow (User A vs User B)** — [`app/README.md`](app/README.md#architecture--visualizations)

## Key journeys

**1 · Provisioning order.** `make -C infra bootstrap` creates the ECR repo + bucket *before*
the agent image / stub zips / KB docs are published; the main `terraform apply` then reads the
published OpenAPI specs and the ECR image **at plan/apply time**, so those publishes are hard
prerequisites. The one-time Snowflake prerequisite is handled outside Terraform by
`make -C infra snowflake-setup`.

**2 · One triage request.** See the sequence above — prompt → memory → Cedar-authorized
Gateway tools (orders as the user via OBO; customers/credit as the agent via SigV4) →
guardrail-screened model loop → KB policy → optional flag → streamed result.

**3 · A change ships to the live stack.** Merge a change under `agent/`, `knowledge/`, or
`stubs/` to `main` → the matching publish workflow rebuilds and uploads the artifact → it
cascades a `repository_dispatch` into the **human-gated** `deploy.yml`. Nothing deploys
without manual approval.

**4 · The two-user OBO demo.** User A and User B sign in through the webapp and both ask
*"Triage order O-1003."* Because the order read runs **as the user** (OBO), a Snowflake row
access policy admits A and denies B — while *"What tier is customer C-001?"* succeeds for both
(customers are read on the agent's own identity). The split is driven by the ontology
classification (`SalesOrder` confidential, `Customer` not), not by app code.

## Further reading

- **Component docs** — each folder's `README.md` (full architecture + diagrams) and `CLAUDE.md`
  (machine/agent operating notes): [knowledge](knowledge/README.md) · [agent](agent/README.md) ·
  [stubs](stubs/README.md) · [infra](infra/README.md) · [app](app/README.md).
- **Decisions (ADRs)** — [`infra/docs/adr/`](infra/docs/adr/) (0001 OBO · 0002 memory · 0003
  guardrail · 0004 observability/FinOps · 0005 evaluations · 0006 gateway-role least-privilege ·
  0007 actor-resolution · 0008 semantic-view + Cortex Analyst · 0009 Function-URL hardening) and
  [`knowledge/docs/adr/`](knowledge/docs/adr/) (ontology privilege/classification).
- **Reference designs** — [`infra/docs/architecture.md`](infra/docs/architecture.md) (data plane) +
  [`infra/docs/architecture/`](infra/docs/architecture/README.md) (subsystem diagrams) +
  [`knowledge/docs/architecture/`](knowledge/docs/architecture/architecture-primer.md) (the three-layer model).
- **Runbooks** — [`infra/docs/playbooks/`](infra/docs/playbooks/): snowflake-bootstrap ·
  deploy & teardown · cd-setup · entra-obo-setup · observability-impl-plan.
- **Spikes & audits** — [`infra/docs/research/`](infra/docs/research/) (the exploration behind the ADRs).

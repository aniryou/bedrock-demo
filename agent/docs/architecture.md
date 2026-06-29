# agent — architecture & internals

Agent-developer reference: the per-turn data flow, how the agent uses the ontology, and the
build & deploy pipeline. The conceptual system diagram lives in the [README](../README.md#architecture);
the helper internals it calls live in [`../../lib/README.md`](../../lib/README.md).

## Data flow (one triage request)

```mermaid
sequenceDiagram
    autonumber
    actor A as Analyst (via webapp)
    participant RT as AgentCore Runtime (Strands)
    participant M as Bedrock model (BEDROCK_MODEL_ID · Nova Lite default)
    participant MEM as AgentCore Memory
    participant KB as Knowledge Base (S3 Vectors)
    participant GW as Gateway + Cedar + OBO
    participant BE as SAP / order-actions / Snowflake Lambdas

    A->>RT: InvokeAgentRuntime (prompt + user JWT)
    Note over RT: forwards the user JWT as the Gateway bearer, then opens one MCP session for the turn
    RT->>MEM: load prior session context (when session_id set)
    loop agent reasoning loop
        RT->>M: ConverseStream (prompt + tools + context)
        M-->>RT: next tool-call decision
        alt route / read skill (describe_entity, load_skill)
            Note over RT: in-process — bindings.json + skill manifests
        else policy guidance (search_policies)
            RT->>KB: Retrieve(relevant policy)
            KB-->>RT: policy passages
        else backend tool (snowflake___* / sap___getCreditStatus / orders___flagOrder)
            RT->>GW: MCP tool call (user JWT bearer)
            GW->>GW: Cedar authorize (principal = the signed-in user)
            GW->>BE: call backend, OBO token minted via TOKEN_EXCHANGE
            BE-->>RT: tool result
        end
    end
    RT->>MEM: persist facts / summary
    RT-->>A: streamed answer (NDJSON) + typed __step__ timeline events
```

## How the agent uses the ontology

The ontology is a **read-only routing & governance layer**, never a data source. It reaches
the agent as two artifacts copied from the in-tree `../knowledge` folder
(`fetch_skills.sh` copies skills and bindings together, so the agent can never route into a skill the
bindings don't know): the skill manifests (`skills/*.skill.md`) and the bindings
reverse-index (`bindings.json`, plus the optional `ontology.compiled.json`). Two consumers
read them:

- **`agent_kit.knowledge.SkillLoader` → system prompt (build-agent time).** `skills_catalog()`
  renders each skill's description plus the ontology entities/actions it `appliesTo` into the
  system prompt that `kit.build_system_prompt()` returns; `load_skill(name)` returns the
  procedure body on demand.
- **`agent_kit.knowledge.OntologyLoader` → `describe_entity` tool (runtime, on-demand).** It reads
  `bindings.json`'s `index.objectType[x]` to answer "which skills / actions / KB govern this
  entity?", enriched with properties / primary key / source-of-truth datasource / related
  governed entities from the compiled file — with **zero** system-prompt growth.

At request time the model routes with `describe_entity(...)`, reads the chosen skill via
`load_skill(name)`, then acts with the Gateway MCP backend tools. The ontology's design names
(e.g. `SalesOrder.soNumber`) are deliberately distinct from the Snowflake runtime fields
(`order_id` / `amount` / `status`) the backend tools actually return — so ontology names are
for routing, never tool arguments.

```mermaid
flowchart TB
    subgraph know["../knowledge (in-tree folder)"]
        direction TB
        oyaml["ontology/*.yaml<br/>object-types · link-types · actions · governance"]
        genr["build/bindings.py<br/>reverse-index generator"]
        bind["bindings.json<br/>index.objectType → skills · actions · kb"]
        comp["ontology.compiled.json (optional)<br/>properties · primaryKey · datasource · links"]
        sk["skills/*.skill.md<br/>frontmatter apiName + appliesTo + body"]
        oyaml --> genr --> bind
        oyaml --> comp
        oyaml -. binds .-> sk
    end

    fetch["scripts/fetch_skills.sh — make skills / CI<br/>copies skills + bindings from ../knowledge"]

    subgraph repo["agent repo · fetched, gitignored"]
        direction LR
        sdir["SKILLS_DIR<br/>skills/*.skill.md"]
        odir["ONTOLOGY_DIR<br/>bindings.json (+ compiled)"]
    end

    subgraph agent["Strands agent process (assembled by the agent via kit.* helpers)"]
        direction TB
        sloader["agent_kit.knowledge SkillLoader<br/>skills_catalog() · get_skill()"]
        oloader["agent_kit.knowledge OntologyLoader<br/>describe_entity reverse-index"]
        prompt["system prompt<br/>skill catalog + entity/action tags<br/>(built by kit.build_system_prompt())"]
        subgraph tools["tool surface"]
            direction TB
            de["describe_entity(api_name)<br/>on-demand · zero prompt growth"]
            ls["load_skill(name)"]
            act["search_policies (local KB)<br/>snowflake___ask<br/>sap___getCreditStatus · orders___flagOrder<br/>(Gateway MCP · OBO-brokered)"]
        end
    end

    model["Model reasoning loop"]

    sk --> fetch
    bind --> fetch
    comp --> fetch
    fetch --> sdir
    fetch --> odir

    sdir --> sloader
    odir --> oloader
    sloader -->|catalog at build time| prompt
    de --> oloader
    ls --> sloader

    prompt --> model
    model -->|"1 route: which skill governs the entity?"| de
    model -->|"2 read the steps"| ls
    model -->|"3 act on data"| act

    note["Ontology = design/governance map only.<br/>Its names (SalesOrder.soNumber) are NOT the<br/>Snowflake fields (order_id/amount/status)."]
    oloader -.-> note
```

## Build & deploy pipeline

```mermaid
flowchart LR
    subgraph repos["Mono-repo folders (bedrock-demo)"]
        direction TB
        skills["knowledge/<br/>ontology + skills + kb docs"]
        librepo["lib/<br/>agent_kit runtime toolkit"]
        agentrepo["agent/<br/>build_agent + runtime + Dockerfile"]
        stubsrepo["stubs/<br/>FastAPI stubs"]
        infrarepo["infra/<br/>Terraform + scripts"]
    end

    subgraph build["Build & publish artifacts"]
        direction TB
        img["Agent arm64 image<br/>(repo-root context: installs ./lib[deploy] then the agent;<br/>skills + ontology baked in)"]
        kbdocs["KB policy docs<br/>(./kb · fetched from the knowledge release)"]
        zips["Lambda zips + OpenAPI<br/>build_lambdas.sh"]
    end

    subgraph store["Artifact stores (terraform bootstrap)"]
        direction TB
        ecr["ECR repo"]
        s3["S3 artifacts bucket"]
    end

    tf["terraform apply<br/>AgentCore + Lambdas + KB<br/>Gateway + Policy + Memory"]
    reg["infra.register (local-exec)"]
    live(["Live stack"])

    skills -->|fetch_skills.sh| agentrepo
    librepo -->|"installed into the image (./lib[deploy])"| img
    agentrepo --> img
    agentrepo --> kbdocs
    stubsrepo --> zips
    img -->|push| ecr
    kbdocs -->|"s3 sync kb/"| s3
    zips -->|"s3 cp stubs/"| s3
    infrarepo -. bootstrap .-> ecr
    infrarepo -. bootstrap .-> s3
    ecr --> tf
    s3 --> tf
    infrarepo --> tf
    tf --> reg --> live
```

The agent's CI (`../../.github/workflows/agent-build.yml`) owns the **Agent arm64 image** and **KB docs**
boxes: it copies skills/ontology/kb from `../knowledge`, builds + pushes the arm64 image to ECR
(`-f agent/Dockerfile` from the **repo root**, so it can `COPY lib` then `pip install ./lib[deploy]`
before the agent), and syncs the fetched `kb/` to `s3://<artifacts>/kb/`, then cascades an
`agent-image-published` dispatch to [infra](../../infra/README.md), which references the
image URI + KB prefix as Terraform inputs. Because the image bakes the shared lib, this build's
path filter includes `lib/**` — a `lib/` change rebuilds the agent image and also runs
`agent-ci.yml`. The hermetic `lib-ci.yml` (ruff + pytest, no AWS) covers `agent_kit` itself.
The build's trigger surface and the observability wiring (the `opentelemetry-instrument` launch
wrapper and the `OrderTriage/Agent` EMF metric namespace) are documented in [`../CLAUDE.md`](../CLAUDE.md).

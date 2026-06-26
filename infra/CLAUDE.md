# CLAUDE.md — working notes for this repo

`bedrock-demo-infra`: Terraform (+ a small `infra/` preflight/registry helper) that deploys the
**order-triage AgentCore** demo to **us-west-2**. It is one of a 5-repo split and consumes the
others' *published artifacts* as inputs — it does not build them:

| Folder | Produces | Consumed here as |
|---|---|---|
| `agent` | arm64 agent image → ECR; KB docs → S3 | `var.agent_image_uri`; KB data source |
| `stubs` | sap / orders / snowflake Lambda zips + OpenAPI → S3 | Lambda `s3_key` + `aws_s3_object` |
| `knowledge` | skills / ontology corpus | baked into the agent image |
| `app` | Entra sign-in client | runtime caller (live OBO demo) |

## Where things live
- `bootstrap/` — ECR + artifacts S3 bucket + GitHub OIDC roles. **Apply first** (separate state).
- `terraform/` — the main stack: `runtime.tf`, `gateway.tf`, `policy.tf` (Cedar), `identity.tf`
  (credential providers), `memory.tf`, `*_lambda.tf` (sap / order-actions / snowflake-query),
  `guardrail.tf`, `observability.tf` → `modules/observability/`, `registry.tf`, `variables.tf`.
- `entra/` — the Entra (azuread) apps as Terraform, **separate LOCAL state** — never torn down
  with the AWS stack. `make entra-setup` (az CLI) is the imperative alternative.
- `snowflake/` — `setup.sql`, `rls.sql`, `semantic_view.sql` (the `ORDERS_SV` Cortex-Analyst model,
  ADR-0008), `test_user.sql` (applied outside the main apply via `make apply-sql FILES=...`).
- `docs/` — `architecture.md` (detailed mermaid data plane), `architecture_diagram.py`
  (→ `system-architecture.svg/.png`), `adr/` (decisions), `architecture/` (subsystem diagrams),
  `playbooks/` (runbooks: cd-setup · entra-obo-setup · snowflake-bootstrap · deploy · observability-impl-plan),
  `research/` (spikes & audits behind the ADRs).
- Config is a **single `../.env`** at the workspace root (gitignored); `make` resolves `TF_VAR_*`
  + the bootstrap outputs from it. `terraform/terraform.tfvars.example` documents the tunables.

## Commands
```bash
make preflight        # read-only access check (runs before deploy)
make tf-validate      # offline validate — use this to check TF changes without AWS
make bootstrap        # ECR + bucket + secret container (first time)
make snowflake-setup  # seed Snowflake + populate the Secrets Manager secret (outside TF)
make seed-entra-secret# put the Entra OBO client secret in Secrets Manager (kept out of TF state)
make deploy           # terraform apply (consumes published artifacts)
make ingest           # trigger KB ingestion (required after every fresh apply)
make status           # end-to-end smoke test: mints a ROPC user token + live triage invoke
make destroy[-full]   # teardown (full also removes ECR/S3/secret container)
```
CI/CD (auto-publish cascade + human-gated apply) is documented in `docs/playbooks/cd-setup.md`.

## Deployed reality — check before assuming
- **Model is `amazon.nova-lite-v1:0`** (`var.bedrock_model_id`). The agent code's
  `claude-opus-4-8` default is *overridden* at deploy — don't trust the Python default.
- **Guardrail is on by default** (`enable_guardrail`): PROMPT_ATTACK input filter only, **no PII
  policy by design** (the OBO agent reads customer PII end-to-end) — see ADR-0003.
- **Observability is on by default** (ADR-0004). `alert_email` defaults empty → **alarms notify
  no one** until set + the SNS email is confirmed.
- **Online Evaluations are opt-in** (`enable_online_evaluations`, default false); scoring is
  currently blocked on `AgentSpanMappingException` — see ADR-0005.
- **OBO is Gateway-brokered** (`grant_type=TOKEN_EXCHANGE` on the snowflake target); the agent
  carries no OBO code. Inbound is `CUSTOM_JWT` (Entra v1) on both Runtime and Gateway.
- **ARNs are recreated each deploy** — read them from `terraform output` (or `make status`),
  never hardcode.

## Conventions
- **Prefer AWS-native and built-in over custom.** Reach for a native TF resource or AWS-managed
  service before `terraform_data` + local-exec, a shell script, or a new provider; custom glue is
  the last resort (and where unavoidable it has no drift detection — say so, as ADR-0004/0005 do).
- **Inline comments state the what / why / how of the _current_ config** — never how it got there.
  Provenance, change history, and PR/phase references belong in ADRs and git, not in `.tf` comments.
- **Decisions go in ADRs** (`docs/adr/`, follow the 0001–0005 format: Status/Date/Deciders/
  Related → Context → Decision → Options → Consequences → Risks → Action items → References).
  Keep the README **current-state only** — the "why / how we got here" belongs in ADRs. Keep the
  ADRs current as decisions change and consistent with the rest of the 5-repo split.
- **Don't hand-edit generated diagrams.** Top-level `docs/system-architecture.svg/.png` ← edit the
  `NODES`/`EDGES`/`GROUPS` tables in `docs/architecture_diagram.py`. The six AWS-style plane diagrams
  `docs/architecture/*-architecture.svg` come from the **`aws-architecture-diagram` skill** — its
  renderer is vendored here as `docs/architecture/_awsviz.py` (+ `generate.py`). To edit/add/convert
  one: change `docs/architecture/specs.json` (node/edge/group grammar lives in `_awsviz.py`) and re-run
  `uv run --with diagrams python docs/architecture/generate.py` (`brew install librsvg` for the `.png`
  fallbacks). **Use that skill for any new "AWS-style" architecture diagram** — it carries the icon set,
  elbow-connector routing, and the zone/grid conventions. Re-run, never hand-edit the SVG. Any remaining
  Mermaid (e.g. in ADRs) → run the `mermaid-check` skill before committing.
- Branch off `main`; PRs are **squash-merged** once CI (`python` lint, `iac`) is green.
- **Work in your own git worktree** so parallel agents don't collide on the shared checkout.
  Default location (a shared root outside the repo): `git worktree add
  ../.worktrees/bedrock-demo/<branch> -b <branch>`. After pushing the branch, remove it:
  `git worktree remove ../.worktrees/bedrock-demo/<branch>` (then `git worktree prune`).
- New TF variables that an operator might set → also add to `terraform.tfvars.example`.

## Gotchas
- **OBO is full of silent traps** (token version v1, `session:role-any` scope carrier, user-mapping
  `('upn','email')`, `tenant_id` only on `awscc`, the runtime's `secretsmanager` grant). The full
  list is the Gotchas table + Step 6 in `docs/playbooks/entra-obo-setup.md` — read it before touching OBO.
- **Secrets** (Snowflake RSA key, Entra client secret) live in Secrets Manager, **out of TF state**;
  seed via `make snowflake-setup` / `make seed-entra-secret`. The Entra agent secret **expires
  2026-12-17** (rotation note in `playbooks/entra-obo-setup.md` Step 4).
- The **deploy role** is a generated least-privilege policy, split into two managed policies for the
  6144-char IAM cap (not AdministratorAccess) — see `docs/playbooks/cd-setup.md` / `bootstrap/github_oidc.tf`.
- App Signals SLOs + online Evaluations are created by **`terraform_data` + AWS CLI local-exec**
  (no native TF resource exists) — they have no drift detection (ADR-0004 D7, ADR-0005 D3).
- **Record recurring tool/command failures and their fixes here** (an `aws`/`terraform` call that
  needs a specific flag, region, or apply ordering) so the same dead end isn't rediscovered. Keep
  this file lean — correct stale lines rather than appending new ones.

## Pointers
- System diagram + deploy pipeline: `README.md`. Detailed runtime data plane: `docs/architecture.md`.
- Decisions: `docs/adr/0001`(OBO) · `0002`(memory) · `0003`(guardrail) · `0004`(observability/FinOps) · `0005`(evaluations) · `0006`(gateway-role least-privilege) · `0007`(actor-resolution) · `0008`(semantic-view + Cortex Analyst) · `0009`(snowflake Function URL direct-call hardening — deferred).
- Runbooks (`docs/playbooks/`): Snowflake seed `snowflake-bootstrap.md` · deploy/teardown `deploy.md` · OBO `entra-obo-setup.md` · CI/CD `cd-setup.md` · observability `observability-impl-plan.md`. Spikes/audits: `docs/research/`. Entra apps as TF: `entra/README.md`.

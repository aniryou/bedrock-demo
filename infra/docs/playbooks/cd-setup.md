# CD pipeline — setup & operation

Auto-publish on merge, an **in-repo** cascade, and a **human-gated** `terraform apply`.
The workflow code is committed; this doc is the one-time substrate you must provision
(none of it existed before — the repo had zero secrets/variables and no OIDC roles).

Everything lives in **one repo, `aniryou/bedrock-demo`**, with **path-filtered** workflows
under `.github/workflows/`: per-folder CI (`knowledge-validate.yml`, `agent-ci.yml`,
`stubs-ci.yml`, `infra-ci.yml`, `app-ci.yml`), the two publishers (`agent-build.yml`,
`stubs-release.yml`), and the gated `deploy.yml`. A merge only runs the workflows whose
`paths:` matched the change.

## What it does

```
knowledge/**  change
        │  (no separate publish — a knowledge/ edit is on agent-build.yml's path filter)
        ▼
agent/** or knowledge/** change ──> agent-build.yml
        │  builds the arm64 image (knowledge baked IN-TREE from ../knowledge), pushes to ECR
        │  repository_dispatch: agent-image-published {image_uri}   ─┐
        ▼                                                            │
stubs/** change ──────────────────> stubs-release.yml               │
        │  publishes sap+order_actions+snowflake zips/specs to S3   │
        │  repository_dispatch: stubs-published                     │
        ▼                                                            ▼
deploy.yml  ──[ MANUAL APPROVAL ]──>  terraform apply  ◀────────────┘
   (on: repository_dispatch types [agent-image-published, stubs-published] + workflow_dispatch)
```

- **Auto-publish**: merging to `main` under `agent/**` (or `knowledge/**`) rebuilds the image
  via `agent-build.yml`; merging under `stubs/**` republishes the stubs via `stubs-release.yml`.
  No more manual image builds / publishes.
- **Knowledge is baked in-tree**: `agent-build.yml` copies the corpus from the in-repo
  `knowledge/` folder — no pinned knowledge release, no GitHub fetch, no token. A `knowledge/**`
  change rebuilds the agent image through `agent-build.yml`'s path filter (there is no separate
  knowledge publish/release workflow).
- **Gated apply**: every path into `terraform apply` pauses on the
  [`manual-approval`](https://github.com/trstringer/manual-approval) action (pinned to
  `74d99df` / v1.12.0). It runs **before** AWS credentials are configured, so it never
  holds the deploy role. Approve by commenting `approved` on the issue it opens.
- **In-repo cascade via `repository_dispatch`**: each publisher fires a `repository_dispatch`
  at its own repo (`gh api repos/aniryou/bedrock-demo/dispatches`) only after its build job
  succeeds — `agent-build.yml` sends `agent-image-published`, `stubs-release.yml` sends
  `stubs-published`, and `deploy.yml` listens on both event types. Completion-chaining keeps the
  producer→deploy ordering correct; the `deploy-infra` concurrency group coalesces overlapping
  triggers into one apply.

The cascade no-ops safely until `DISPATCH_TOKEN` exists (each dispatch step is guarded by
`if: ${{ env.DISPATCH_TOKEN != '' }}`). A `repository_dispatch` fired with the built-in
`GITHUB_TOKEN` deliberately does **not** start a new run — hence the PAT below.

## One-time provisioning

### 1. OIDC roles (AWS) — apply the bootstrap

`bootstrap/github_oidc.tf` creates the GitHub OIDC provider + three roles (CI publish,
deploy, and the read-only PR-plan role), all trusting the single repo. Apply with the admin
creds you already use locally:

```bash
cd infra
make bootstrap                  # or: terraform -chdir=bootstrap apply
terraform -chdir=bootstrap output ci_publish_role_arn
terraform -chdir=bootstrap output ci_deploy_role_arn
terraform -chdir=bootstrap output ci_plan_role_arn
terraform -chdir=bootstrap output ecr_repository_url
terraform -chdir=bootstrap output artifacts_bucket
```

- **OIDC trust subjects (single repo).** All three roles trust `aniryou/bedrock-demo`, scoped
  by GitHub Actions subject:
  - **publish** role → `repo:aniryou/bedrock-demo:*` (assumed by `agent-build.yml` /
    `stubs-release.yml` on any ref).
  - **deploy** role → `repo:aniryou/bedrock-demo:environment:production` (assumed only by
    `deploy.yml`'s environment-gated job).
  - **plan** role → `repo:aniryou/bedrock-demo:pull_request` (read-only, assumed only by the
    `infra-ci.yml` PR-plan job).
- If the account **already** has a GitHub OIDC provider:
  `terraform -chdir=bootstrap apply -var create_github_oidc_provider=false -var existing_oidc_provider_arn=<arn>`
- The **deploy role defaults to a generated least-privilege policy** (`aws_iam_policy.deploy_perms`),
  covering exactly the services `terraform/` manages — no AdministratorAccess. To pin a specific
  managed policy instead, pass `-var deploy_policy_arn=<arn>` (note: setting this also DROPS the
  auto-attached observability policy below, so fold those grants into your override).
- **Two managed policies, one role.** The generated grants exceed the 6144-char IAM managed-policy
  cap, so they are split and both attached: `…-deploy-perms` (core services — AgentCore, Bedrock
  KB + **Guardrail** + **model-invocation logging** + **data-protection policy**, Lambda, IAM demo
  roles, Secrets, ECR/Logs/X-Ray incl. the vended-log `logs:*Delivery*` set, S3, Cloud Control) and
  `…-deploy-obs-perms` (observability add-ons — CloudWatch dashboards/alarms/anomaly + **Insight
  rules** & `cloudwatch:GetMetricData`, the SNS alert topic, **`application-signals:*`** for the
  SLOs, `bedrock:AllowVendedLogDeliveryForResource` for KB logs, the failed-ingestion metric
  filter). Effective permissions are the union. The online-Evaluations exec role and its
  `/aws/bedrock-agentcore/evaluations/*` results log group are created by `terraform/` (not
  bootstrap) and are already covered by the deploy role's `iam:CreateRole`/`PutRolePolicy` (scoped
  to `order-triage-*`) and `iam:PassRole` to `bedrock-agentcore.amazonaws.com`.

### 2. Secrets & variables (GitHub) — set ONCE on the single repo

All secrets/variables live on the one repo. Set with `gh secret set NAME -R aniryou/bedrock-demo`
(or `gh variable set` for vars). `<acct>` = AWS account id; `<ecr>` = `ecr_repository_url` output;
`<bucket>` = `artifacts_bucket` output.

| Scope | Secrets | Variables (optional) |
|---|---|---|
| Publish (`agent-build.yml`, `stubs-release.yml`) | `AWS_PUBLISH_ROLE_ARN`, `ECR_REPOSITORY_URL`=`<ecr>`, `ARTIFACTS_BUCKET`=`<bucket>`, `DISPATCH_TOKEN` | `AWS_REGION` |
| Deploy (`deploy.yml`) | `AWS_DEPLOY_ROLE_ARN`, `ARTIFACTS_BUCKET`=`<bucket>`, `AGENT_IMAGE_URI`=`<ecr>:latest`, `SNOWFLAKE_API_KEY` | `AWS_REGION`, `NAME_PREFIX`, `DEPLOY_APPROVERS`, `ENTRA_TENANT_ID`, `ENTRA_AGENT_APP_ID`, `ENTRA_OBO_SCOPE` |
| Plan (`infra-ci.yml`) | `AWS_PLAN_ROLE_ARN` | `ENABLE_TF_PLAN` |

The full set on `aniryou/bedrock-demo`: secrets `AWS_PUBLISH_ROLE_ARN`, `AWS_DEPLOY_ROLE_ARN`,
`AWS_PLAN_ROLE_ARN`, `ECR_REPOSITORY_URL`, `ARTIFACTS_BUCKET`, `AGENT_IMAGE_URI`,
`SNOWFLAKE_API_KEY`, `DISPATCH_TOKEN`; variables `AWS_REGION`, `NAME_PREFIX`, `DEPLOY_APPROVERS`,
`ENABLE_TF_PLAN`, `ENTRA_TENANT_ID`, `ENTRA_AGENT_APP_ID`, `ENTRA_OBO_SCOPE`.

- The agent build no longer needs a knowledge read token — it copies the corpus from the
  in-tree `knowledge/` folder (no GitHub fetch).
- `SNOWFLAKE_API_KEY` — the live X-API-Key for the Snowflake data Lambda (`deploy.yml`
  passes it as `TF_VAR_snowflake_api_key`). The SAP/orders stubs no longer use a key — their
  Function URLs are `AuthType=AWS_IAM`, invoked by the Gateway role via SigV4.
- `ENTRA_TENANT_ID` / `ENTRA_AGENT_APP_ID` / `ENTRA_OBO_SCOPE` — the Entra OBO production
  variables `deploy.yml` maps to `TF_VAR_entra_*`. They have **no Terraform defaults**, so
  `terraform apply` fails fast ("No value for required variable") if they're unset. (The Entra
  client *secret* is not here — it's seeded into Secrets Manager out-of-band by
  `make seed-entra-secret`, never as a `TF_VAR`.)
- `AWS_PLAN_ROLE_ARN` — the read-only role the PR-plan job (`infra-ci.yml`) assumes when
  `ENABLE_TF_PLAN=true`; `ci_plan_role_arn` from the bootstrap output.
- `DEPLOY_APPROVERS` — comma-separated GitHub logins allowed to approve (default `aniryou`).
- `ENABLE_TF_PLAN=true` — opt in to the real `terraform plan` on infra PRs (off by default
  so PRs stay green until the deploy secrets above exist).
- **Optional observability / guardrail / evaluation TF vars** (safe defaults; *not* wired into
  `deploy.yml`). Override via `terraform.tfvars` or `TF_VAR_*` only if needed: `alert_email`
  (default empty — **set this or the alarm SNS topic has no subscriber and alarms notify no one**;
  the recipient must confirm the SNS email), `enable_guardrail` (default `true`) /
  `guardrail_prompt_attack_strength` (`LOW|MEDIUM|HIGH`, default `MEDIUM`),
  `enable_online_evaluations` (default `false` — opt-in per-trace LLM-judge cost),
  `model_input_usd_per_million` / `model_output_usd_per_million` (FinOps estimate, Nova Lite
  `0.06`/`0.24`), `trace_indexing_percentage` (default `100`), and the log-retention vars
  `memory_log_retention_days` / `bedrock_invocation_log_retention_days` /
  `function_log_retention_days` (30d). To set any in the pipeline, add a `TF_VAR_*` line to
  `deploy.yml` (e.g. `TF_VAR_alert_email: ${{ vars.ALERT_EMAIL }}`).

### 3. The cascade token — `DISPATCH_TOKEN`

The cascade fires `repository_dispatch` (within the same repo); GitHub's built-in
`GITHUB_TOKEN` can't start a new run from a dispatch it raised. Create a **fine-grained PAT**
(recommended) and add it as the single `DISPATCH_TOKEN` secret on `aniryou/bedrock-demo`:

- Resource owner `aniryou`; repo access: `bedrock-demo`.
- Repository permissions: **Contents: read & write** + **Metadata: read** (fine-grained PATs
  gate the `dispatches` API under Contents). Grant Contents: read/write on `bedrock-demo`.
- (A GitHub App installation token is the longer-lived alternative; same workflow code.)

## Operating it

- **Ship a knowledge change** → merge to `main` under `knowledge/**`. The path filter triggers
  `agent-build.yml`, which rebuilds the image with the new corpus baked in, pushes it, and
  cascades to the deploy approval issue. Comment `approved` to apply.
- **Ship an agent code change** → merge to `main` under `agent/**`. Same image-publish → gated apply.
- **Ship a stub change** → merge to `main` under `stubs/**`. `stubs-release.yml` publishes
  zips/specs → gated apply.
- **Deploy manually** → run the `Deploy to AgentCore` workflow (`deploy.yml`, `workflow_dispatch`).
- **Status**: the pipeline reached a green `terraform apply` end-to-end on 2026-06-22.
  `deploy.yml` runs `infra.preflight` (a read-only access check) and then applies. The
  earlier "org SCP blocks `bedrock` / `bedrock-agentcore`" report was a preflight bug — it
  probed an action the least-privilege deploy role didn't hold, so it failed on its own IAM
  and mis-reported an SCP deny; fixed in infra #36. Bedrock was never SCP-denied.

# Playbook — deploy, teardown & rotation

The happy-path command list is in the [repo README](../../README.md#setup--usage). This
runbook covers what each target actually does, plus teardown and rotation.

## How the make targets resolve config

`make bootstrap` / `plan` / `deploy` / `destroy` resolve the required `TF_VAR_*` (snowflake
+ entra) and the bootstrap outputs from the single root **`../.env`**, and init the remote
**S3 backend** automatically — so they run from a fresh clone with no manual `terraform init`.

- `make preflight` — the read-only access check that `make deploy` runs first; validate
  offline any time with `make tf-validate`.
- `make bootstrap` — ECR repo + artifacts S3 bucket + the secret container (separate
  state). **Apply first**, and note its outputs (they feed the main stack).
- `make deploy` — `terraform apply` on the main stack, consuming the published artifacts.
- `make ingest` — triggers KB ingestion. **Required after every fresh apply** (apply
  creates the KB + data source, not the ingestion job; CI deploys do **not** run it).
- `make status` — the end-to-end smoke test: mints an Entra ROPC user token and invokes
  the live CUSTOM_JWT runtime over HTTPS.

> The agent **image is built by the [`agent`](../../../agent/README.md) folder's
> CI** (arm64 buildx → ECR, `agent-build.yml`); there is no local image build. A from-scratch
> local deploy therefore needs the component folders' "publish" workflows to have run first
> (image + stub zips + KB docs in the bucket).

## Teardown

- `make destroy` — tears down the **main stack only**, keeping the ECR image + S3
  artifacts so a subsequent `make deploy` is fast.
- `make destroy-full` — also tears down ECR / S3 / the secret container.

The stack is often torn down between demos (zero idle cost); `make deploy && make ingest`
brings it back from the kept artifacts.

## Rotation

- `make seed-entra-secret` — re-seeds the Entra OBO client secret in Secrets Manager on
  rotation (the value is kept out of TF state). The Entra agent client secret expires
  **2026-12-17** — see [`entra-obo-setup.md`](entra-obo-setup.md) Step 4.
- Snowflake key/secret rotation — re-run `make snowflake-setup`; see
  [`snowflake-bootstrap.md`](snowflake-bootstrap.md).

## Tunables

Sensible defaults ship **on** (guardrail, observability) or **opt-in** (online
evaluations). Override via `TF_VAR_*` or `terraform.tfvars`; the full annotated list with
defaults is [`../../terraform/terraform.tfvars.example`](../../terraform/terraform.tfvars.example),
and the rationale for the on-by-default choices is in ADR-0003 (guardrail), ADR-0004
(observability/FinOps), and ADR-0005 (evaluations).

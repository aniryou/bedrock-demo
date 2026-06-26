# CLAUDE.md

Guidance for working in this repo. See [README.md](README.md) for the full
architecture diagrams.

## What this is

Three FastAPI back-office stub services used as **AgentCore Gateway targets** for
the order-triage demo. Each deploys as an arm64 Lambda Function URL (via
[Mangum](https://pypi.org/project/mangum/), the ASGI→Lambda adapter) and runs locally
under uvicorn.

| Package | Routes | Gateway target | Data source |
|---|---|---|---|
| `sap_stub` | `GET /credit-status/{id}` | `sap` | in-memory dict |
| `order_actions_stub` | `POST /orders/{id}/flag` | `orders` | order status from `snowflake_stub` over HTTP |
| `snowflake_stub` | `GET /orders`, `/orders/{id}`, `/customers`, `/customers/{id}` | `snowflake` | live Snowflake SQL REST API |

## Commands

```bash
make setup          # uv sync --extra dev
make test           # pytest (FastAPI TestClient — hermetic, no network)
make lint           # ruff check .
make sap            # run sap_stub on :8088
make order-actions  # run order_actions_stub on :8089
make snowflake      # run snowflake_stub on :8090 (needs AWS creds + SNOWFLAKE_SECRET_NAME)
make lambdas        # build all three arm64 Lambda zips into ./build
```

Run a single test: `uv run pytest tests/test_snowflake_obo.py -q`.

## Auth model (important)

- **Inbound to `sap`/`orders`:** the Lambda Function URL is `AuthType=AWS_IAM`; the
  Gateway SigV4-signs each call with its execution role. There is **no app-layer key**
  on these — don't add `X-API-Key` checks to them.
- **Inbound to `snowflake_stub`:** the Function URL stays `AuthType=NONE` and the service
  authorizes itself, because the Gateway reaches it with a per-user Entra **OBO** bearer
  (TOKEN_EXCHANGE) that occupies its single egress credential slot — leaving no slot for a
  Gateway SigV4 identity, so `X-API-Key` carries the service path instead. Two paths,
  selected in `snowflake_stub/app.py:_authorize`:
  - **User (OBO):** a forwarded `Authorization: Bearer <token>` is presented to
    Snowflake with token-type `OAUTH`; Snowflake enforces that user's RBAC.
  - **Service:** otherwise a valid `X-API-Key` selects a key-pair `KEYPAIR_JWT` as the
    SELECT-only `AGENT_RO` role.
- **Authorization** (who may flag, who may read) lives in the **Cedar policy on the
  Gateway**, not in these services. The stubs enforce only business rules (e.g.
  `order_actions` flags OPEN orders only) and data access.

## Conventions

- Python 3.12, [uv](https://docs.astral.sh/uv/) for deps, `ruff` for lint
  (`line-length = 100`).
- **Prefer the standard library and existing deps over custom code.** FastAPI, Mangum, and the
  Lambda-provided `boto3` already cover the surface here — add a dependency or hand-roll a helper
  only when nothing existing fits.
- Comments and docstrings state the **what / why / how of the code's current state** — not how it
  came to be. No history, migration notes, dated proof points, or references to past versions.
- **Architecture decisions and the "how we got here" live in ADRs, not code.** This component owns
  none; cross-cutting decisions sit in the owning component's `docs/adr/` (`../infra`,
  `../knowledge`) — keep those current and consistent across the 5-component split.
- Tests are **hermetic**: mock the Snowflake SQL call and JWT signing; never require a
  running service, AWS, or network access.
- `boto3` is provided by the Lambda runtime and is never packaged into the zip;
  `boto3`/`jwt`/`cryptography` are imported lazily at their call sites so the modules
  stay unit-testable without those deps installed.
- Each service has a thin `lambda_handler.py` (`Mangum(app)`) — the deploy entrypoint.
  `app.py` holds the routes; keep all logic there.
- **After generating or editing a mermaid diagram, run the `mermaid-check` skill** and fix
  whatever it flags (parse errors, overlapping nodes/edges) before committing. The README's
  architecture diagram is mermaid.
- **Work in your own git worktree** so parallel agents don't collide on the shared checkout.
  Default location (a shared root outside the repo): `git worktree add
  ../.worktrees/bedrock-demo/<branch> -b <branch>`. After pushing the branch, remove it:
  `git worktree remove ../.worktrees/bedrock-demo/<branch>` (then `git worktree prune`).
- **Record recurring tool/command failures and their fixes here** as you hit them (a `make`
  target, a Lambda build/deploy step, an AWS call needing a specific flag) so the same dead end
  isn't rediscovered. Keep this file lean — correct stale lines rather than appending new ones.

## Deploy

`build_lambdas.sh` builds the zips; `../.github/workflows/stubs-release.yml` uploads them plus
each service's `openapi.json` to the artifacts S3 bucket on merge to `main`, then
cascades a `stubs-published` dispatch to `../infra` (Terraform), which references
the zips by `s3_key` and the specs via `aws_s3_object` data sources.

For a from-scratch deploy, run `../.github/workflows/stubs-release.yml` manually
(`workflow_dispatch`) to publish all artifacts up front; `../infra`'s `make deploy` then
consumes them (Lambda code by `s3_key` + specs via `aws_s3_object` data sources). Full pipeline
runbook: `../infra/docs/playbooks/cd-setup.md`.

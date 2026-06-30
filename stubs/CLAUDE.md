# CLAUDE.md

Guidance for working in this repo. Runtime architecture diagram in
[README.md](README.md); the build/deploy diagram in
[docs/build-and-deploy.md](docs/build-and-deploy.md).

## What this is

Three FastAPI back-office stub services used as **AgentCore Gateway targets** for the
order-triage demo. Each runs locally under uvicorn; on deploy `snowflake_stub` is a Lambda
Function URL (via [Mangum](https://pypi.org/project/mangum/), the ASGI→Lambda adapter), while
`sap_stub`/`order_actions_stub` are native Lambda targets (the Gateway invokes them directly).

| Package | Routes | Gateway target | Data source |
|---|---|---|---|
| `sap_stub` | `GET /credit-status/{id}` | `sap` | in-memory dict |
| `order_actions_stub` | `POST /orders/{id}/flag` | `orders` | order status from `snowflake_stub` over HTTP |
| `snowflake_stub` | `POST /ask` (agent) | `snowflake` | Cortex Analyst (NL→SQL over the `ORDERS_SV` semantic view) |

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

- **Inbound to `sap`/`orders`:** native AgentCore Gateway **Lambda targets** — the Gateway
  invokes each function directly (`lambda:InvokeFunction`) as its execution role. There is **no
  Function URL, no SigV4, and no app-layer key**. The Lambda receives the tool args as the event
  and the tool name in `client_context.custom['bedrockAgentCoreToolName']` — don't add HTTP or
  `X-API-Key` handling to them.
- **Inbound to `snowflake_stub`:** the Function URL stays `AuthType=NONE`; the Gateway reaches
  it with a per-user Entra **OBO** bearer (TOKEN_EXCHANGE). `POST /ask` is **user (OBO) only**:
  the forwarded `Authorization: Bearer <token>` is presented to Cortex Analyst and the SQL API
  with token-type `OAUTH`, so the generated SQL runs in that user's Snowflake context and the
  row-access policy scopes the rows. No service fallback — RLS is meaningless without a real
  user, so a missing bearer is a 401. This is the only agent-facing tool (`snowflake___ask`).
  - **Deferred (happy-path stub — come back later):** REST error mapping (a Snowflake failure
    currently surfaces as a 500, not a 502), SQL-API async (HTTP 202) + partitioned results,
    graceful degradation on a declined/failed query, and the key-pair **service-path
    `GET /orders/{id}`** status read that `order_actions` needs for its OPEN-only rule.
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
- `snowflake_stub`'s `lambda_handler.py` is `Mangum(app)` (its target is still a Function URL).
  `sap`/`order_actions` are native Lambda targets, so their `lambda_handler.py` parses the
  AgentCore tool event (`client_context.custom['bedrockAgentCoreToolName']` + the arg map) and
  calls the `app.py` route function directly — no Mangum. `app.py` holds the routes/logic.
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
the zips by `s3_key`. Only the `snowflake` target still consumes its `openapi.json` (via an
`aws_s3_object` data source); the `sap`/`orders` Lambda targets carry an inline tool schema in
the Gateway target, so their `openapi.json` is local API docs only.

For a from-scratch deploy, run `../.github/workflows/stubs-release.yml` manually
(`workflow_dispatch`) to publish all artifacts up front; `../infra`'s `make deploy` then
consumes them (Lambda code by `s3_key` + specs via `aws_s3_object` data sources). Full pipeline
runbook: `../infra/docs/playbooks/cd-setup.md`.

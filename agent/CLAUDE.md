# CLAUDE.md

Working brief for **order-triage-agent** — the Strands agent, its local tools, and the
AgentCore Runtime entrypoint. See `README.md` for full architecture diagrams and the
5-repo split; this file is the orientation an agent needs to work in the code.

## Commands

```bash
make setup     # uv venv + dev deps        (uv sync --extra dev)
make skills    # copy skills + ontology bindings + kb/ from ../knowledge
make test      # hermetic unit tests — no network, no model   (uv run pytest tests -q)
make lint      # ruff                       (uv run ruff check .)
```

- Run one test: `uv run pytest tests/test_spec.py -k test_name -q`.
- Python is pinned to 3.12; everything runs through `uv run`.
- **There is no local run target.** The runtime is Gateway-only and hard-errors without a
  user JWT + `GATEWAY_URL`. Exercise the full path through the deployed runtime (e.g. the
  order-triage-webapp OBO client), not locally.

## Layout

This agent is a **thin consumer of `agent_kit`** (the in-tree library at `../lib`). All the
agent-agnostic plumbing — prompt assembly, tool surface, `BedrockModel`, memory, identity,
Gateway client, skill/ontology/KB loaders, stream classifier, the AgentCore runtime
entrypoint — lives in `agent_kit`. This package supplies only the per-agent contract.

- `src/order_triage/`
  - `spec.py` — `SPEC`: the agent's `AgentSpec` (`agent_id`, metric namespace,
    `action_implementations`, KB tool name/description). The single per-agent surface
    `agent_kit` is driven from.
  - `runtime.py` — `app = build_app(SPEC)`. AgentCore entrypoint
    (`BedrockAgentCoreApp`, `/invocations` + `/ping`) built entirely by `agent_kit`. Needs the
    `deploy` extra; not imported by the tests.
  - `__init__.py` — package `__version__`.
- `tests/` — per-agent hermetic tests (`test_spec.py`: skill→action coverage of `SPEC`).
  The plumbing's own unit tests live in `../lib/tests`.
- `skills/`, `ontology/`, `kb/` — fetched content, gitignored (see below).
- `scripts/fetch_skills.sh`, `Dockerfile`, `Makefile`, `../.github/workflows/` (agent-ci.yml, agent-build.yml).

The Dockerfile builds with the **repo root** as the build context (it installs `../lib`
then the agent).

## How it works (orientation)

- **Gateway-only.** The backend tools — `snowflake___ask`, `sap___getCreditStatus`, `orders___flagOrder` — are **not in this repo**.
  The AgentCore Gateway serves them as MCP tools (Cedar-authorized, brokered
  on-behalf-of the user via `grant_type=TOKEN_EXCHANGE`) and they are passed into the agent
  as `extra_tools` at runtime. The agent forwards the inbound user JWT and mints no
  credentials itself.
- **Local tools** (`search_policies` → Bedrock Knowledge Base; `describe_entity` → ontology
  bindings; `load_skill`) never traverse the Gateway and are always present.
- **Skills / ontology / KB are fetched content, not code.** `make skills` copies them from the
  in-tree `../knowledge` folder into `skills/`, `ontology/`, `kb/` (all gitignored) — no GitHub
  fetch, no token. The agent degrades gracefully to an empty catalog when they're absent.

## Conventions & gotchas

- **Prefer built-ins and the existing stack over custom code.** Reach first for the standard
  library, deps already in `pyproject.toml`, and AWS-native primitives (Bedrock / AgentCore,
  Strands) — hand-roll a helper or add a dependency only when nothing existing fits.
- **Comments and docstrings state the what / why / how of the code's _current_ state** — never
  how it got there. Keep provenance, change history, dated proof points, and PR/phase references
  out of inline comments and docstrings.
- **The "how it got here" lives in ADRs, not code.** This component owns none; cross-cutting design
  decisions are recorded in the owning component's `docs/adr/` (`../infra/docs/adr/`,
  `../knowledge/docs/adr/`). Keep those current and consistent across the mono-repo when a
  decision changes.
- **After generating or editing a mermaid diagram, run the `mermaid-check` skill** and fix
  whatever it flags (parse errors, overlapping nodes/edges) before committing. The README's
  architecture diagram is mermaid.
- **`agent_kit.infra.identity` decodes the JWT payload without verifying the signature** — the
  CUSTOM_JWT authorizer already verified it upstream, and the subject is used only as a memory
  partition key, never to authorize. Never log token bytes or claim values.
- **`requestMetadata` values must stay opaque, charset-limited, and PII-free**
  (`agent_kit.agent` strips them); never put an email/UPN/raw subject into a Converse call.
- **Ontology names ≠ Snowflake fields.** The ontology (`SalesOrder.soNumber`, …) is a
  routing/governance map; the backend tools return runtime fields
  (`order_id` / `amount` / `status`). Ontology names are for routing, never tool arguments.
- **Tests must stay hermetic** — no network, no model, no AWS. Backend tools are exercised
  only on the deployed runtime.
- **ruff**: line-length 100, `select = E, F, I, UP, B`, `E501` ignored. Run `make lint`
  before committing.
- **Record recurring tool/command failures and their fixes here** as you hit them (a flaky
  `make` target, an AWS call needing a specific flag, a deploy step with a non-obvious order) so
  the same dead end isn't rediscovered.
- **Keep this file lean.** Update lines when findings change — correct a stale line rather than
  appending a new one; context budget is finite.

## Git / PRs

- Branch off `main` (don't commit to it directly). Squash-merge PRs; commit subjects follow
  conventional style (`feat(agent):`, `docs:`, `chore:`) and land on `main` as `… (#NN)`.
- **Work in your own git worktree** so parallel agents don't collide on the shared checkout.
  Default location (a shared root outside the repo): `git worktree add
  ../.worktrees/bedrock-demo/<branch> -b <branch>`. After pushing the branch, remove it:
  `git worktree remove ../.worktrees/bedrock-demo/<branch>` (then `git worktree prune`).
- CI (`../.github/workflows/agent-ci.yml`) runs ruff + the hermetic tests on every PR.

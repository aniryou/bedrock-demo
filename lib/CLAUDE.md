# CLAUDE.md

Working brief for **agent_kit** — the agent-agnostic Strands + AgentCore runtime toolkit
(src layout: `src/agent_kit/`). It holds the plumbing every agent shares; a per-agent
package supplies an `AgentSpec` and consumes `build_agent` / `build_app` to stand up a
deployable runtime. See `README.md` for the one-paragraph overview.

## Commands

```bash
make setup     # uv venv + dev deps        (uv sync --extra dev)
make test      # hermetic unit tests — no network, no model   (uv run pytest tests -q)
make lint      # ruff                       (uv run ruff check .)
```

- Python is pinned to 3.12; everything runs through `uv run`. ruff: line-length 100,
  `select = E, F, I, UP, B`, `E501` ignored.

## Public API

- **`AgentSpec`** (`spec.py`) — the frozen per-agent contract: `agent_id`,
  `metric_namespace`, `action_implementations`, the KB tool name/description, an optional
  `system_prompt_preamble`, the memory `retrieval_namespaces`, and model/region/max-tokens
  defaults. A consuming agent constructs one of these and passes nothing else.
- **`build_agent(spec, ...)`** (`agent.py`) — assembles the system prompt, tool surface,
  `BedrockModel`, and AgentCore Memory into a Strands `Agent`.
- **`build_app(spec)`** (`app.py`) — the AgentCore Runtime entrypoint factory: seeds config
  from the spec, lazy-imports `BedrockAgentCoreApp`, registers the `/invocations` invoke
  loop, and returns the app. The deploy-only import is lazy, so `import agent_kit` needs
  only the core deps.
- Also exported: `make_kb_tool`, `describe_entity`, `load_skill`, `step_events`,
  `get_config`, `Config`.

## Layout

- `src/agent_kit/`
  - `spec.py` — the `AgentSpec` contract object.
  - `config.py` — env-driven `Config.from_env()` (`lru_cache`d via `get_config()`); per-agent
    overrides via `configure(model_id=, region=, max_tokens=)`.
  - `agent.py` — `build_agent()` + system-prompt and `requestMetadata` assembly.
  - `app.py` — `build_app()` runtime entrypoint factory.
  - `stream_steps.py` — pure classifier turning Strands events into typed timeline events.
  - `infra/` — `gateway.py` (Gateway MCP client), `identity.py` (per-request user identity
    `ContextVar`), `memory.py` (AgentCore Memory session manager).
  - `knowledge/` — `skill_loader.py`, `ontology.py`, `skills.py`, `kb.py` (KB search +
    `make_kb_tool` factory), `coverage.py` (action-coverage gate + tool registry).
- `tests/` — hermetic unit tests (loaders, identity, stream classifier, request metadata).

## How it works (orientation)

- **Agent-agnostic.** Nothing under `agent_kit` may import a per-agent package; the agent
  identity, metric namespace, and action map all arrive via `AgentSpec`. The KB tool is built
  by name from the spec (no hard-coded tool name).
- **`infra/` vs `knowledge/` split.** `infra/` is the AWS-facing plumbing (Gateway, identity,
  Memory). `knowledge/` reads the fetched `skills/` + `ontology/` content and exposes the
  local tools + the action-coverage gate that asserts every skill-invoked action maps to a
  registered tool.
- **Backends are not in this package.** The Gateway-served tools are passed into `build_agent`
  as `extra_tools` at runtime; the local tools (KB search, `describe_entity`, `load_skill`)
  are always present.

## Conventions & gotchas

- **Prefer built-ins and the existing stack over custom code** (stdlib, deps already in
  `pyproject.toml`, AWS-native primitives — Bedrock / AgentCore, Strands).
- **Import siblings as absolute `agent_kit.*` paths** — consistently across all modules.
- **Comments and docstrings state the code's _current_ what / why / how** — never how it got
  there. No provenance, change history, or PR/phase references inline.
- **`import agent_kit` must succeed with only the core deps** (strands, boto3, pyyaml).
  `bedrock_agentcore` and `mcp` are lazy-imported inside `build_app` / the Gateway client —
  never at module top level.
- **Tests must stay hermetic** — no network, no model, no AWS.
- **Keep this file lean.** Correct a stale line rather than appending a new one.

## Git / PRs

- Branch off `main`; squash-merge PRs. Commit subjects follow conventional style
  (`feat(lib):`, `docs:`, `chore:`).
- CI (`../.github/workflows/lib-ci.yml`) runs ruff + the hermetic tests on every PR; an
  agent that consumes the lib re-runs its own tests too (`agent-ci.yml` is path-filtered to
  `lib/**`).

# CLAUDE.md

Working brief for **agent_kit** — the agent-agnostic Strands + AgentCore **helper toolkit**
(src layout: `src/agent_kit/`). It is a flat set of composable helpers every agent reuses.
The library has **zero control flow and makes zero configuration decisions**: the consuming
agent owns assembly (it writes `build_agent()` and the `@app.entrypoint` loop, constructing
its own `BedrockModel` with its guardrail/model config) and calls these `kit.*` helpers. There
is **no `build_app` / `AgentSpec` / `Config`**. See `README.md` for the one-paragraph overview.

## Commands

```bash
make setup     # uv venv + dev deps        (uv sync --extra dev)
make test      # hermetic unit tests — no network, no model   (uv run pytest tests -q)
make lint      # ruff                       (uv run ruff check .)
```

- Python is pinned to 3.12; everything runs through `uv run`. ruff: line-length 100,
  `select = E, F, I, UP, B`, `E501` ignored.

## Public API

A flat set of helpers re-exported from the package root (`import agent_kit as kit`):

- **`identity`** (the `infra/identity.py` module) — per-request user identity
  (`set_user_jwt` / `reset` / `current`, `actor_id` / `actor_oid`, `ANONYMOUS_ACTOR`) +
  **`extract_user_jwt(context, header_name="Authorization")`**.
- **`build_gateway_client(gateway_url, jwt)`** — the Gateway MCP client (user JWT bearer).
- **`build_session_manager(memory_id, session_id, actor_id, retrieval_namespaces, region="us-west-2")`**
  — AgentCore Memory session manager (`None` when `session_id is None`).
- **`emit_usage_metric(agent, *, namespace, agent_id, model_id="", session_id=None, actor_id="", actor_oid="")`**
  — the per-turn token-usage EMF emitter (never raises).
- **`make_kb_tool(name, description, knowledge_base_id, region="us-west-2")`** — the KB-search
  `@tool` factory; **`describe_entity`** / **`OntologyLoader`** / **`ontology_loader`**;
  **`load_skill`** / **`SkillLoader`** / **`skill_loader`**.
- **`tools_with_coverage(local_tools, action_implementations, extra_tools=None)`** /
  **`assert_action_coverage`** / **`SkillActionCoverageError`** — the coverage gate.
- **`build_system_prompt(preamble="", loader=None)`** / **`request_metadata(agent_id, ...)`**;
  **`step_events`** / **`tool_result_text`**.

## Layout

- `src/agent_kit/`
  - `prompt.py` — `build_system_prompt()` + `request_metadata()` (the `requestMetadata`
    sanitizer `_rm_value` / `_RM_DISALLOWED`).
  - `stream_steps.py` — pure classifier turning Strands events into typed timeline events.
  - `infra/` — `gateway.py` (`build_gateway_client`), `identity.py` (per-request user identity
    `ContextVar` + `extract_user_jwt`), `memory.py` (`build_session_manager`), `metrics.py`
    (`emit_usage_metric`).
  - `knowledge/` — `skill_loader.py`, `ontology.py`, `skills.py`, `kb.py` (`_kb_retrieve` +
    `make_kb_tool` factory), `coverage.py` (`tools_with_coverage` / `assert_action_coverage`).
- `tests/` — hermetic unit tests (loaders, identity, stream classifier, request metadata).

## How it works (orientation)

- **Pure toolkit — no control flow, no config decisions.** The library exposes helpers; the
  **agent owns assembly**. The agent writes `build_agent()` and the `@app.entrypoint` loop,
  constructs its own `BedrockModel` (model id, guardrails, token budget), and passes the
  agent id / namespace / action map *into* the helpers as arguments. No env reads, no
  `Config`, no factory here.
- **Agent-agnostic.** Nothing under `agent_kit` may import a per-agent package. The KB tool is
  built by name (`make_kb_tool(name, …)`), never a hard-coded tool name.
- **`infra/` vs `knowledge/` split.** `infra/` is the AWS-facing plumbing (Gateway, identity,
  Memory, metrics). `knowledge/` reads the fetched `skills/` + `ontology/` content and exposes
  the local tools + the action-coverage gate that asserts every skill-invoked action maps to a
  registered tool.
- **Backends are not in this package.** The Gateway-served tools are passed to
  `tools_with_coverage(...)` as `extra_tools` by the agent at runtime; the local tools (KB
  search, `describe_entity`, `load_skill`) are always present.

## Conventions & gotchas

- **Prefer built-ins and the existing stack over custom code** (stdlib, deps already in
  `pyproject.toml`, AWS-native primitives — Bedrock / AgentCore, Strands).
- **Import siblings as absolute `agent_kit.*` paths** — consistently across all modules.
- **Comments and docstrings state the code's _current_ what / why / how** — never how it got
  there. No provenance, change history, or PR/phase references inline.
- **`import agent_kit` must succeed with only the core deps** (strands, boto3, pyyaml).
  `bedrock_agentcore` is lazy-imported inside `build_session_manager` and `mcp` inside
  `build_gateway_client` — never at module top level.
- **Tests must stay hermetic** — no network, no model, no AWS.
- **Keep this file lean.** Correct a stale line rather than appending a new one.

## Git / PRs

- Branch off `main`; squash-merge PRs. Commit subjects follow conventional style
  (`feat(lib):`, `docs:`, `chore:`).
- CI (`../.github/workflows/lib-ci.yml`) runs ruff + the hermetic tests on every PR; an
  agent that consumes the lib re-runs its own tests too (`agent-ci.yml` is path-filtered to
  `lib/**`).

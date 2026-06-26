# CLAUDE.md

Working brief for **order-triage-webapp** — the OBO demo chat client. See
[README.md](README.md) for the full flow diagram, the two-user demo script, and the
5-repo split; this file is the orientation an agent needs to work in the code.

## What this is

A minimal FastAPI chat UI that signs a human into Microsoft Entra (auth-code), then
proxies chat to the AgentCore **OBO runtime** carrying that user's JWT — so the agent
**impersonates the signed-in user** and Snowflake RBAC/RLS decides what each user sees.
It is a runtime *caller*, not part of the deployed stack. **No AWS credentials** — the
runtime call carries only the user bearer (CUSTOM_JWT inbound).

Why a backend at all: the agent app is a **confidential** client (it has a secret), so
the auth-code→token exchange must be server-side; and the browser can't call
`bedrock-agentcore.<region>.amazonaws.com` directly (no CORS), so the backend proxies it.

Deps are four: `fastapi`, `uvicorn`, `httpx`, `python-dotenv`.

## Commands

```bash
cp .env.example .env   # then set OBO_RUNTIME_ARN (from terraform output)
./run.sh               # creates .venv, runs uvicorn on http://localhost:8000
```

- **No test or lint targets, no Makefile, no CI.** This is a demo client; exercise it by
  signing in (User A vs User B in separate browser profiles) against a live runtime.
- **The runtime must be up first** — the stack is often torn down (zero idle cost). Bring
  it up in `../infra` (`make deploy && make ingest`), read `OBO_RUNTIME_ARN` from
  `terraform output`, and set it in the local `.env`.

## Layout

- `app/main.py` — the FastAPI app: routes and config loading and the **in-memory** session
  store (`_SESSIONS`, demo-only). The full route catalog:
  - `/` — serves the single-page UI.
  - `/login` → Entra — kicks off the auth-code sign-in.
  - `/callback` — auth-code → token exchange; mints the `webapp-<40 hex>` session id.
  - `/me` — current session (display name/email).
  - `/chat` — POST `{message}`; **streams** the agent reply as newline-delimited JSON events.
  - `/logout` — drops the session.
  - `/healthz` — liveness + `runtime_set` (false when `OBO_RUNTIME_ARN` is missing/stale).
- `app/entra.py` — Entra auth-code helpers for the confidential client: `authorize_url`,
  `exchange_code`, `decode_id_claims`. Plain OAuth2 over `httpx` — **no MSAL**.
- `app/agentcore.py` — `stream_agent()` invokes the OBO runtime and yields `("delta", text)`
  / `("step", entry)` events as each NDJSON line arrives; `_parse_line` / `_is_event_noise`
  drop the runtime's leaked Strands internal event reprs so only answer text + steps reach
  the UI. The `/chat` wire envelope is one JSON object per line:
  - `{"type":"delta","text":...}` — an answer-text chunk (the UI appends it as it arrives).
  - `{"type":"step","step":...}` — an agent step entry.
  - `{"type":"done"}` — terminal success marker.
  - `{"type":"error","detail":...}` — mid-stream failure (raw runtime body stays server-side).
- `web/index.html` — the single-page UI (renders tokens as they stream).
- `run.sh`, `requirements.txt`, `.env.example`.

## How it works (orientation)

- **Config is two `.env` files.** Shared Entra app config + the client secret come from
  `../.env` (`bedrock-demo/.env`); a webapp-local `.env` holds the per-deploy bits
  (`OBO_RUNTIME_ARN`, `WEBAPP_REDIRECT_URI`). Both are read with `python-dotenv`.
- **The access token is the inbound JWT.** The `access_as_user` scope yields a token with
  `aud = api://<agent app>` — exactly what the OBO runtime's CUSTOM_JWT authorizer expects.
  The backend forwards it as the bearer and mints no AWS credentials.
- **OBO vs agent identity is the whole point.** Order reads run *as the user* (OBO) so a
  Snowflake row access policy can deny User B; customer reads run *as the agent*. The split
  is driven by the ontology classification (`SalesOrder` confidential, `Customer` not), not
  by this app.

## Conventions

- **Prefer built-ins and existing deps over custom code.** Lean on the standard library and
  the four deps already in `requirements.txt`; the Entra flow is deliberately plain OAuth2
  over `httpx` (no MSAL) — keep it that way unless a dependency genuinely earns its place.
- **Comments and docstrings state the what / why / how of the code's _current_ state** —
  never how it got there. Keep change history, migration notes, dated proof points, and
  PR/phase references out of inline comments and docstrings.
- **The "how it got here" lives in ADRs, not code.** This repo owns none; the OBO and
  classification decisions are recorded in the owning repos' `docs/adr/`
  (`../infra/docs/adr/0001`, `../knowledge/docs/adr/0001`). Keep those
  current and consistent across the 5-repo split when a decision changes.
- **Never log token bytes or claim values, and never leak the upstream runtime body to the
  browser.** `decode_id_claims` reads name/email for display only (no signature check, never
  for authz); the raw runtime error stays server-side, correlated by the opaque session id.
- **Record recurring tool/command failures and their fixes here** (e.g. a runtime invoke that
  needs a specific header or a deploy step with non-obvious ordering) so the same dead end
  isn't rediscovered.
- **Keep this file lean.** Update lines when findings change — correct a stale line rather
  than appending a new one; context budget is finite.

## Gotchas

- **AgentCore requires a session id ≥ 33 chars** (`X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`);
  `/callback` mints `webapp-<40 hex>` to satisfy it.
- **The runtime stream leaks Strands internal event reprs** (`tool_use_stream`, `<strands…`,
  lifecycle objects) — sometimes tens of KB each. They're dropped in `agentcore.py`; if the UI
  shows raw `{'type': …}` blobs, extend `_EVENT_NOISE_MARKERS`.
- **`_SESSIONS` is in-process** — fine for the local demo, but a multi-instance deploy needs a
  shared session store.
- **Don't `source .env`.** `python-dotenv` does *not* tilde-expand, so the `~`-leading client
  secret is read literally and correctly; a shell `source` would mangle it.
- **`OBO_RUNTIME_ARN` is recreated each deploy** — read it from `terraform output`, never
  hardcode. A missing/stale ARN surfaces as a 500 on `/chat` (and `runtime_set:false` on
  `/healthz`).

## Pointers

- Full flow, prerequisites, two-user demo, and the phase-2 (App Runner) deploy sketch:
  [README.md](README.md).
- OBO decision + runbook: `../infra/docs/adr/0001-user-impersonation-obo.md`, `../infra/docs/playbooks/entra-obo-setup.md`.
- Why order vs customer split: `../knowledge/docs/adr/0001` + `snowflake/rls.sql`.

## Git / PRs

Branch off `main` (don't commit to it directly); squash-merge PRs with conventional subjects
(`feat(webapp):`, `docs:`, `chore:`). There is no CI in this repo yet.

**Work in your own git worktree** so parallel agents don't collide on the shared checkout.
Default location (a shared root outside the repo): `git worktree add
../.worktrees/bedrock-demo/<branch> -b <branch>`. After pushing the branch, remove it:
`git worktree remove ../.worktrees/bedrock-demo/<branch>` (then `git worktree prune`).

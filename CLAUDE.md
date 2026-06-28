# CLAUDE.md — mono-repo root

`bedrock-demo` is the order-triage AgentCore demo. Each top-level folder has its **own
`CLAUDE.md`** — read the folder's file when you work in it; this root file only covers what
spans folders.

| Folder | What it is | Folder brief |
|---|---|---|
| `knowledge/` | ontology + skills + KB (source of truth) | `knowledge/CLAUDE.md` |
| `lib/` | `agent_kit` — agent-agnostic Strands + AgentCore toolkit (consumed by `agent/`) | `lib/CLAUDE.md` |
| `agent/` | Strands agent + AgentCore Runtime entrypoint (thin `agent_kit` consumer) | `agent/CLAUDE.md` |
| `stubs/` | 3 FastAPI back-office stubs (SAP · orders · Snowflake) | `stubs/CLAUDE.md` |
| `infra/` | Terraform orchestrator (provisions the live AWS stack) | `infra/CLAUDE.md` |
| `app/` | FastAPI OBO chat client (the demo driver) | `app/CLAUDE.md` |

The pipeline: **knowledge → agent → infra → live**, with **stubs** as the agent's Gateway
targets and **app** driving the deployed runtime. Region `us-west-2`, model Nova Lite. The
runtime architecture and the deploy cascade are in [`README.md`](README.md).

## Cross-folder facts (mono-repo specifics)

- **One config file: the root `.env`** (gitignored). `infra/` and `app/` read it as `../.env`
  — the nesting depth is one level, so that path resolves to this root. Holds AWS, Entra, and
  Snowflake credentials; never commit it.
- **The agent bakes knowledge in-tree.** `agent/scripts/fetch_skills.sh` copies skills +
  bindings + KB from `../knowledge` (no GitHub fetch, no `SKILLS_TOKEN`). A `knowledge/` change
  on `main` therefore rebuilds the agent image via `agent-build.yml`.
- **CI/CD is a set of path-filtered workflows** in `.github/workflows/` (per-folder `*-ci`,
  plus `agent-build.yml` / `stubs-release.yml` publishers, plus the human-gated `deploy.yml`).
  Each runs only when its folder changes. Jobs set `working-directory:` (or `-chdir=`) to the
  folder. Full table in `README.md`; pipeline runbook in `infra/docs/playbooks/cd-setup.md`.
- **Deploy is human-gated.** `deploy.yml` blocks on a manual approval before any AWS creds are
  configured, then `terraform apply`s against live remote state. Its OIDC trust is
  `repo:aniryou/bedrock-demo:environment:production` — set in `infra/bootstrap/github_oidc.tf`.
- **Decisions live in ADRs, not code.** `infra/docs/adr/` (system/OBO/observability) and
  `knowledge/docs/adr/` (ontology privilege). Keep them current and consistent across folders.
- **Diagrams are generated** — don't hand-edit `infra/docs/**/*.svg`/`*.png` (regenerate from
  their `.py` sources); run the `mermaid-check` skill after editing any mermaid block.

## Conventions

- **Prefer AWS-native / built-ins / existing deps over custom code** (each folder restates this
  for its stack). Comments state the code's *current* what/why/how — never how it got there.
- Branch off `main`; PRs are squash-merged once the relevant path-filtered CI is green. Commit
  subjects are conventional (`feat(agent):`, `docs:`, `chore:`).

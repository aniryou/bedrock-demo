# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The **knowledge layer** for the [order-triage agent](../agent/README.md): a file-based **ontology** plus the **skills** (curated procedures) and **KB** that bind into it. There is no graph database — the YAML/markdown source is the source of truth, `git` is the audit log, and the `build/` scripts compile the source into two JSON artifacts the agent consumes. You author source; the build validates and compiles.

Runtime deps are minimal (`pyyaml`, `jsonschema`); CI runs on Python 3.13.

## Commands

```bash
pip install -r requirements.txt        # or use the checked-in .venv/

python build/validate.py               # validate + compile ontology  -> build/ontology.compiled.json
python build/bindings.py               # validate + resolve skill/KB refs -> build/bindings.json (+ bindings.md)
python build/lineage_report.py         # source-of-truth / maturity rollup -> build/lineage.{md,csv}
python build/render_ontology.py        # interactive graph -> build/ontology.html (+ ontology-summary.md)
```

There is **no test framework and no linter**. `validate.py` and `bindings.py` *are* the checks — they exit non-zero on any schema or referential error and run the full document each time (there is no "single test" to run; the suite is fast). Run both before committing. Order matters: run `validate.py` first (it writes the compiled ontology), then `bindings.py` (it resolves against the same source).

## The one workflow gotcha: committed artifacts must not drift

`build/ontology.compiled.json` and `build/bindings.json` are **committed**, and CI gates them with `git diff --exit-code`. After editing any source you must regenerate and commit them, or CI fails:

```bash
python build/validate.py && python build/bindings.py
git add build/ontology.compiled.json build/bindings.json   # commit alongside your source change
```

**Never hand-edit the compiled JSON** — the compile is not a pass-through (see "compile enriches" below), so hand edits will not survive regeneration and will trip the drift gate.

The `*.md` / `*.csv` / `.html` outputs are generated and **git-ignored** (CI re-uploads them as artifacts each run).

## Architecture

**Reference everything by `apiName`; nothing nests, and binding is one-way.** Links, backings, skill/KB bindings, and policies all point at stable `apiName` identifiers. Skills and KB point *into* the ontology — nothing in the ontology points back. Composite keys are allowed (`primaryKey` may be a list).

**The ontology is split into layers that merge into one document.** `validate.py` reads `ontology/_meta.yaml`, `datasources.yaml`, `object-types.yaml`, `link-types.yaml`, `action-types.yaml` in order and merges them by top-level key. Each file must contribute **disjoint** top-level keys — a key appearing in two layers fails the merge. (Only a first set of MVP actions is defined; the rest of the A/B/C catalog still comes from the work-stream specs.)

**Validation is two-stage** (`validate.py`): first JSON Schema Draft 2020-12 against `schema/ontology.schema.json`, then Python referential-integrity checks that schema can't express — link endpoints, action targets, `primaryKey`/`titleProperty` components resolving to declared properties, backing/source datasources existing in the registry, and duplicate `apiName`s. A property is **either** source-backed (`source`/`column`, where `column` may be pending) **or** `managed: true` — mutually exclusive, enforced here.

**The compile enriches — `ontology.compiled.json` ≠ merged source.** `enrich_authority()` derives per action: `authority` = `user` when the action `mutates` enterprise state **or** its target object's `classification` is `confidential`/`restricted`, else `agent`; an explicit `authority` on the action overrides (recorded as `authoritySource: declared` vs `derived`). It also stamps `targetClassification`. This is the single declarative field the consuming agent's credential-routing reads: **the ontology declares *what* is privileged, never *how* it is enforced** (no IdPs, scopes, or role names — see `docs/adr/0001-ontology-privilege-classification.md`).

**`bindings.py` builds the reverse index and is the cross-layer drift gate.** Skills are authored as `skills/*.skill.md` (YAML frontmatter + markdown procedure body — the form the agent fetches) or `skills/examples/*.skill.yaml` (metadata-only examples — validated but **not** fetched by the agent). A skill's frontmatter declares `appliesTo` (`objectTypes`/`linkTypes`/`actions` — its structural trigger), `invokes` (actions), and `reads` (`objectTypes`/`datasources`); `preload: true` marks a doctrine skill that is intentionally not entity-bound. KB docs are registered in `kb/index.yaml`, each (and each chunk, where possible) declaring what it `concerns`. `bindings.py` validates manifests against `schema/bindings.schema.json`, resolves **every** reference (a dangling `apiName`, or a missing KB `path`, **fails the build** — this is how a renamed/removed entity is caught), expands link references to their endpoint objects, and emits `build/bindings.json` — the reverse index from each `apiName` to the skills/KB/actions touching it (`index.{objectType,linkType,action}`), plus a `coverage` block.

**Coverage gaps are advisory and never fail the build** — actions with no governing skill, skills bound to nothing (preload excluded), entities with no skill/KB, and skills reading a datasource with no mock backend in the [stubs](../stubs/README.md). `lineage_report.py` likewise treats the source-of-truth registry as a maturity view, listing entities with no defined system of record (the migration backlog).

## Consuming side

The order-triage agent copies only the top-level `skills/*.skill.md` (not `examples/`) into its `SKILLS_DIR` at build/CI time from the in-tree `../knowledge` folder (no GitHub fetch, no token); its loader renders an enriched catalog from each file's frontmatter `description` plus the `appliesTo` ontology entities/actions, and returns the markdown body on demand via the `load_skill` tool. That consuming-side wiring lives in the **[agent](../agent/README.md)**, not here. A skill file is therefore both an authored procedure and a machine-checked ontology binding. The placement discipline (KB → Skills → Ontology, hardening upward) and the feedback loop are documented in `docs/architecture/architecture-primer.md`; the privilege/authority model in `docs/adr/0001-ontology-privilege-classification.md`; the binding model in `docs/architecture/associations.md`.

## Conventions

- **Prefer the standard library and the two runtime deps over custom code.** The build scripts lean on `pyyaml` + `jsonschema` (Draft 2020-12) — express new rules as schema or a small stdlib check before adding a dependency or hand-rolling a parser.
- **Inline comments / docstrings state the what / why / how of the current source and scripts** — never how they got there. Keep change history, migration notes, and dated references out of the YAML, markdown, and build code; `git` is the audit log.
- **The "how it got here" lives in ADRs** (`docs/adr/`, currently `0001`). Record model-level decisions (privilege/classification, catalog structure) there, keep them current as the model evolves, and consistent with the consuming repos in the 5-repo split — not in scattered comments.
- **After generating or editing a mermaid diagram, run the `mermaid-check` skill** and fix whatever it flags (parse errors, overlapping nodes/edges) before committing. The README and the `render_ontology.py` output (`build/ontology-summary.md`) emit mermaid.
- **Work in your own git worktree** so parallel agents don't collide on the shared checkout. Default location (a shared root outside the repo): `git worktree add ../.worktrees/bedrock-demo/<branch> -b <branch>`. After pushing the branch, remove it: `git worktree remove ../.worktrees/bedrock-demo/<branch>` (then `git worktree prune`).
- **Record recurring tool/command failures and their fixes here** (e.g. a `validate.py` / `bindings.py` run that trips the committed-artifact drift gate) so the same dead end isn't rediscovered.
- **Keep this file lean.** Update lines when findings change — correct a stale line rather than appending a new one; context budget is finite.

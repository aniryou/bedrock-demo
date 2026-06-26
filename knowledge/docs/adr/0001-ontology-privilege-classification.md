# ADR-0001: Classify action privilege and data sensitivity in the ontology

**Status:** Accepted — partially implemented (items 1, 2, 4 done; 3 withdrawn; 5 open — see Action Items)
**Date:** 2026-06-20
**Deciders:** order-triage-knowledge owner; work-stream A/B/C spec owners; platform + security. **Consumer:** order-triage agent team (see [infra ADR-0001](../../../infra/docs/adr/0001-user-impersonation-obo.md)).

## Context

The ontology is **enterprise / domain-wide** — 42 object types across 3 work-streams — and the order-triage agent is just **one consumer**. A downstream need has emerged (detailed in [infra ADR-0001](../../../infra/docs/adr/0001-user-impersonation-obo.md), "on-behalf-of user impersonation"): agents must decide, **per action**, whether to act on their own service identity or to impersonate the requesting human (and let the backend enforce that user's permissions). For that decision to scale across many agents — rather than being re-implemented in each — it has to be a **declarative property carried by the ontology**, because:

- **Privilege/sensitivity is intrinsic to the action and the data**, not to any one agent. It is exactly the kind of domain fact the ontology is the source of truth for, and the opposite of an agent-specific heuristic (which the enterprise-scope rule says must never be pushed up).
- The ontology already has the **seeds**:
  - A `classification` field exists on object types and properties (e.g. `CreditProfile: classification: confidential` in `ontology/object-types.yaml`); the schema also permits it at property and datasource level.
  - An `ontology/governance.yaml` layer was once **scaffolded but left empty** (`roles`, `classifications`, `objectPolicies`, `actionPolicies`, `retention`) as the place this decision would land. In the end the model below was implemented **without** it — classification lives inline on object types and `authority` is **derived** in `build/validate.py` — so the empty governance layer has been **retired**. Reintroduce a policy layer only if/when actual work-stream policy data (roles, object/action policies, retention) needs to be carried.

## Decision

Carry privilege/sensitivity on **two distinct axes**, both sourced from the work-stream specs and validated by the build:

1. **Data classification** (formalize the existing field): a typed enum `public | internal | confidential | restricted` on object types and properties. Drives downstream data-layer controls (e.g. Snowflake masking / row-access) and informs whether a *read* needs the user's identity.
2. **Action authority** (new): `authority: agent | user` on `actionType`. `user` means executing the action requires the **human's** authority (the consumer must impersonate); `agent` means the consumer may act on its own identity. A **default is derived in the build** — `user` if the target object is `confidential`+ **or** the action mutates state; `agent` otherwise — with an **explicit override** permitted for exceptions.

Both fields are added to `schema/ontology.schema.json`, populated from the work-stream specs, compiled by `build/validate.py` into `build/ontology.compiled.json`, and shipped to consumers through the existing pinned-release + CD cascade.

**The boundary that must hold — declare the *what*, never the *how*.** The ontology says "this action requires user authority" and "this data is confidential." It must **not** name IdPs, OAuth scopes, Snowflake role names, or credential-provider ARNs — those are *consumer binding config* and live in the consuming agent/platform (see [infra ADR-0001](../../../infra/docs/adr/0001-user-impersonation-obo.md)). This mirrors the existing discipline that `datasource` is "source-of-truth, not a runtime table."

## Options Considered

### Where privilege is classified

#### Option A: In each consuming agent (per-tool flags in code)
| Dimension | Assessment |
|-----------|------------|
| Ownership | Wrong layer — duplicated in every agent |
| Drift risk | High — agents diverge |
| Auditability | Scattered |

**Rejected** — defeats the enterprise-scope model; the same action would be classified N times.

#### Option B: In the ontology (`classification` + `authority`) — **chosen**
| Dimension | Assessment |
|-----------|------------|
| Ownership | Correct — enterprise/work-stream owns it |
| Reuse | Every consumer inherits it for free |
| Auditability | Single PR-gated source; can **generate** consumer authz config |

**Pros:** declarative, inherited, governed. **Cons:** schema change; build must compute defaults and validate; classification becomes security-relevant (review gating).

#### Option C: Only at the platform/IdP (Cedar scopes, IdP roles)
**Rejected as the source of truth** — IdP/Cedar scopes capture *who may*, but not *what data is sensitive*, and the IdP is not the domain authority on "which actions are privileged." (It is used **downstream** of Option B, generated from it.)

### Declaring `authority` vs deriving it from `classification`
Chosen: **derive a default + allow override.** Pure derivation can't capture exceptions (a non-mutating read of `internal` data that policy still wants user-attributed); pure hand-declaration means classifying every action by hand. The hybrid keeps the common case automatic and the exceptions explicit.

## Consequences

**Easier**
- One declarative source of privilege; every consuming agent inherits it; new actions inherit policy automatically.
- Consumer authorization config (Cedar policies, credential routing) can be **generated** from the same classification.
- Fully auditable — privilege changes are gated PRs against the work-stream specs.

**Harder / new burden**
- Schema change; `build/validate.py` must compute the default and validate the enum.
- Classification becomes **security-relevant** — it needs work-stream sign-off and review gating, not casual edits.
- Consumers must honor it (e.g. a startup coverage check that every `user`-authority action has an impersonation-capable credential — implemented on the consumer side).

**Revisit**
- The exact enum values and the derivation rule once the work-stream specs land.
- Whether property-level `classification` should drive column-level masking downstream.

## Action Items
1. [x] Add `authority` (enum `agent|user`) to the `actionType` definition and formalize the `classification` enum on object types + properties in `schema/ontology.schema.json`.
2. [x] Implement the default-derivation + enum validation in `build/validate.py`; surface `authority` in `build/ontology.compiled.json` (and reverse-index in `build/bindings.py` if useful to consumers).
3. [~] **Withdrawn.** Originally: populate `ontology/governance.yaml` from the work-stream specs. The classification/authority model shipped without a governance layer (classification inline; authority derived), so the empty `governance.yaml` layer was removed. Reintroduce a policy layer only if/when real roles/object-/action-policies/retention data needs to be carried.
4. [x] Classify the existing actions (e.g. `raiseException`, `approveCreditLimit`) and confirm the inline object `classification` tags.
5. [ ] Cross-reference the consumer-side binding in [infra ADR-0001](../../../infra/docs/adr/0001-user-impersonation-obo.md); coordinate the release/tag the agent pins to.

## References
- [infra ADR-0001](../../../infra/docs/adr/0001-user-impersonation-obo.md) — on-behalf-of user impersonation (the consumer that drives this need).
- `ontology/object-types.yaml`, `ontology/action-types.yaml`, `schema/ontology.schema.json`, `build/validate.py`.
- Internal memory: `knowledge-repo-enterprise-scope`.

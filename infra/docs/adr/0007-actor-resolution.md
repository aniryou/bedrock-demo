# ADR-0007 — Render-time actor resolution for the dashboards

**Status:** Accepted
**Date:** 2026-06-24
**Deciders:** repo owner
**Related:** ADR-0001 (OBO / identity), ADR-0004 (observability/FinOps), `order-triage-agent` `identity.py`/`runtime.py`

## Context

The FinOps "Top actors by tokens" leaderboard ranked the **opaque Entra `sub`** (e.g.
`hcdG6kYx…`), which reads as broken next to the human-legible session ids beside it. The `sub`
is the AgentCore Memory `actor_id` and is a **pairwise pseudonym** — unique per user *per app*,
not resolvable by any directory API. Only the Entra `oid` (directory object id) is resolvable,
via Microsoft Graph `/users/{oid}`.

The PII posture is non-negotiable: stored telemetry (the unmasked runtime `-DEFAULT` log group,
`requestMetadata.actor` in the model-invocation log, Contributor Insights keys) must never carry
email/UPN/name. The model-invocation log masks only 5 managed PII identifiers, and email/UPN are
not managed identifiers, so any write-time injection of a name is stored unmasked permanently.

## Decision

Resolve the actor to a display name **only at render time**, keeping every stored byte opaque.

1. **Agent** (`order-triage-agent`): emit the `oid` as an additional `actor_oid` EMF field. The
   `sub` stays the Memory `actor_id` (no re-partition). Both are opaque GUIDs, never used to
   authorize.
2. **`actor_oid` Contributor Insights rule** ranks token spend by oid.
3. **A CloudWatch custom-widget Lambda** (`actor_resolver.py`, stdlib `urllib` only) reads the
   top-N oids from that rule and batch-resolves them via Graph (`$batch /users/{oid}`) using an
   **app-only** Entra app (`User.Read.All`, admin-consented, client-credentials). The resolved
   name exists only in the Lambda's render path and the operator's browser.
4. The FinOps "Top actors" widget becomes the custom widget (`leaderboard` mode, top-10). The
   Governance per-turn audit table likewise becomes a custom widget (`audit` mode: Logs Insights
   over the model-invocation log + Graph), reading `requestMetadata.actor_oid`. **Opt-in** via
   `enable_actor_resolution` (default false) — off keeps the native widgets and creates zero new
   resources.

## Options considered

- **Render-time Graph resolution (chosen).** Production-faithful; telemetry stays opaque.
- **Operator-maintained sub→alias map.** Lighter (no Entra app), but stale and unscalable; PII-safe
  only if aliases are non-name handles.
- **Inject email/UPN into telemetry.** Rejected — unmasked group + non-managed identifier =
  permanent unmasked PII.
- **Switch the Memory `actor_id` to `oid`.** Rejected — re-partitions existing memory for no gain;
  emitting `oid` as a separate field is sufficient.

## Consequences

- The actor leaderboard becomes human-readable without weakening the PII posture.
- New out-of-band setup: an Entra app-only registration (`entra/` `graph_resolver`) + admin
  consent + a client secret seeded via `make seed-graph-secret` (kept out of TF state, like the
  OBO secret). The feature lights up only after the agent redeploys (emitting `actor_oid`).
- Custom-widget Lambdas are invoked with the **dashboard viewer's** IAM identity, so a non-admin
  viewer needs `lambda:InvokeFunction` on `${name_prefix}-actor-resolver`.

## Risks

- **Graph resolvability.** `oid` resolves for directory users; guests/MSAs/service principals or
  deleted users may not. The widget degrades to a short oid per row — never blanks.
- **Custom widget = custom glue** (against the "AWS-native first" convention), justified because
  CloudWatch has no native key→label mechanism; it is a normal Lambda (has drift detection), but
  the Graph secret seeding is out-of-band (no drift detection, like ADR-0001's OBO secret).

## Action items

- [x] Agent emits `actor_oid` (order-triage-agent#32).
- [x] `actor_oid` rule + resolver Lambda + opt-in wiring (this change).
- [ ] Operator: `make entra-tf` (creates `graph_resolver` + admin consent) → `make
      seed-graph-secret` → set `enable_actor_resolution = true` + `graph_resolver_secret_name` →
      `make deploy`. Verify the FinOps widget renders names after one live invoke.
- [x] Governance audit table's actor column resolved via the same Lambda (`audit` mode).

## References

- Microsoft Graph `User.Read.All` (app-only), `$batch`. Entra `oid` vs pairwise `sub`.
- CloudWatch custom widgets (Lambda-backed dashboard widgets).

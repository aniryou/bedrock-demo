# DESIGN AUDIT — AgentCore Observability Dashboards

**Question:** Are the 7 CloudWatch dashboards faithful to the observability spike, and why do they feel underwhelming? Can they be merged?
**Scope:** the seven `aws_cloudwatch_dashboard` resources in [dashboards.tf](../../terraform/modules/observability/dashboards.tf) + supporting [queries.tf](../../terraform/modules/observability/queries.tf) / [alarms.tf](../../terraform/modules/observability/alarms.tf) / [slo.tf](../../terraform/modules/observability/slo.tf), reviewed **live** in the console (acct `953472632913` / `us-west-2`) and against [OBSERVABILITY-SPIKE.md](observability-spike.md) + [OBSERVABILITY-IMPL-PLAN.md](../playbooks/observability-impl-plan.md).
**Method:** live walkthrough of all 7 boards at a 1-week window + IaC read + the spike/plan intent, then a multi-agent audit (5 design/faithfulness/data lenses → 3 adversarial verifiers → synthesis). Corrections from the adversarial pass are folded in; refuted findings are dropped.
**Date:** 2026-06-24.

---

## 1. Bottom line

**You're right on both counts — and the sharper reason is informative.** The boards feel underwhelming not mainly because they're broken, but because **the layout spends premium canvas on near-zero information**: golden-signal `singleValue` tiles are `height=4–5` holding a *single digit* ([dashboards.tf:32-51](../../terraform/modules/observability/dashboards.tf#L32), [:218-257](../../terraform/modules/observability/dashboards.tf#L218)), the Incident alarm strip reserves `height=4` for a one-row chip strip ([:145](../../terraform/modules/observability/dashboards.tf#L145)), and ~30% of widgets are cross-board duplicates. The demo's idle traffic (**~2 invocations in the whole week**) then amplifies that whitespace into "looks broken."

**And yes, merge — because merging is *more* faithful to the original intent, not a retreat from it.** The spike framed the deliverable as *"the single pane"* ([SPIKE §5.6](observability-spike.md)) and the impl plan's **P3.2 specified ONE "Runtime dashboard."** The shipped 7 audience boards are an unannotated scope expansion past the plan. The recommendation is **consolidate 7 → 4 AND ship the density fixes in the same change** — consolidation alone still leaves sparse boards; density fixes alone leave the drift and duplication.

**The hashed actor is a *presentation* failure on top of a *correct* security decision.** It's the Entra `sub` claim, deliberately kept opaque so no email/UPN ever lands in telemetry. The fix is a **render-time resolution layer**, never "log the email" (which would be permanently unsafe — see §4).

---

## 2. The hashed actor — root cause and the PII-safe fix

### What you're seeing
On **FinOps → "Top actors by tokens"** the legend ranks `1. hcdG6kYxFFiOLvRGt5Z7CeQNYi8Q0…` and `2. 5wsUTACc7FQN7tMJ2nxCrivv6dun7…`. The same opaque value appears as the rightmost `requestMetadata.actor` column (`hcd…`) on the **Governance** audit table. The tell that it looks broken: the **"Top sessions"** panel *right beside it* shows perfectly readable ids (`status-check-…`, `webapp-689f928abb…`).

### Why it's opaque (this is by design, confirmed in code + plan)
- `identity.actor_id()` returns the verified Entra **`sub`** claim (fallback `oid`) — a pairwise pseudonymous GUID — to use as the Memory partition key ([identity.py:85-91](../../../agent/src/order_triage/identity.py#L85)).
- That `sub` flows into the EMF token line's `actor_id` root field ([runtime.py:76](../../../agent/src/order_triage/runtime.py#L76)) → the FinOps Contributor Insights rule keyed on `$.actor_id` ([queries.tf:16](../../terraform/modules/observability/queries.tf#L16)); and into `requestMetadata.actor` ([agent.py:101](../../../agent/src/order_triage/agent.py#L101)) → the audit tables.
- `agent.py` **intentionally** keeps these opaque: *"Opaque ids only — never PII"* and `_rm_value` even strips `@`. The impl plan records the same: *"actor = Entra sub GUID, opaque … never email/name."*

### The hard constraint (why you can't just "show the email")
The FinOps Contributor Insights rules read the runtime **`-DEFAULT` log group, which is UNMASKED** ([monitoring.tf:42](../../terraform/modules/observability/monitoring.tf#L42) — no data-protection policy). Even the *masked* `modelinvocations` group would not catch a UPN: the agent's `@`-strip turns `anil@contoso.com` into `anilcontoso.com`, which no longer matches the managed `EmailAddress` identifier ([invocation_logging.tf:17](../../terraform/modules/observability/invocation_logging.tf#L17)), and **masks are non-retroactive**. So **any write-time email/UPN injection is permanently unsafe.** Resolution must happen at render time or at the edge.

### Recommended fix — **IDR-1: render-time resolution via a CloudWatch custom-widget Lambda**
A `type=custom` widget invokes a Lambda at panel load; the Lambda reads the top-N subs (`GetInsightRuleReport` / Logs Insights), batch-resolves them via Microsoft Graph (`GET /users/{id}` or `$batch`), and returns HTML. **The GUID→name mapping exists only transiently in the render path and the operator's browser — never in a log, metric, or Contributor Insights key.** PII verdict: **SAFE.** Apply to all three opaque surfaces: FinOps leaderboard, Governance table, and the Security caller-identity panel. Effort: **HIGH** (new Lambda + Entra app registration with `User.Read.All` client-credentials, secret in Secrets Manager, Graph batching/caching). Pair with a static fallback bucket for unresolvable subs (service principals, deleted users).

**Ship this S-effort relabel *now*, before the Lambda:** retitle the tile `"Top actors by tokens (opaque Entra subject — by PII design)"` with a markdown subtitle pointing resolution at the OBO → Snowflake `QUERY_HISTORY` path. That alone makes the opacity read as *intentional* next to the readable session panel.

| Option | PII verdict | Note | Effort |
|---|---|---|---|
| **IDR-1 render-time Graph Lambda** ✅ | **Safe** | recommended; telemetry stays opaque, name only in render path | High |
| IDR-2 `sub`→alias lookup, render-time join | Safe *iff* alias is a non-PII handle | goes stale, needs an owner | M |
| IDR-3 emit low-cardinality non-PII attr (dept/team) | Safe *with* in-code claim allow-list | answers "which org unit", not "which person"; best chargeback cut; needs the live token to carry the claim | L–M |
| IDR-4 resolve in the webapp | Safe for telemetry | abandons the dashboard as the resolution surface | High |
| IDR-5 inject email/UPN at write time | **UNACCEPTABLE** | unmasked group + UPN not a managed identifier + `@`-strip defeats masking | — |

> Also reject any proposal to relax `_rm_value` to "allow `@` so emails read nicely" — that one change reintroduces an unmasked-PII surface across **every** Converse record.

---

## 3. Faithfulness scorecard vs. spike + impl-plan

| Dimension | Intent | As built | Verdict |
|---|---|---|---|
| **Dormant-native surface lit up** | vended metrics, gen_ai/token EMF, model-invocation log behind PII mask, alarms, anomaly band, OBO/Cedar/Guardrail — all AWS-native | exactly this | ✅ **Faithful** — the spike's central thesis is delivered |
| **Board count** | "the single pane"; P3.2 = **ONE** "Runtime dashboard" | **7** audience boards, never amended in plan | ⚠️ **Drift (high)** — over-build, no ADR/P3.2 authorization |
| **Drill path** | header copy promises "metric tile → session.id-filtered trace → trace → log" ([:1-6](../../terraform/modules/observability/dashboards.tf#L1)) | implemented on **no** board; only Incident's static board-level deep-links exist ([:139](../../terraform/modules/observability/dashboards.tf#L139)) | ⚠️ **Drift (medium)** — aspirational copy presented as built |
| **Exec tile drill-down** | header: "each tile links down to its dashboard" ([:216](../../terraform/modules/observability/dashboards.tf#L216)) | no tile carries a link; CloudWatch metric/singleValue tiles **cannot** | ⚠️ **Drift (medium)** — structurally unimplementable as written |
| **Feedback eval** | evals enabled → scores populate | banner keyed on the config flag ([:474](../../terraform/modules/observability/dashboards.tf#L474)) says **ENABLED** while the panel is empty (scoring blocked by `AgentSpanMappingException`, ADR-0005) | ⚠️ **Drift (high)** — makes a broken state look healthy |
| **Latency semantics** | one golden-signal "latency" | **three** definitions: Exec p99 App-Signals ~45s ([:233](../../terraform/modules/observability/dashboards.tf#L233)), Ops avg vended ~556ms ([:42](../../terraform/modules/observability/dashboards.tf#L42)), SLO p99 vended ≤5s ([slo.tf:22](../../terraform/modules/observability/slo.tf#L22)) | ⚠️ **Drift (medium)** — unreconciled, ~80× apart |
| **Actor attribution** | opaque-by-design (never email/UPN) | opaque Entra sub on FinOps/Governance | ✅ **Faithful to intent** — but presentation undercuts it (§2) |
| **Caller-identity audit** | audit the *user* | groups by `identity.arn` (always the runtime role) → audits the runtime ([:412](../../terraform/modules/observability/dashboards.tf#L412)) | ⚠️ **Drift (high)** — semantic bug; title over-promises |
| **Cost legibility** | readable $ for leadership | `min/1e6*rate` → `9.61E-3` sci-notation ([:243](../../terraform/modules/observability/dashboards.tf#L243), [:314](../../terraform/modules/observability/dashboards.tf#L314)) | ⚠️ **Drift (low)** — legibility, not correctness |

**Net:** broadly faithful in *substance* (the right native primitives are wired and most panels populate over a week), but drifted on *scope/framing* and on four panels whose copy overstates what's actually wired.

---

## 4. Consolidation — 7 → 4 boards

**Decision: N = 4.** This honors the spike's plural "dashboard(s)," makes the merged Operations board *literally* P3.2's "Runtime dashboard" as a subset, and preserves the three real IAM/share audiences (engineering, finance, security-compliance) plus a thin leadership rollup. N is a *decision, not a default*: if the demo narrative is purely "single pane," N=1–2 is more faithful; N=4 is justified **only** because the three audiences map to genuinely distinct dashboard-share boundaries — so record the choice (FIX-15).

| # | Board | Audience | Composed from |
|---|---|---|---|
| 1 | `order-triage-operations` | App-eng + SRE | Operations + Incident + Feedback's 2 widgets (a "Quality" row) |
| 2 | `order-triage-finops` | Finance + eng-leads | FinOps, unchanged — **stays standalone** (data-sensitivity invariant below) |
| 3 | `order-triage-governance` | Compliance / risk / security | Governance audit table (isolated) + the Security panels merged in |
| 4 | `order-triage-exec` | Leadership | slimmed: 5 KPI tiles + composite health alarm only |

### Two invariants the merge must respect (from the adversarial pass)
- **Audit-table isolation.** Keep the Governance per-turn append-only table ([:434-440](../../terraform/modules/observability/dashboards.tf#L434)) as the **sole top section** of board 3 — no live operational tiles beside it. The append-only durability lives in the masked `modelinvocations` log group, not the widget, so merging is safe; but co-tenanting degrades evidentiary clarity. If SOX separation is later required, re-split it to a 5th audit board.
- **Data-sensitivity invariant (the real IAM boundary).** A widget reading the **UNMASKED** `-DEFAULT` group (FinOps Contributor Insights `top_actors`/`top_sessions`, [queries.tf:8-39](../../terraform/modules/observability/queries.tf#L8); tokens-by-session) must **never** co-tenant with a widget read by a broader audience. The masked `modelinvocations` group is the only PII-safe shareable source. N=4 keeps FinOps standalone, so it complies — state the invariant so future merges don't break it.

### Widget mapping (condensed)

| Current widget | New home | Disposition |
|---|---|---|
| Ops RED (Invocations/Latency/Sessions/Errors) | Operations | keep — repack into a dense `height=2–3` band, sparklines on |
| Ops downstream latency/faults, per-tool, token-per-turn, vCPU/GB-h | Operations | keep (all unique; vCPU/GB-h is the **canonical** saturation home) |
| Incident runbook header + Active alarms + Token-vs-anomaly-band | Operations (On-call row) | keep — shrink alarm widget to `height=2` |
| Incident Errors&throttles | — | **drop — byte-identical duplicate** of Ops |
| Incident OBO success/failure | — | **drop — byte-identical duplicate** of Security |
| Incident Saturation (USE) | Operations | **merge** — fold the extra `Sessions` series into the Ops saturation tile |
| Exec 5 KPI tiles + health alarm | Exec | keep — shrink heights, fix latency source + spend format |
| Exec Invocations&errors trend / Token trend | — | **drop** — Ops/FinOps own these (near-dups at coarser resolution) |
| FinOps (all 6 widgets) | FinOps | keep — densest, best-populated board |
| Security guardrail×2, Cedar-by-tool, OBO×2 | Governance | keep — OBO becomes the **canonical** home |
| Security Caller-identity audit | Governance | **merge** into the per-turn table + fix grouping (FIX-01) |
| Governance per-turn table, Cedar-by-engine, KB latency | Governance | keep — table isolated at top |
| Feedback banner / eval-score / LLM-latency | Operations (Quality row) | keep — reconcile banner (FIX-04), fix legend (FIX-05) |

**Net:** 4 widget instances dropped with **zero signal loss** (all exact/near duplicates) + 2 merges.

### What's lost (explicit)
- **The on-call landing page.** Incident's purpose-built triage URL disappears; mitigated by anchoring the runbook header + Active-alarms + anomaly band as the **top rows** of Operations (bookmark it for on-call). Reversible.
- **Security/Governance co-tenancy.** A compliance reader now also sees live security-ops panels — acceptable because both map to the same owner (security/risk) and CloudWatch dashboard IAM is per-dashboard. If auditors must not see live OBO-failure rates, re-split the audit table.
- **Nothing else** — the dropped widgets are duplicates; their canonical copy survives.

---

## 5. Why they feel underwhelming (design/density critique)

The "underwhelming" reaction decomposes into four concrete, fixable causes:

1. **Oversized single-value tiles.** A `height=5` tile holding the digit "2" is ~85–90% empty. Across Operations + Exec that's the dominant visual. Fix: drop to `height=2–3` and turn on `sparkline` so each KPI carries a *trend*, not just a number.
2. **Duplication dilutes signal.** Errors&throttles, OBO success/failure, runtime saturation, and the token trend each appear on 2–3 boards. Seven boards with overlapping content reads as less, not more.
3. **Idle traffic + default 3h window.** Many panels are empty on first load purely because the window is short and the demo is quiet — the App Signals dependency, per-tool, token, and saturation panels all *do* populate at 1 week. Fix: default idle-prone boards to a 1-week view; annotate legitimately-zero panels (OBO failures, eval) as "expected 0."
4. **Copy/format defects that read as bugs.** `9.61E-3` for cost, the mangled `evalscoreevalscore` legend, the "ENABLED" banner over an empty panel, and the opaque actor leaderboard all signal "half-finished" even where the underlying wiring is fine.

---

## 6. Prioritized fix backlog

Ordered by leverage (impact × low effort × number of "looks broken" symptoms removed). Effort S/M/L.

| ID | Title | Sev | Board(s) | Change | File(s) | Effort |
|---|---|---|---|---|---|---|
| **FIX-01** | Caller-identity audit groups by runtime role, not user | High | Security→Gov | `by identity.arn` → `by requestMetadata.actor, modelId`; keep `identity.arn` as a column (proves OBO "served-as runtime, authorized-as user"). Merge into the Governance table. | `dashboards.tf:412` | **S** |
| **FIX-02** | Oversized singleValue tiles waste ~85% of canvas | High | Ops, Exec | `height` 5/4 → **2–3**; `sparkline=true`. Highest-leverage anti-"broken" fix. **Blocking for the merge.** | `dashboards.tf:32-51,218-257` | **S** |
| **FIX-03** | Cross-board duplicate widgets | High | Ops/Inc/Exec/Sec | drop the 4 verified duplicates to one canonical home each (§4). | `dashboards.tf` | **S** (in merge) |
| **FIX-04** | Feedback banner says ENABLED while panel empty | High | Feedback→Ops | decouple banner from `var.enable_online_evaluations`; when enabled-but-empty render `"ENABLED — scores pending (AgentSpanMappingException, ADR-0005)"`. | `dashboards.tf:474` | **S** |
| **FIX-05** | Mangled `evalscoreevalscore` legend | Low | Feedback→Ops | set `label="Avg eval score by evaluator"` (empty label → CloudWatch concatenates the id). | `dashboards.tf:484` | **S** |
| **FIX-06** | Spend renders as sci-notation `9.61E-3` | Low | Exec, FinOps | scale ×100 → cents (`label="Est. cost (¢)"`) or widen window; never show E-notation on Exec; carry the "ESTIMATE" caveat onto Exec too. | `dashboards.tf:243,314` | **S** |
| **FIX-07** | Latency defined 3 incompatible ways | Med | Exec, Ops, SLO | re-source Exec p99 from the **same vended `Latency`** the SLO uses, or label each inline (`"End-to-end p99 (App Signals)"` vs `"Runtime envelope avg"`). | `dashboards.tf:233,42` | **M** |
| **FIX-08** | Actor leaderboard opacity looks like a defect | Med | FinOps/Gov/Sec | **now:** relabel + subtitle (§2). **later:** IDR-1 Lambda. Never push email/UPN into telemetry. | `dashboards.tf:321,438`; `queries.tf` | **S** / **L** |
| **FIX-09** | Exec "each tile links down" unfulfilled | Med | Exec | delete/reword — tiles can't carry links; use markdown deep-links in a text widget if cross-board nav is wanted. | `dashboards.tf:216` | **S** |
| **FIX-10** | Header drill-path comment never implemented | Med | all | reword `:1-6` to describe what's built (board-level deep-links + saved Logs Insights queries); drop the per-tile `session.id` drill claim. | `dashboards.tf:1-6` | **S** |
| **FIX-11** | Incident "Active alarms" oversized (`height=4`) | Med | Inc→Ops | `height=2`; reclaim 2 rows to pull the anomaly band above the fold. | `dashboards.tf:145` | **S** |
| **FIX-12** | Idle-traffic sparse timeseries look empty | Med | Ops/Exec/Fb/Sec | default idle-prone boards to a 1-week view; annotate legitimately-zero panels as "expected 0." | `dashboards.tf` | **S** |
| **FIX-13** | Isolate the Governance audit table on merge | Med | Gov | keep the append-only table as the sole top section, no operational tiles beside it. | `dashboards.tf:434-440` | **S** (in merge) |
| **FIX-14** | State the data-sensitivity invariant in comments | Low | FinOps/Gov | comment: unmasked `-DEFAULT`-group widgets must never co-tenant with a broader audience; `modelinvocations` is the only shareable source. | `dashboards.tf`,`queries.tf` | **S** |
| **FIX-15** | Record the 7→4 (and N) decision | Med | all | ADR or P3.2 amendment superseding "one Runtime dashboard / single pane" with N=4 and the audience-IAM rationale. | `docs/adr/` | **S** |

> **Corrected out of the backlog (adversarial pass):** the "token-usage trend is a verbatim duplicate" claim is **wrong** — Ops uses 3 metrics @ period=300, Exec 2 @ period=3600 (drops `Total`), FinOps 3 @ period=3600: the *same metrics re-framed at different resolutions*, handled as the Exec-drop in §4, not a flat clone. The runtime-saturation pair is a *near*-duplicate (Incident adds `Sessions`) — a merge, not a delete.

---

## 7. Sequencing

**Wave 1 — quick wins, ship today (all S, no new infra, independent of the merge):**
FIX-01, FIX-02 (highest leverage), FIX-04, FIX-05, FIX-06, FIX-08-label, FIX-09, FIX-10, FIX-11, FIX-12. These remove *every* "broken-looking" symptom and don't depend on consolidation. Validate offline with `make tf-validate`.

**Wave 2 — the consolidation (M), bundled with the cross-cutting fixes so boards aren't born broken:**
the 7→4 merge (§4) carrying FIX-03, FIX-07, FIX-13, FIX-14, FIX-15. The merge **must** ship with Wave-1's density fixes already in — otherwise N=4 still reads as whitespace.

**Wave 3 — deeper, decoupled (L):**
FIX-08-Lambda (IDR-1 render-time Graph resolution) — the only item needing new infra (Lambda + Entra app + Graph perms); lands after the boards are clean. Optionally IDR-3 (non-PII dept attribute) as a chargeback-friendly + fallback layer, gated on verifying the live token carries a usable claim.

**Rule of thumb:** *labels/heights/grouping first (cheap, kills the "broken" perception), merge second (kills drift + duplication), identity Lambda last (the only real engineering lift).*

**Files where changes land:** [dashboards.tf](../../terraform/modules/observability/dashboards.tf) (primary), [queries.tf](../../terraform/modules/observability/queries.tf) (CI-rule labels, sensitivity comments), [slo.tf](../../terraform/modules/observability/slo.tf) (latency source for FIX-07), a new `actor_resolver.tf` + Lambda (FIX-08 Wave 3), [identity.py](../../../agent/src/order_triage/identity.py) (only if IDR-3 is adopted), `docs/adr/` (FIX-15).

---

## Appendix — live per-board observations (1-week window, acct 953472632913 / us-west-2)

- **Operations** — RED singleValues `Invocations=2 / Latency=556ms / Sessions=2`; downstream-dependency + per-tool (11-tool legend) + token + vCPU/GB-h all populate over a week (empty at 3h, idle).
- **Incident** — 6 alarms green; Errors&throttles (dup), Saturation (overlap), OBO (dup), Token-vs-anomaly-band (unique, good). Alarm widget reserves ~3 empty rows.
- **Exec** — `Success=100`, `p99=45.1s` (App Signals), `spend=9.61E-3`, `Guardrail=0`, health green. Header over-promises tile links; two trend tiles overlap other boards.
- **FinOps** — token volume / cost / tokens-by-model / memory-tokens populate; **Top actors = opaque subs** beside **Top sessions = readable ids**.
- **Security** — guardrail breakdowns + Cedar-by-tool (rich) + OBO populate; **Caller-identity audit groups by the runtime role** (every row identical).
- **Governance** — densest, most useful: per-turn audit table (nova-lite + titan-embed KB calls, token counts, turn ids) with the opaque `hcd…` actor column; Cedar-by-engine + KB latency populate.
- **Feedback** — weakest (2 widgets): "ENABLED" banner over an empty eval panel (`AgentSpanMappingException`), mangled legend; LLM-latency-by-model populates.

*Provenance: live console walkthrough of all 7 dashboards + IaC read + spike/plan intent, then a 9-agent audit workflow (5 lenses → 3 adversarial verifiers, all returning "sound-with-changes" → synthesis). Adversarial corrections folded in; refuted findings dropped.*

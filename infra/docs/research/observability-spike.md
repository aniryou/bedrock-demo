# SPIKE REPORT — Observability Native-Fit for `order-triage-agent`

**Question:** Is the current observability implementation **maximally AgentCore-native + AWS-native** — and does staying native cost us any comprehensiveness?
**Scope:** AgentCore Runtime (`order_triage-cwG2Pw7Bnv`) + Gateway (Cedar/OBO) + Strands agent + Bedrock Knowledge Base + AgentCore Memory + Guardrail + Snowflake/SAP Lambdas + webapp.
**Audience:** repo owner + ops.
**Relationship to prior work:** the cost/token *dollarization* plan lives in [FINOPS-SPIKE.md](finops-spike.md) (Tier-0/1 toggles, `requestMetadata`, EMF, CUR, AIP) — this spike **defers to it** rather than re-deriving it, and focuses on the observability/telemetry surface.

---

## 1. Bottom line up front

The stack is **already substantially AgentCore-native by default and runs ZERO third-party observability tooling.** The runtime image launches under `opentelemetry-instrument` with `aws-opentelemetry-distro` ([Dockerfile:25](../../../agent/Dockerfile), [pyproject.toml:21](../../../agent/pyproject.toml)), feeding **CloudWatch GenAI Observability**; account-level **CloudWatch Transaction Search is wired** ([observability.tf:10-41](../../terraform/observability.tf)); vended `AWS/Bedrock-AgentCore` metrics auto-emit with no config; and **AgentCore Memory log + trace delivery is deployed** ([observability.tf:51-92](../../terraform/observability.tf), ADR-0002 D3 / infra #66).

The real problem is **not a native-vs-third-party choice — it is a deeply under-used native surface.** No dashboards, no alarms, no SLOs, no Bedrock model-invocation logging, no `USAGE_LOGS`, no **Gateway/Identity** trace+log delivery, and the per-turn Strands token-usage event is **discarded** in [runtime.py:67-75](../../../agent/src/order_triage/runtime.py). Closing every *operational* gap here is Terraform/config wiring against primitives that **already exist or already half-exist** in this repo — no vendor required.

The **only** comprehensiveness features genuinely unreachable native-only are: LLM-quality **eval UX choice across multiple judge providers**, **prompt-version ↔ eval ↔ trace linkage**, **human annotation/labeling queues**, **versioned dataset/experiment-diff UI**, and **per-trace cost dollarization inside the trace view**. Every one of those is **OTEL-additive** (Langfuse/Phoenix/Datadog dual-export), so adopting them later sacrifices nothing native.

**⚠️ Live console correction (2026-06-23 — supersedes the earlier reconciliation).** The AgentCore console (Runtime → *Log deliveries and tracing*) shows **Tracing: Not enabled** and **Log delivery (0)** on **both** the **Runtime** and **Identity** tabs. This resolves the spike's open caveat in the *pessimistic* direction: the **`InvokeAgentRuntime` service span and any gen_ai/token spans are NOT being delivered to CloudWatch** — **only the vended metrics flow** (the runtime dashboard's session/invocation/latency/error tiles populate with zero config). The earlier "service span flows today" framing was **wrong** — this **per-resource Tracing toggle is the gate, and it is off**, because Terraform wired log/trace delivery for the **Memory resource only** ([observability.tf:51-92](../../terraform/observability.tf)). The dormant trace surface is therefore broader than first stated: it is **Runtime *and* Identity** (and Gateway), not just Gateway/Identity. The account-level Transaction Search routing being on does **not** by itself deliver the runtime's traces — the per-resource toggle does.

---

## 2. Two-tier native verdict table

`native_fit` legend: **fully-native** · **underused** (a native primitive is being left on the table) · **aws-only** (uses generic AWS, no AgentCore-specific primitive applies) · **gap** · **needs-3p**.

| Dimension | AgentCore-native capability | AWS-native capability | Current state (file:line) | `native_fit` | Lost if native-only |
|---|---|---|---|---|---|
| Trace & span emission (agent loop + tool calls) | ADOT auto-instr → `aws/spans`; GenAI Obs span tree | Transaction Search routing; X-Ray service map | ADOT launched ([Dockerfile:25](../../../agent/Dockerfile)); Transaction Search wired ([observability.tf:10-41](../../terraform/observability.tf)); no `StrandsTelemetry`/`OTEL_EXPORTER_*`/`AGENT_OBSERVABILITY_ENABLED` (zero grep, [runtime.tf:40-52](../../terraform/runtime.tf)) | **underused** | Nothing for span *capture*; only LLM-trace UX/replay (additive) |
| GenAI-convention spans & token capture | gen_ai spans → token/usage views in GenAI Obs | Bedrock model-invocation logging (tokens + `requestMetadata`) | usage event discarded ([runtime.py:67-75](../../../agent/src/order_triage/runtime.py)); no `requestMetadata` ([agent.py:56-74](../../../agent/src/order_triage/agent.py)); no model-invocation logging | **underused** | Per-span/session **dollarized** cost; eval scoring (additive / FinOps) |
| Logs (runtime, Memory, app, model-invocation) | Memory APPLICATION_LOGS delivery; runtime stdout auto-vended | model-invocation logging; CWL retention/CMK/data-protection | Memory logs wired + 30d retention ([observability.tf:51-61](../../terraform/observability.tf)); ~zero structured app logging; no model-invocation logging | **underused** | Nothing — fully native-served |
| Metrics (vended, EMF, token) | Vended `AWS/Bedrock-AgentCore` (auto) | EMF custom metrics; metric filters | Vended metrics auto-emit; no EMF/alarms/filters; tokens discarded | **underused** | Cost dollars (FinOps); eval-quality (additive) |
| Sessions & multi-turn analytics | `session.id` propagation; GenAI Obs session→trace drill-down; AgentCore Evaluations session/goal scoring | Logs Insights cohort slicing | Stable per-login session id ([main.py:124](../../../app/app/main.py)), reused per-turn, threaded into Memory ([memory.py:48](../../../agent/src/order_triage/memory.py)); no session attrs on spans/logs | **underused** | Conversation-quality replay, cohort slicing, per-session $ (additive) |
| Latency & performance breakdown | **Gateway Call-Tool spans (SERVER+CLIENT, `TargetExecutionTime`)**; Memory traces | X-Ray service map; Lambda Active tracing | Memory traces wired; **Gateway has no trace delivery** ([gateway.tf](../../terraform/gateway.tf)); no Lambda `tracing_config`; no `traceparent` forwarding | **underused** | Cost-on-latency overlay (FinOps) |
| Errors, failures & exceptions | Vended error/throttle metrics; service-span `error_type` | DLQ; alarms; SNS; Lambda Active tracing | JWT-decode failures fall back silently ([identity.py](../../../agent/src/order_triage/identity.py)); ~zero Lambda logging; no DLQ/alarm/SNS; **vended error/throttle metrics emit, but the service-span `error_type` is NOT delivered** (Runtime Tracing off, console-verified) | **underused** | LLM-aware error-trace replay ergonomics only |
| Quality / online-eval / groundedness / Guardrail | **AgentCore Evaluations (13 judges, online + on-demand)**; Guardrails vended metrics | Bedrock Guardrails metrics; model-invocation guardrail trace | Guardrail = PROMPT_ATTACK only ([guardrail.tf:29-50](../../terraform/guardrail.tf)); no `guardrail_trace`; no eval wiring; `__step__` timeline unscored ([stream_steps.py](../../../agent/src/order_triage/stream_steps.py)) | **underused** | Multi-provider judges, annotation queues, dataset/experiment-diff UI (additive) |
| Alarming, SLOs, anomaly, dashboards | *(AgentCore exposes no alarm primitive)* | CloudWatch alarms/composite/anomaly; Application Signals SLOs; dashboards; SNS | **zero** alarms/dashboards/SLOs/anomaly (two greps) | **aws-only** | None for this dimension |
| Downstream (Snowflake/SAP/KB/OBO-Gateway) | **Gateway target spans; Identity OBO spans (`GetWorkloadAccessTokenForJWT`)**; KB `Retrieve` span | X-Ray on Lambdas | Only Memory delivery wired; no Lambda tracing; KB `Retrieve` auto-instr ([knowledge.py](../../../agent/src/order_triage/tools/knowledge.py)); Snowflake internals opaque ([snowflake_client.py](../../../stubs/snowflake_stub/snowflake_client.py)) | **underused** | In-Snowflake RBAC/RLS/credits/query-profile (outside AWS *and* AgentCore) |
| Retention, lifecycle, telemetry-cost, PII governance | Memory `event_expiry_duration` (90d) | `retention_in_days`, `kms_key_id`, `log_data_protection_policy`, S3 lifecycle, **trace sampling** | Only Memory log group retained ([observability.tf:51-55](../../terraform/observability.tf)); no CMK / no data-protection policy; tags only Project+ManagedBy ([versions.tf:33-38](../../terraform/versions.tf)) | **aws-only** | None — native-served |
| Single-pane / cross-signal correlation | Session↔trace↔span in GenAI Obs; ADOT session stamping | Transaction Search; Logs Insights joins | Transaction Search + Memory delivery wired; no `traceparent` from webapp ([agentcore.py](../../../app/app/agentcore.py)); no Gateway/Identity TRACES | **underused** | **Per-trace/session cost in dollars co-located in the trace UI** (the one genuine correlation loss; FinOps + additive) |

---

## 3. "Is it AgentCore-native?" — explicit answer

**Yes — and that is the right posture. The stack uses native primitives already; the remaining work is to *light up native primitives that are dormant*, not to bolt on a vendor.**

### Native primitives ACTUALLY in use today
- **ADOT auto-instrumentation** — `opentelemetry-instrument python -m order_triage.runtime` ([Dockerfile:25](../../../agent/Dockerfile)) with `aws-opentelemetry-distro>=0.10.0` ([pyproject.toml:21](../../../agent/pyproject.toml)). No hand-rolled tracer — correct; `StrandsTelemetry` was deliberately not added.
- **CloudWatch GenAI Observability** — consumes the ADOT spans (session → trace → span drill-down, latency/error/session metrics).
- **CloudWatch Transaction Search** — X-Ray → `aws/spans` resource policy + `update-trace-segment-destination --destination CloudWatchLogs` ([observability.tf:10-41](../../terraform/observability.tf)).
- **Vended `AWS/Bedrock-AgentCore` metrics** — Invocations/Sessions/Latency/Errors/Throttles + `CPUUsed-vCPUHours`/`MemoryUsed-GBHours`, auto-emitted, zero IaC.
- **AgentCore Memory log + trace delivery** — APPLICATION_LOGS → vended CWL group (30d retention) and TRACES → X-Ray ([observability.tf:51-92](../../terraform/observability.tf), ADR-0002 D3, deployed infra #66). LTM `/summaries/{actorId}/{sessionId}` namespace live ([memory.py:28,48](../../../agent/src/order_triage/memory.py)).
- **Bedrock Guardrail** — PROMPT_ATTACK input filter wired into the model ([guardrail.tf:29-50](../../terraform/guardrail.tf)), so `AWS/Bedrock/Guardrails` vended metrics emit.

> **NOTE (console-verified 2026-06-23):** the `InvokeAgentRuntime` service span is **NOT** in this list — Runtime Tracing is *Not enabled*, so it is not delivered. Only the **vended metrics** above flow without the per-resource Tracing toggle. See the §1 console correction.

### Native primitives LEFT ON THE TABLE (dormant — closeable with Terraform/config)
- **Per-resource Tracing granularity.** AgentCore exposes **separate** Tracing/log-delivery enablement per resource — Runtime, **Gateway**, Memory, built-in Tools, and a distinct **WorkloadIdentity** toggle. Only **Memory** is wired; **Runtime and Identity are both off (console-verified 2026-06-23: Tracing Not enabled, 0 log deliveries).** *This is the single biggest native-but-dormant surface.*
- **Gateway TRACES + APPLICATION_LOGS delivery** — none ([gateway.tf](../../terraform/gateway.tf)). Enabling it emits the **two-span Call-Tool structure** (`kind:SERVER` overall + `kind:CLIENT` target span carrying `TargetExecutionTime`/`overhead_latency_ms`/target type), which **natively closes the "trace breaks at Gateway→Lambda" gap without** Lambda Active tracing or `traceparent` forwarding.
- **Identity / WorkloadIdentity tracing** — `GetWorkloadAccessTokenForJWT` spans carry `issuer` + `user_sub` (the per-user OBO exchange), plus per-provider `…AccessTokenFetch`/`ApiKeyFetch` Success/Failure/Throttle metrics. **No third-party equivalent.** Given this repo's entire validated value-prop is **per-user OBO**, this is the highest-value dormant audit surface — and the closest native proxy to the intentionally-retired "served-as" identity panel.
- **`USAGE_LOGS`** — the only native **per-session vCPU/GB-hours** signal (1-sec granularity: `session.id`, `agent.runtime.vcpu.hours.used`, `memory.gb_hours.used`). Not enabled; feeds the GenAI Obs Agent-Session page and the FinOps unit-economics join.
- **Token-usage capture** — Strands surfaces `EventLoopMetrics.accumulated_usage` per turn; [runtime.py:67-75](../../../agent/src/order_triage/runtime.py) forwards only `event["data"]` text + `step_events()` and **drops the rest**. No `requestMetadata` on the Bedrock call ([agent.py:56-74](../../../agent/src/order_triage/agent.py)).
- **AgentCore Evaluations** (GA Mar 2026) — 13 built-in LLM-judge evaluators (faithfulness / goal-success / safety) running **online** on sampled live traces → CloudWatch, **consuming the gen_ai spans/Transaction Search already deployed.** "Eval is third-party-only" is the **old, wrong** thesis — do not repeat it.
- **Bedrock model-invocation logging** — canonical AWS-native token-count + `requestMetadata` + prompt/completion capture; absent. *(Carries unmasked PII — see §5 Phase 1.4 prerequisite.)*
- **Dashboards / alarms / anomaly / Application Signals SLOs** — zero. The one `aws-only` dimension (AgentCore has no alarm primitive), but still fully native.

---

## 4. What you'd lose by staying 100% native

| Capability | Genuine native gap? | Matters for THIS Nova-Lite single-agent demo? | OTEL-additive (native NOT sacrificed)? |
|---|---|---|---|
| **LLM-as-judge online/offline evals** | Partial — AgentCore Evaluations covers faithfulness/goal-success/safety natively; gap is multi-provider judge choice + richer rubric iteration | **Low** today (single Bedrock model). Native online eval is a low-effort add once tracing is confirmed | **Yes** (Langfuse/Phoenix/Braintrust ingest OTLP) |
| **Prompt versioning + experiment/dataset mgmt** | Bedrock Prompt Management gives versioning; gap is prompt↔eval↔trace linkage + golden-set/experiment-diff UI | **Low** (prompts live in code/skills; no release cadence pressure) | **n/a** — authoring plane, not telemetry (parallel control plane) |
| **Trace playback + human annotation queues** | Trace playback is native (GenAI Obs); **annotation/labeling queues have no native equivalent** | **Low** (no human-in-the-loop labeling workflow today) | **n/a** for annotation authoring; trace inspect is native |
| **Per-trace cost dollarization in the trace UI** | Yes — native emits token **counts** + vCPU/GB-hours, never per-trace **dollars** | **Owned by [FINOPS-SPIKE.md](finops-spike.md)** (requestMetadata/EMF/CUR/AIP), not this spike | **Yes** (Datadog/Langfuse price maps) |

**Honest read:** none of these block the demo. The native stack is **comprehensiveness-complete for operational telemetry** (trace / log / metric / session / error / latency capture + retention + governance). The four items above are **LLM-quality-workflow** and **FinOps-dollarization** features — real, but (a) low-urgency for a single-agent Nova-Lite demo and (b) layerable later via a **second OTLP exporter** without ripping out CloudWatch. The only case that *replaces* native is setting `DISABLE_ADOT_OBSERVABILITY=true` to route solely to a vendor — a config choice, **not** a requirement.

### Additional surfaces flagged in completeness review
- **KB ingestion/sync-job observability — real minor gap.** The KB *query* path is auto-instrumented (`bedrock:Retrieve` span), but the *ingestion* lifecycle (`StartIngestionJob` status, embedding-token cost during sync, sync failures) has no logging/alarm. [knowledge_base.tf](../../terraform/knowledge_base.tf) wires a `data_source` but no ingestion telemetry. Low priority for a static demo KB; alarmable if the corpus ever refreshes on a schedule.
- **Trace sampling rate / telemetry-volume control — pair with retention.** Transaction Search defaults to **100% span ingestion** into `aws/spans` (a cost driver). Govern telemetry cost on *both* axes: ingest-side sampling **and** at-rest `retention_in_days` (§5 Phase 3).
- **Deployment/version correlation — real gap.** Nothing emits runtime version / image digest / guardrail version as deployment markers, so latency/quality regressions can't be tied to a release (the endpoint *does* roll on runtime version — [runtime.tf:55-60](../../terraform/runtime.tf) — but that fact isn't surfaced as telemetry). Low effort: stamp `service.version`/image digest as a span resource attribute or a dashboard annotation.
- **Authorization-decision audit — mostly covered by the §5 Phase-0 Gateway+Identity tracing.** Cedar allow/deny (`hasTag("scp")`) and OBO `TOKEN_EXCHANGE` outcomes are a **compliance/audit** signal distinct from latency/error telemetry; enabling Gateway + Identity tracing surfaces them natively, with CloudTrail as the management-plane backstop.
- **Cold-start observability — NOT a gap (verified).** [cold_start.tf](../../terraform/cold_start.tf) is **deploy-time eventual-consistency hardening** (`time_sleep`, create-only), **not** runtime warm-keeping. There are no synthetic warm-pool invocations, so there is no warm-vs-real traffic pollution of session/latency metrics to worry about.

---

## 5. Recommendation — maximize native first (the correct call here)

A phased, mostly-Terraform "light up the dormant native surface." Cross-references the [FINOPS-SPIKE.md](finops-spike.md) Tier-0/1 toggles rather than re-deriving them.

### Phase 0 — flip the dormant native toggles (Terraform, low effort)
1. **Wire RUNTIME Tracing + log delivery (confirmed off, not a no-op).** The console shows Runtime → *Tracing: Not enabled* and *0 log deliveries*, so the runtime's traces (`InvokeAgentRuntime` service span + gen_ai/token spans) are **not** reaching CloudWatch. Clone the existing Memory `log_delivery_source`/`destination`/`delivery` pattern ([observability.tf:57-91](../../terraform/observability.tf)) against the **runtime ARN** with `log_type = TRACES` (→ XRAY destination) and `APPLICATION_LOGS`/`USAGE_LOGS` (→ CloudWatch Logs). If the framework still doesn't emit gen_ai spans after the toggle, add `AGENT_OBSERVABILITY_ENABLED=true` to `runtime.tf` env and/or an explicit Strands tracer — confirm with a live `aws/spans` query.
2. **Wire Gateway TRACES + APPLICATION_LOGS delivery and WorkloadIdentity (Identity) tracing** the same way against the gateway and identity ARNs. Identity is also *Not enabled / 0 deliveries* (console-confirmed). Surfaces Call-Tool target-execution timing and the OBO `GetWorkloadAccessTokenForJWT(issuer, user_sub)` spans — **highest value, lowest effort.**
3. **Enable `USAGE_LOGS`** runtime log delivery (per-session vCPU/GB-hours) → a log group with explicit retention (covered by the runtime log delivery in step 1).

### Phase 1 — token usage + cost-attribution seam (cross-ref FinOps Tier-0/1; do not duplicate)
4. **Enable Bedrock model-invocation logging** (`aws_bedrock_model_invocation_logging_configuration`) → token counts + prompt/completion. **Blocking prerequisite:** add a `aws_cloudwatch_log_data_protection_policy` first — invocation logs and any guardrail trace retain **unmasked customer PII** (no PII guardrail per the 2026-06-23 decision). Never enable full request/response logging with real data absent that policy.
5. **Stop discarding the token-usage event:** in [runtime.py](../../../agent/src/order_triage/runtime.py) read the final `AgentResult`/`EventLoopMetrics.accumulated_usage` and emit it (EMF or span attribute). Keep **agent/model as the only EMF metric dimensions**; `session_id`/`request_id`/actor are **log fields only** (cardinality rule, FinOps). Inject `requestMetadata` (actor/session/turn) via `additional_args` ([agent.py:56-74](../../../agent/src/order_triage/agent.py)) — FinOps Tier-1; **validate persistence on one live streaming `converse_stream` first.**

### Phase 2 — proactive monitoring layer (`aws-only`, generic CloudWatch, medium effort)
6. **CloudWatch dashboard(s)** assembling vended AgentCore/Guardrails metrics + Logs Insights widgets (the single pane).
7. **Metric/composite alarms + anomaly detection** on error/throttle/latency, `InvocationsIntervened` (guardrail block-rate), and (post-Phase-1) token spend → an **SNS topic**.
8. **Application Signals SLOs** for availability/latency (Transaction Search already satisfies the dependency). Lambda SLIs ride the Application Signals/ADOT layer, not bare `tracing_config{mode=Active}`.

### Phase 3 — hygiene (Terraform, low effort)
9. Set **`retention_in_days`** on the runtime + three Lambda + Gateway log groups (only Memory has it today); consider CMK. Add **cost-allocation tags** (cost_center/team/env) beyond Project+ManagedBy ([versions.tf:33-38](../../terraform/versions.tf)). Govern **trace sampling** alongside retention.
10. Add **structured error logging** to the silent JWT-decode fallback ([identity.py](../../../agent/src/order_triage/identity.py)) and the webapp inline error path ([main.py](../../../app/app/main.py)). Stamp **`service.version`/image digest** as a span resource attribute for release-to-regression correlation.

### Deferred — OTEL dual-export to an eval tool, ONLY if quality evals become a requirement
AgentCore/Strands already emit OTEL; add a second span processor/OTLP exporter (Langfuse `/api/public/otel`, Phoenix, Braintrust, Datadog) **alongside** the CloudWatch ADOT exporter — additive, **zero native loss.** Before reaching for a vendor, evaluate **AgentCore Evaluations** (native, online, consumes already-deployed spans). LiteLLM remains rejected (managed runtime, no interceptable hop). APM/Datadog only if the org already owns it (adds PII-egress risk given no PII guardrail).

---

## 6. Key files cited

- [../../../agent/Dockerfile:25](../../../agent/Dockerfile), [pyproject.toml:21](../../../agent/pyproject.toml) — ADOT auto-instrumentation (the single telemetry mechanism)
- [runtime.py:50-75](../../../agent/src/order_triage/runtime.py) — session read; token-usage event discarded
- [stream_steps.py](../../../agent/src/order_triage/stream_steps.py) — `__step__` classification (no usage branch)
- [agent.py:56-74](../../../agent/src/order_triage/agent.py) — `BedrockModel` build (no `requestMetadata`; guardrail kwargs)
- [memory.py:28,48](../../../agent/src/order_triage/memory.py) — session / LTM namespace
- [identity.py](../../../agent/src/order_triage/identity.py) — JWT-decode fallback returns `None` silently (no log/metric)
- [observability.tf:1-92](../../terraform/observability.tf) — Transaction Search wiring + Memory log/trace delivery (the reusable pattern to clone for Gateway/Identity)
- [runtime.tf:9-60](../../terraform/runtime.tf) — runtime resource; **no** observability/Tracing attr; endpoint rolls on version
- [gateway.tf](../../terraform/gateway.tf) — Gateway, no trace/log delivery
- [guardrail.tf:29-50](../../terraform/guardrail.tf) — PROMPT_ATTACK only; no `guardrail_trace`
- [knowledge_base.tf](../../terraform/knowledge_base.tf) — KB data source; no ingestion-job logging
- [cold_start.tf](../../terraform/cold_start.tf) — deploy-race `time_sleep` (NOT warm-keeping)
- [versions.tf:33-38](../../terraform/versions.tf) — tags = Project+ManagedBy only
- `{sap,order_actions,snowflake}_lambda.tf` — no `tracing_config`, no log groups
- [main.py:124,175](../../../app/app/main.py), [agentcore.py](../../../app/app/agentcore.py) — session mint/reuse; no `traceparent`
- [snowflake_client.py](../../../stubs/snowflake_stub/snowflake_client.py) — opaque urllib SQL-REST egress

---

*Provenance: a 33-agent multi-agent spike — repo-grounded Phase-1 inventory (infra TF / agent code / webapp+Lambdas / prior docs) + Phase-2 capability landscape (AgentCore-native / AWS-native / third-party delta), reconciled through per-dimension adversarial verification and a completeness critic, then re-grounded against the actual files. Consistent with [FINOPS-SPIKE.md](finops-spike.md), [AUDIT.md](audit-2026-06-21.md), ADR-0002, and verified memory notes. Deployed model = `amazon.nova-lite-v1:0` ([variables.tf:14](../../terraform/variables.tf)), not the Python Opus default. **Live-console correction (2026-06-23):** an earlier draft reconciliation claimed the `InvokeAgentRuntime` service span "flows today" — the AgentCore console (Runtime → Log deliveries and tracing) **disproves this**: both Runtime and Identity show *Tracing: Not enabled* and *0 log deliveries*. So only the vended metrics flow; the per-resource Tracing toggle (off, because TF wired delivery for Memory only) is the gate for the service span + gen_ai/token spans. Generated 2026-06-23.*

# Observability Phase 3 — Research & Dashboard Design

**Date:** 2026-06-23 · **Author:** native-observability spike (multi-agent research, 18 agents) · **Status:** RESEARCH / DESIGN — pre-build
**Companion docs:** [OBSERVABILITY-SPIKE.md](observability-spike.md) (native-fit analysis), [OBSERVABILITY-IMPL-PLAN.md](../playbooks/observability-impl-plan.md) (P0–P4 sequencing), [FINOPS-SPIKE.md](finops-spike.md) (owns token→$ dollarization)

**Hard constraint:** build **100% AWS-native** — CloudWatch (Dashboards / Metrics Insights / Logs Insights / Contributor Insights / Alarms), X-Ray Transaction Search (`aws/spans`), AgentCore GenAI Observability + Evaluations, Cost Explorer / CUR 2.0, CloudTrail, optional QuickSight. **No Langfuse / Arize / Datadog.** Best-in-class tools are the *bar to match natively*, not tools to adopt.

> Every load-bearing "can we do this natively" claim below was adversarially verified against AWS docs. The 4 that came back **refuted/uncertain** are folded into the design and listed in §8.

---

## 0. LIVE METRIC CONTRACT (read back from the account 2026-06-23 — overrides §3/§5/§6 where they differ)

Pinned via `aws cloudwatch list-metrics` against acct `953472632913` / `us-west-2`. **The live surface is richer than the research assumed — build from this.**

**Four namespaces (not one):**
| Namespace | What | Key dims |
|---|---|---|
| **`AWS/Bedrock-AgentCore`** (hyphen!) | AWS-**vended** runtime/gateway/memory/identity/**authz** metrics | `Operation`, `Resource` (ARN), `Name`, `Method`/`Protocol` (gateway MCP), `StrategyId`/`StrategyType` (memory) |
| **`bedrock-agentcore`** (no prefix) | OTEL/ADOT app metrics | `strands.*` (by `tool_name`), `gen_ai.client.*` (by `gen_ai.token.type`,`gen_ai.request.model`), `http.*`, `otel.sdk.*` |
| **`ApplicationSignals`** | **LIVE auto-instrumented** golden signals + dependency map | `Service`, `Operation`, `RemoteService`, `RemoteOperation`, `RemoteResourceType`/`Identifier`, `Environment` |
| **`OrderTriage/Agent`** | our EMF token metric | `agent_id`, `model_id` |

**Vended `AWS/Bedrock-AgentCore` (dims are `Operation`/`Resource`/`Name` — NOT `Endpoint`/`AgentId`):** `Invocations`, `Latency`, `Errors`, `SystemErrors`, `UserErrors`, `Throttles`, `Sessions`, `Duration`; `CPUUsed-vCPUHours`/`MemoryUsed-GBHours`; **`TargetExecutionTime` by tool `Name`** (tool-exec time IS a vended metric); Memory **`TokenCount`** (`Operation=LongTermMemoryProcessing`, `StrategyType=Preference` — summarization cost visible) + `CreationCount`; **Cedar authz as metrics** `AllowDecisions`/`DeterminingPolicies`/`TotalMismatchedPolicies` (by `OperationName`,`Policy`,`PolicyEngine`,`ToolName`); **OBO as metrics** `ResourceAccessTokenFetchSuccess`/`Failures` (by `ProviderName`,`Type`,`ExceptionType`), `WorkloadAccessTokenFetchSuccess`, `InboundAuthorizationSuccess`.

**`ApplicationSignals` (LIVE, no IaC):** `Latency`/`Error`/`Fault`/`Throttle` per `Service` (`order_triage.default`) × `RemoteService` — capturing **every downstream dependency**: SAP & Snowflake Lambda URLs, `AWS::Bedrock` (nova-lite), `AWS::Bedrock::KnowledgeBase`, `AWS::BedrockAgentCore::Memory` — plus `GenAISystem-Input/OutputTokens` and per-model `Input/OutputTokens`.

**Five research caveats OVERTURNED by the live data** (supersede §3/§6):
1. ~~"tool latency is trace-only"~~ → it's a **metric** 3 ways (`TargetExecutionTime`, `strands.tool.duration`, App Signals RemoteOperation `Latency`).
2. ~~"Cedar decision logs must be routed into the spine (new wiring)"~~ → **already vended metrics** (`AllowDecisions`/`DeterminingPolicies`).
3. ~~"OBO is trace-only"~~ → **vended metrics** (`ResourceAccessTokenFetch*`).
4. ~~"downstream Lambdas opaque / need Active tracing"~~ → **App Signals RemoteService** covers SAP/Snowflake/Bedrock/KB/Memory Latency/Error/Fault now.
5. ~~"App Signals SLO — AgentCore not auto-discovered"~~ → service + ops + remote deps **ARE discovered** → SLOs viable now. **Drive percentile latency + SLOs off `ApplicationSignals.Latency`**; vended `Latency` Average for tiles (vended p99 accepted-but-unconfirmed-with-data while idle).

**`session.id` = confirmed canonical join key** (present on every span; spans also carry `actor.id`, `memory.id`, `aws.remote.resource.*`). **Multiple runtime resources exist** (versions + OBO test); dashboards pin the current runtime ARN from `terraform output` or aggregate via Metrics Insights `GROUP BY` / `[Operation]`-only combos.

---

## 1. Best-in-class benchmark — what "rich" looks like

We surveyed 14 platforms in two families:

**AI-native (the reference IA):** Langfuse, LangSmith, Arize Phoenix/AX, Braintrust, W&B Weave, Helicone, Pydantic Logfire.
**APM-extension (GenAI bolted onto single-pane APM via OTEL):** Datadog LLM Observability, New Relic AI Monitoring, Dynatrace, Honeycomb, Grafana LGTM+OpenLIT, Traceloop/OpenLLMetry.

**They converge on seven sections** (the AI-native tools ship all seven; the APM tools ship 1–3 + partial 4):

| # | Section | What it is | Table-stakes? |
|---|---------|-----------|---------------|
| 1 | **Overview / Monitoring** | volume, latency percentiles, error rate, token usage, cost, feedback scores | ✅ table-stakes |
| 2 | **Traces** (the centerpiece) | hierarchical trace→span waterfall; span kinds LLM/tool/retrieval/agent/workflow with inputs, outputs, tokens, latency, per-span cost | ✅ table-stakes |
| 3 | **Sessions** | multi-turn conversations grouped + replay | ✅ table-stakes |
| 4 | **Evaluations** | online + offline, LLM-as-judge + heuristic/code scorers | ✅ table-stakes |
| 5 | **Datasets & Experiments** | curated from production traces, CI-gated | differentiator |
| 6 | **Prompts + Playground** | versioned prompts, replay against real production traces | differentiator |
| 7 | **Human feedback / Annotation queues** | thumbs/ratings, labeling queues routed from production | differentiator |

**The shared UX is one motion — layered drill-down:** overview metric → filtered session/trace list → session replay → trace waterfall → span → raw prompt/completion/tool-args/retrieved-docs. This *is* the "what → why, zoom-out → zoom-in" the brief asks for, and it is what we replicate natively.

**Notable differentiators (where AWS-native has gaps — §8):** topic/pattern clustering (Datadog Patterns), AI copilot investigators (Honeycomb Canvas, Arize Alyx, Braintrust Loop), one-click trace→dataset, prompt-playground replay on production traces, CI eval-gating, high-cardinality differential analysis (Honeycomb BubbleUp), unified cost across the *whole* agent workflow.

**The shared substrate is OpenTelemetry GenAI semantic conventions** (`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.request.model`, `gen_ai.operation.name`, tool spans, …). Our ADOT instrumentation already emits these — so **keeping the wire format OTEL gen_ai means a third-party tool remains a drop-in later** if a hard gap (annotation queues, dataset curation) ever becomes in-scope. We build native first.

---

## 2. Native capability inventory

### 2.1 Strands (the agent SDK)
- **Tracing:** auto-creates `invoke_agent` → `execute_event_loop_cycle` → `chat`/model-invoke → `execute_tool` spans, setting `gen_ai.usage.{input,output,total}_tokens`, `gen_ai.request.model`, `gen_ai.operation.name`. Emitted via ADOT (`opentelemetry-instrument` + `aws-opentelemetry-distro`) → OTLP → X-Ray.
- **Metrics:** `agent.event_loop_metrics.latest_agent_invocation.usage` (per-turn) — the source of our EMF token metric.
- **Hooks/callbacks:** usable to attach custom span attributes or capture a feedback/eval signal (currently unused).
- **Auto vs code:** spans + gen_ai attributes are auto; our only hand-written signal is the EMF token metric.

### 2.2 Bedrock (the model layer)
- **Vended metrics** `AWS/Bedrock`: `Invocations`, `InvocationLatency`, `InputTokenCount`, `OutputTokenCount`, `InvocationClientErrors`, `InvocationServerErrors`, `InvocationThrottles`, `CacheReadInputTokens`, `TimeToFirstToken` — dim `ModelId`.
- **Model-invocation logging:** one record per Converse call — `modelId`, identity, `inputTokenCount`/`outputTokenCount`, request/response bodies, and `requestMetadata`.
- **Guardrails** `AWS/Bedrock/Guardrails`: `InvocationsIntervened` dim `GuardrailPolicyType` + `GuardrailContentSource` (input vs output).
- **Cost:** **no USD metric anywhere.** `requestMetadata` does **not** reach CUR. Native USD attribution = Cost Explorer / CUR 2.0 via **IAM-principal attribution** (`line_item_iam_principal`, GA Apr 2026) or Application Inference Profile cost-allocation tags. Token×price-table is for finer-than-CUR (per-prompt) granularity only.

### 2.3 AgentCore
- **GenAI Observability** console: Agents View → Sessions View → Traces View — the same 3-tier drill-down the commercial tools use, **for runtime/policy only** (Memory/Gateway/Tools are CloudWatch-only, not in the GenAI page).
- **Transaction Search:** spans → `aws/spans` log group (must be enabled; ~1% indexed free).
- **Vended Runtime metrics** (`bedrock-agentcore` ns — *exact literal must be pinned*): `Invocations`, `Sessions`/`Session Count`, `Latency`, `SystemErrors`/`UserErrors`/`TotalErrors`, `Throttles`, `CPUUsed-vCPUHours`, `MemoryUsed-GBHours`.
- **Per-resource vended logs:** Runtime/Gateway/Memory `APPLICATION_LOGS`, Runtime `USAGE_LOGS` (per-session vCPU/GB-hours, ~60-min lag), Runtime/Gateway/Memory `TRACES`.
- **AgentCore Evaluations (GA 2026-03-31, native):** 13 LLM-judge evaluators (correctness, faithfulness, helpfulness, safety, task-completion, context-relevance) + deterministic trajectory matchers (expected vs actual tool sequence) + tool-selection/parameter accuracy. Online on sampled traces → `Bedrock-AgentCore-Evaluations` CloudWatch metrics, parented to the original span, drill-down in console. **Consumes the gen_ai spans we already emit — feasible now, not yet wired.**

### 2.4 AWS-native dashboard / alerting / governance surface
- **Visualization:** CloudWatch Dashboards (widget types: `metric`, `log` (Logs Insights results), `alarm`/`alarm-status`, `text`, `custom` (Lambda HTML) — **no trace-map widget**, §8); Metrics Insights (SQL `SELECT … FROM "<custom-ns>" GROUP BY <dim>`, ≤500 series); Logs Insights (saved `query_definition`s → widgets); Contributor Insights (top-N from JSON log fields, no metric dimensions needed); QuickSight for heavier BI over CUR/Athena.
- **Alerting/incident:** metric alarms, **anomaly-detection alarms (work on our custom EMF metrics)**, composite alarms (≤100 children), SNS, EventBridge (`source: aws.monitoring`) → AWS User Notifications / Chatbot. **Not Incident Manager** (closed to new customers, §8).
- **FinOps:** Cost Explorer, CUR 2.0 (`bcmdataexports`), Budgets, cost-allocation tags, Cost Anomaly Detection.
- **Security/Governance:** CloudTrail (InvokeModel = **management** event, §8), Logs data-protection PII mask (already live), Config, Audit Manager.
- **SLO:** Application Signals — **`awscc` provider only** (`awscc_applicationsignals_service_level_objective`; no `hashicorp/aws` resource), can target a custom metric.

---

## 3. What this repo emits TODAY (live-validated) vs the gaps

After Phases 0/1/2 (deployed + validated 2026-06-23, acct `953472632913` / `us-west-2`), **four native signal classes are live**:

| Signal | Source | Where | Validated |
|--------|--------|-------|-----------|
| **Token metric** `OrderTriage/Agent` `InputTokens`/`OutputTokens`/`TotalTokens` (dims `agent_id`+`model_id`) | EMF stdout from `runtime.py:_emit_usage_metric` | **runtime `-DEFAULT` log group** (NOT vended APPLICATION_LOGS) | `TotalTokens` Sum=6035; auto-extract works |
| **Per-call tokens + bodies + attribution** | Bedrock model-invocation logging | `/aws/bedrock/order-triage/modelinvocations` — `requestMetadata.{agent,actor,session,turn}` | 4 records/invoke (Nova-Lite ConverseStream ×2 + Titan-embed); N-per-turn share `turn` id; PII mask validated |
| **gen_ai + tool + OBO traces** | ADOT auto-instrumentation | X-Ray `aws/spans` (Transaction Search) — `gen_ai.usage.*`, `gen_ai.request.model`, Gateway CLIENT-span `TargetExecutionTime`, `GetWorkloadAccessTokenForJWT` | 37 gen_ai spans; Runtime+Gateway+Memory tracing now Enabled |
| **Vended ops metrics** | zero-config | `bedrock-agentcore` ns + `AWS/Bedrock/Guardrails` + Runtime `USAGE_LOGS` | flowing |

**Gaps a rich dashboard wants but we do NOT emit today:**
- ❌ **Per-invocation USD cost** — only token *counts* + vCPU/GB-hours (dollarization owned by FINOPS-SPIKE). Billing collapses all Entra users into one shared runtime role → no per-actor $ from billing alone; Snowflake credits not in AWS billing.
- ❌ **Eval/quality/groundedness scores** — AgentCore Evaluations native + feasible, **not wired**.
- ❌ **User feedback** — no thumbs/rating anywhere; no native annotation-queue equivalent.
- ⚠️ **Tool-level latency** — exists only inside Gateway CLIENT spans (`TargetExecutionTime`), **not a metric** → trace-query widget, can't alarm without a metric filter. Downstream Lambdas (sap/snowflake/order_actions) have no Active tracing.
- ⚠️ **Structured error taxonomy** — only `SystemErrors`/`Throttles`; no error-type dimension. P1.3 JWT warning shipped in agent; P1.4 webapp error change unmerged.
- ❌ **Deployment/version marker** — nothing ties a regression to a release (Phase 4 P4.4).
- ❌ **Zero dashboards / alarms / SLOs / SNS** — all of Phase 3.

---

## 4. Decision — multiple audience-scoped dashboards (SEVEN)

**Build SEVEN dashboards-as-code, not one mega-dashboard and not one-per-metric.**

- A **single pane** mixes audiences — the #1 documented IA failure (an exec scrolling past vCPU-GB-hours; an SRE hunting for budget burn). One-per-metric produces alarm-soup with no narrative.
- The **unit of a dashboard is one audience making one decision.** The seven interlock through a single shared **drill-down spine**, so they are a connected system, not silos — exactly mirroring the Overview→Sessions→Traces→Spans→raw-prompt motion every best-in-class tool converges on.

### IA model — *what / when-where / why* + zoom, on every dashboard
A 3-layer inverted pyramid where **the drill *is* the zoom**:

| Layer | Question | Source |
|-------|----------|--------|
| **WHAT** (zoom-out, top) | is anything wrong, how much, now | CloudWatch metric tiles + domain KPI |
| **WHEN/WHERE** (middle) | time-series broken down by `gen_ai.request.model` / `agent_id` / `gen_ai.tool.name` / session, with deploy/model-swap/policy-change **events** overlaid | metrics + Metrics Insights |
| **WHY** (zoom-in, bottom + click-through) | the exact trace + logs — offending span, prompt/tool payload, Cedar decision | X-Ray `aws/spans` + Logs Insights |

**Shared spine (identical motion on all 7):** metric tile → filtered TRACE list scoped by `session.id` / time → one TRACE (`invoke_agent`→`execute_event_loop_cycle`→`chat`→`execute_tool`) → correlated LOG line (model-invocation log / APPLICATION_LOGS payload / Cedar decision). **Join key = `session.id`** ⚠️ *must verify it is consistently emitted across agent/tool/gateway spans before building — the whole spine depends on it.*

### Audience-per-dashboard
| # | Dashboard | Audience | Domain | Layer emphasis |
|---|-----------|----------|--------|----------------|
| 1 | **Exec Rollup** | Leadership | cross-domain KPI | WHAT only; links down, never shows a trace |
| 2 | **Operations** | App-engineers | Operations | WHAT+WHEN; RED over USE |
| 3 | **Incident / On-call** | SRE / on-call | Incident | WHAT in seconds; fastest path down the spine |
| 4 | **FinOps** | Finance + eng-leads | FinOps | WHAT+WHERE; token→$ in-panel |
| 5 | **Security** | Security | Security | event + log heavy |
| 6 | **Governance / Audit** | Compliance / risk | Governance | append-only system-of-record |
| 7 | **Feedback & Evaluation** | App-eng + ML/quality | Feedback & Eval | score trend + regression-on-swap |

---

## 5. The seven dashboards (widget → exact AWS source)

> **Pinning prerequisite (blocks every vended-metric tile/alarm):** run `aws cloudwatch list-metrics` to fix the AgentCore namespace literal (`bedrock-agentcore` vs `AWS/BedrockAgentCore` vs `BedrockAgentCore`), the activity dimension key (`Resource`=ARN vs `Endpoint`/`AgentId`), and whether `Latency` supports p99 or only Average. Written `<AGENTCORE_NS>` below.

### D1 — Exec Rollup · *Is the agent healthy, what's it costing, is it safe & compliant — at a glance?*
- Success-rate number — `<AGENTCORE_NS>` `Invocations` − `TotalErrors`/`SystemErrors` (Sum).
- p95 latency number — `<AGENTCORE_NS>` `Latency` (ext-stat p95 if supported, else Average).
- Spend + budget-burn number — Cost Explorer / CUR 2.0 Bedrock spend (invoice-accurate); token-math $ as secondary near-real-time estimate.
- Open-incident count — `alarm` widget bound to the D3 composite "agent-unhealthy".
- Eval-quality sparkline — `Bedrock-AgentCore-Evaluations` (once wired).
- Guardrail interventions today — `AWS/Bedrock/Guardrails` `InvocationsIntervened` (Sum).
- **Drill:** each tile deep-links DOWN to its owning dashboard. Never renders a trace.

### D2 — Operations · *Where is latency/errors coming from?*
- Golden-signal header: Latency (`<AGENTCORE_NS>` `Latency`), Traffic (`Invocations`), Errors (`System/User/Total Errors`+`Throttles` split), Saturation (USE row).
- Per-tool latency — **Logs Insights over `aws/spans`**: `stats avg(), pct(TargetExecutionTime,95) by gen_ai.tool.name` (trace-only, not a metric).
- TTFT — `AWS/Bedrock` `TimeToFirstToken` (dim `ModelId`=`amazon.nova-lite-v1:0`) or span `gen_ai.server.time_to_first_token`.
- USE row — `CPUUsed-vCPUHours`, `MemoryUsed-GBHours`, `Session Count`, `Throttles`.
- KB retrieval health — `bedrock:Retrieve` span latency from `aws/spans`.
- **Drill:** latency spike → filtered trace list by time → trace → `execute_tool` span → Gateway `APPLICATION_LOGS` payload.

### D3 — Incident / On-call · *What's broken right now and what do I do?*
- Active alarms — `alarm-status` widget (all child + composite).
- RED time-series — `SystemErrors`, `Throttles`, `UserErrors`.
- USE directly below — so "users see errors" → "runtime saturated" is one glance.
- Last deploy / model-swap / guardrail-version — annotation marker (Phase 4 P4.4; manual until then).
- Runbook links + "jump to worst trace" — `text` widget deep-linking the X-Ray Trace Map filtered by fault.
- **Drill:** alarm → Logs Insights over `aws/spans` ranked by fault → worst trace → log.

### D4 — FinOps · *What are we spending, on what model/actor/session, where's the waste?*
- Token volume — EMF `OrderTriage/Agent` `Input/Output/TotalTokens` (Sum).
- Estimated $ in-panel — CloudWatch **metric-math** `(InputTokens × nova_lite_in) + (OutputTokens × nova_lite_out)` (Nova-Lite prices, NOT Opus).
- Invoice-accurate $ — Cost Explorer / CUR 2.0 panel keyed on **`line_item_iam_principal`** (IAM-principal attribution) or Application-Inference-Profile tag.
- Top actors/sessions by tokens — **Contributor Insights rule** over runtime `-DEFAULT` group, keys `$.actor_id`/`$.session_id`, `ValueOf=$.total_tokens`, `AggregateOn=Sum` (no metric dims needed).
- Cache savings — `AWS/Bedrock` `CacheReadInputTokens` / `cache_read_input_tokens` log field.
- Per-call + KB-embedding cost — Logs Insights over `/aws/bedrock/order-triage/modelinvocations` `GROUP BY requestMetadata.turn`.
- **Drill:** cost tile → top sessions (Contributor Insights) → the trace that burned tokens → its prompt in the model-invocation log.

### D5 — Security · *Are auth/tool calls behaving, is anyone abusing the agent?*
- Guardrail interventions split — `AWS/Bedrock/Guardrails` `InvocationsIntervened` by `GuardrailPolicyType`+`GuardrailContentSource`. (Today PROMPT_ATTACK only — covers prompt-injection block-rate.)
- Authz/OBO outcomes — Logs Insights over `aws/spans` `GetWorkloadAccessTokenForJWT(issuer,user_sub)` + Cedar/Gateway decision logs (must be routed into the same group — §6 Security).
- Anomalous/denied tool calls — Logs Insights on `gen_ai.tool.name` + status=error; Contributor Insights top denied-tool callers.
- Caller-identity audit — CloudTrail **management** events for `InvokeModel`/`Converse` (who/model/when — §8).
- **Drill:** anomaly → trace → exact `gen_ai.tool.call.arguments` (PII-masked).

### D6 — Governance / Audit · *Who did what, with which model/version/params, against which data?*
- Per-turn model + params record — Logs Insights over `/aws/bedrock/order-triage/modelinvocations`: `modelId`, `identity.arn`, params, `requestMetadata.{agent,actor,session,turn}`.
- Policy decisions — Cedar/Gateway decision logs (`hasTag("scp")` outcomes).
- Data-source access — `bedrock:Retrieve` spans / KB `gen_ai.data_source.id`.
- Config/policy change events — CloudTrail (guardrail-version, IAM edits).
- Retention/PII posture — `aws_cloudwatch_log_data_protection_policy` status (5-identifier mask).
- **Drill:** query by `session.id`/`actor`/`turn` → the immutable record. *Safer default: enable object-lock on the modelinvocations group for a true system-of-record.*

### D7 — Feedback & Evaluation · *Is quality holding, did a model swap regress it?*
- Eval-score trend — `Bedrock-AgentCore-Evaluations` (Correctness, Faithfulness, Helpfulness, Tool-Selection/Parameter accuracy, Harmfulness) over time + by model/version. **Requires wiring online Evaluations config.**
- Regression-on-swap — score series with model-swap event overlay.
- Tool-trajectory accuracy — AgentCore trajectory matchers (expected vs actual tool sequence).
- Human feedback — **HARD GAP, no native source.** Mark "not instrumented."
- **Drill:** score drop → low-scoring trace (Evaluations parent to the original span) → its `gen_ai.input.messages`/`gen_ai.output.messages`.

---

## 6. Domain-by-domain build (mechanism · signal · honest gap)

- **FinOps** — metric-math over EMF token metric × Nova-Lite price (near-real-time estimate) + CUR 2.0 IAM-principal panel (invoice-accurate), reconcile on usage-type/day. *Gap:* no USD metric; `requestMetadata` ∉ CUR; Memory SUMMARIZATION call runs under a different principal; Snowflake credits not in AWS billing.
- **Operations** — vended RED metrics + USE rows. *Gap:* per-tool latency is trace-only (Logs Insights widget, not alarmable without a metric filter); downstream Lambdas opaque (need Active tracing).
- **Security** — Guardrails metrics + CloudTrail management events + `aws/spans` OBO/tool spans + Cedar logs. *Gap:* guardrail PROMPT_ATTACK-only; Cedar decision logs must be routed into the spine's log group (new wiring).
- **Incident** — composite alarm over anomaly + static child alarms → SNS + EventBridge → User Notifications/Chatbot. *Gap:* no error taxonomy yet (no error-type dimension to alarm on); **do NOT use Incident Manager** (closed to new customers).
- **Governance/Audit** — model-invocation logging (append-only) + CloudTrail + PII mask. *Gap:* queryable Logs view today, not a true immutable record — recommend object-lock.
- **Feedback & Evaluation** — **AgentCore Evaluations (native, GA, consumes existing spans)** online on sampled traces → CloudWatch metrics. *Gap:* not wired; human-feedback queues have **no** native equivalent — the one domain with zero data and the strongest (out-of-scope) case for an OTEL-fed third party later.

---

## 7. Signal gaps & prerequisites (ordered — do before dashboards are meaningful)

1. **Pin the vended-metric contract** — `list-metrics` read-back: `<AGENTCORE_NS>`, dimension key, `Latency` percentile support, `InvocationsIntervened` dim value (ARN vs id). *Blocks every metric tile/alarm.*
2. **Confirm `session.id` is the single canonical correlation id** across agent/tool/gateway spans. *The entire drill-down spine depends on it.*
3. **Wire AgentCore Evaluations online config** — native, feasible now; only source for D7 + the Exec quality tile + eval alarms.
4. **Add an error-taxonomy dimension** — merge webapp P1.4; emit structured `error_type` so Incident/Ops alarm on classes, not just `SystemErrors`. Stop leaking raw body to browser.
5. **Route Cedar/Gateway authz decision logs + CloudTrail** into the spine's log group/index so Security & Governance correlate against traces.
6. **Decide + add a human-feedback signal** (webapp thumbs/rating) if D7 feedback is in scope — nothing emits it today.
7. **Confirm FinOps attribution path** — IAM-principal vs Application Inference Profiles for invoice-accurate $ (already injecting `requestMetadata` — good; it can't be backfilled).
8. **Add Lambda Active tracing + structured timing** (sap/snowflake/order_actions) to de-opaque below-Gateway latency.
9. **Governance: enable object-lock** on the modelinvocations group if a true system-of-record is required.

---

## 8. Corrections from adversarial verification (10 claims; 4 changed the design)

1. **REFUTED — dashboard can embed an X-Ray/ServiceLens trace-map widget.** Widget types are `metric`/`log`/`alarm`/`text`/`custom` only. → spine's trace step is a Logs Insights `log` widget over `aws/spans` **+ a deep-link** to the X-Ray Trace Map page (or a `custom` Lambda widget). **Don't promise an inline trace map.**
2. **UNCERTAIN/partly-REFUTED — "per-agent cost must be token×price."** No USD metric and `requestMetadata` ∉ CUR are true, but per-agent/per-actor *aggregated invoice-accurate* $ IS native via **IAM-principal attribution** (`line_item_iam_principal`, CUR 2.0) + Application Inference Profile tags. → FinOps pairs token-math *estimate* (granularity) with a CUR 2.0 IAM-principal *invoice* panel.
3. **REFUTED — CloudTrail captures InvokeModel as DATA events.** `InvokeModel`/`Converse` are **management** events (caller/modelId/IP/time, no payloads/tokens). → Security/Governance use management events (already on, no selector); payloads/tokens come from invocation logging / spans.
4. **REFUTED — use Incident Manager for escalation.** Closed to new customers. → composite alarm → SNS + EventBridge (`aws.monitoring`) → AWS User Notifications / Chatbot.
5. **CONFIRMED (load-bearing, kept):** anomaly detection works on EMF custom metrics (pair with ≤5s flush + "M-of-N" datapoints); Metrics Insights `GROUP BY` on custom-ns dims drives a widget (≤500 series); Contributor Insights ranks top-N from JSON log fields with no metric dims; Application Signals SLOs are `awscc`-only; AgentCore Evaluations is fully native; Guardrails emit `InvocationsIntervened` by policy-type/content-source.

---

## 9. Build plan (Terraform — provider noted per resource; sequenced)

> **STATUS 2026-06-23 — BUILT + `terraform validate`/`plan` clean (21 add / 0 destroy), NOT yet deployed.** Files in `../../terraform/`: `monitoring.tf`, `alarms.tf`, `slo.tf`, `queries.tf`, `evaluations.tf`, `dashboards.tf` (Operations+Incident), `dashboards_extra.tf` (Exec/FinOps/Security/Governance/Feedback); deploy-role IAM in `bootstrap/github_oidc.tf`. All 7 dashboards + 6 alarms + 2 SLOs + 2 Contributor Insights rules + 3 saved queries + SNS topic. Evaluations enablement is var-gated (`enable_online_evaluations`, default off) — a reviewed `bedrock-agentcore-control` step. Live render/alarm validation is post-deploy.

**3a — Telemetry enablement (ship WITH the dashboards):**
- AgentCore Evaluations online config (no clean TF resource — likely `awscc`/SDK/`local-exec`; verify) — prereq for D7.
- Confirm `aws_cloudwatch_log_data_protection_policy` mask (`hashicorp/aws`).
- Route Cedar/Gateway decision logs + CloudTrail into the shared log group (`aws_cloudwatch_log_subscription_filter` / delivery resources, `hashicorp/aws`).

**3b — Saved queries + insight rules (dashboards reference these):**
- `aws_cloudwatch_query_definition` (`hashicorp/aws`) — per-session token sum over `-DEFAULT`; per-turn `GROUP BY requestMetadata.turn`; Gateway CLIENT-span `TargetExecutionTime` by tool; OBO `GetWorkloadAccessTokenForJWT`; per-call governance record.
- `aws_cloudwatch_contributor_insight_rule` (`hashicorp/aws`) — top actors/sessions by `$.total_tokens` (FinOps); top denied-tool callers (Security).
- Metric filters (`aws_cloudwatch_log_metric_filter`) — **fallback only** (EMF auto-extract is validated; add only to make tool-latency or `error_type` alarmable).

**3c — Dashboards** — one `aws_cloudwatch_dashboard` module each (`hashicorp/aws`, `dashboard_body` JSON, env/region vars), D1–D7. Widgets: `metric` (incl. Metrics Insights), `log`, `alarm`/`alarm-status`, `text`; `custom` (Lambda) only if a trace visual is required. **No trace-map widget.**

**3d — Alarms + escalation (`hashicorp/aws`):**
- `aws_sns_topic` + email subscription.
- `aws_cloudwatch_metric_alarm`: static — `SystemErrors`>0, `Throttles`, `Latency` p99 (if percentile supported, else trace-query); anomaly — on EMF `TotalTokens` and `Invocations`; Guardrail `InvocationsIntervened`. All `treat_missing_data=notBreaching` (idle-demo flapping). Anomaly caveats: no SEARCH/METRICS, ≤10 metrics, period ≤1h.
- `aws_cloudwatch_composite_alarm` — "agent-unhealthy" rollup (feeds D1 + D3).
- `aws_cloudwatch_event_rule` — `{"source":["aws.monitoring"],"detail-type":["CloudWatch Alarm State Change"]}` → User Notifications / Chatbot.
- Eval-score alarm — on `Bedrock-AgentCore-Evaluations` (after 3a).

**3e — FinOps cost layer (`hashicorp/aws`):**
- `aws_bcmdataexports_export` — CUR 2.0 with caller-identity (`line_item_iam_principal`).
- `aws_ce_anomaly_monitor` + `aws_ce_anomaly_subscription` — Bedrock cost anomaly.
- `aws_budgets_budget` — budget-burn for D1/D4. (Cost-allocation-tag activation = manual/CLI.)
- `aws_quicksight_*` — only if BI over S3/Athena beyond CloudWatch is needed; defer.

**3f — SLOs (deferred / `awscc` only):**
- `awscc_applicationsignals_service_level_objective` targeting a custom metric via `sli.sli_metric.metric_data_queries`. Low-rate API, AgentCore not auto-discovered — the p99 latency alarm covers the operational need in the interim.

---

## 10. Net assessment

AWS-native cleanly delivers, at the best-in-class bar: **Overview, Operations, Incident, Sessions/Traces drill-down (with the instrumentation we already have), token-level analysis, FinOps (estimate + invoice-accurate), Security, Governance, and — once wired — native Evaluations.** It does **not** natively deliver: dollar-cost *per trace inline*, online eval scoring rendered *on the trace view*, **human annotation queues**, dataset/experiment curation, prompt-playground replay, or topic clustering. None of those are in Phase-3 scope; the only one with a real future business case (human feedback) is best served by adding a feedback signal now and, if it ever grows, an OTEL-fed third party reading the **same gen_ai spans** — zero rework, because we keep the wire format OTEL.

# OBSERVABILITY — Implementation & Validation Plan

> Executable companion to **[OBSERVABILITY-SPIKE.md](../research/observability-spike.md)** (analysis/root-cause) and cross-referenced with **[FINOPS-SPIKE.md](../research/finops-spike.md)** (token→dollar derivation — NOT duplicated here). Read the spike first; this document is the *what-to-change, in-what-order, how-to-prove-it*. All file:line citations below were re-verified in-tree on 2026-06-23.

> **✅ STATUS — Phase 0 DEPLOYED & VALIDATED (2026-06-23, live, account 953472632913 / us-west-2).** The five delivery trios (P0.1–P0.5) were added to [observability.tf](../../terraform/observability.tf) → `terraform validate` clean → `make plan` = **18 add / 0 change / 0 destroy** → `make deploy` applied all 18. `describe-delivery-sources`/`describe-deliveries` confirm Runtime+Gateway each have TRACES→XRAY + APPLICATION_LOGS→CWL, plus Runtime USAGE_LOGS→CWL (console *Tracing: Enabled* for Runtime/Gateway/Identity). A live `make status` invoke produced **37 gen_ai spans in `aws/spans`** carrying `gen_ai.usage.{input,output,total}_tokens` + `gen_ai.request.model`. **Resolved open questions: Q1 → `AGENT_OBSERVABILITY_ENABLED` is NOT required (token spans flow without it) ⇒ P0.6 SKIPPED; Q2 → the provider accepts the `USAGE_LOGS` enum (no local-exec fallback).** Residual nuance: the literal `InvokeAgentRuntime` *service* span string was not found (0) — the AgentCore-managed service span is named differently or not emitted; the valuable application/gen_ai/tool spans ARE present. USAGE_LOGS *records* lag up to ~60 min.

> **✅ STATUS — Phase 2 DEPLOYED & VALIDATED (2026-06-23, live).** Added `invocation_logging.tf` (model-invocation logging behind the PII mask) + `log_groups.tf` (Lambda retention, 3 groups imported first) + retention vars → `terraform validate` clean → `make plan` = **5 add / 3 change / 0 destroy** → applied (mask created *before* the logging config; no 403). Pre-flight probes resolved: **singleton config absent** (no overwrite); **all 5 PII identifier ARNs live-verified** via throwaway-group probe; Lambda groups imported. Validation: `get-model-invocation-logging-configuration` shows the CWL config + role; `get-data-protection-policy` shows Audit+Deidentify w/ 5 identifiers; a `make status` invoke landed **4 records with `inputTokenCount`/`outputTokenCount`** (nova-lite ConverseStream ×2 + titan-embed InvokeModel — confirming per-call token capture + KB-embedding visibility + N-records-per-turn). **P2.4 (S3) and P2.7 (cost tags) deferred.** Committed on [PR #78](https://github.com/aniryou/bedrock-demo-infra/pull/78) (Phase 0 + Phase 2).

> **✅ STATUS — Phase 1 DEPLOYED & VALIDATED LIVE (2026-06-23).** Agent code: [order-triage-agent#24](https://github.com/aniryou/order-triage-agent/pull/24) — P1.1 per-turn token usage → EMF (`agent.event_loop_metrics.latest_agent_invocation.usage`, no span attr), P1.2 `requestMetadata` via `additional_args`, P1.3 structured JWT-decode warning. Shipped: #24 merged → `build.yml` pushed image `:39b482bc9206` → auto `repository_dispatch` → deploy run 27999155796 (gated-approved) → runtime+endpoint rolled. **Both flagged uncertainties resolved POSITIVELY:** (1) `OrderTriage/Agent` metric materialized with a real datapoint (`TotalTokens` Sum=6035, dims `agent_id`+`model_id`) — **EMF auto-extraction works, no metric-filter fallback needed**; the agent stdout/EMF lands in the runtime **`-DEFAULT`** log group (`…/runtimes/order_triage-cwG2Pw7Bnv-DEFAULT`), not the Phase 0 APPLICATION_LOGS vended group (Phase 3 Logs Insights should query `-DEFAULT`). (2) `requestMetadata.{agent,actor,session,turn}` confirmed on streaming ConverseStream records (actor = Entra sub GUID, opaque); the N per-cycle records of one turn **share a `turn` id** (per-turn grouping works). P1.4 webapp ([order-triage-webapp#8](https://github.com/aniryou/order-triage-webapp/pull/8)) is local-only — merge + restart uvicorn. **Remaining: Phase 3 (dashboards/alarms — can now chart `OrderTriage/Agent` + vended metrics), Phase 4 (sampling/KB-ingestion).**

---

## 1. Objective & guardrails

Light up the **dormant AgentCore-native observability surface** that the spike found switched off — per-resource Tracing/Log-delivery on **Runtime, Gateway, and (transitively) WorkloadIdentity**, plus token-usage capture, model-invocation logging, and a proactive dashboard/alarm layer — using **only AWS-native services** (CloudWatch, X-Ray/Transaction Search, GenAI Observability, Application Signals). **Zero third-party tooling; all telemetry stays in-account.** The single non-negotiable ordering constraint that gates everything PII-bearing: **the CloudWatch Logs data-protection (PII mask) policy MUST exist on a destination log group BEFORE any request/response body is logged to it** — every record that lands in the gap is stored unmasked permanently and cannot be retroactively masked. FinOps dollarization (price map, CUR, cost EMF) is **owned by [FINOPS-SPIKE.md](../research/finops-spike.md)** — this plan only makes the token counts and PII-safe bodies *land durably*.

---

## 2. Sequenced phases

Five phases. **Phase 0 must be applied and live-validated before Phase 1's empirical spike. Phase 2's PII gate (P2.2) is a hard `depends_on` of logging-on (P2.3).** Phases 3–4 are independent of 0–2 except where a metric namespace must be read back live.

### Phase 0 — Flip the dormant per-resource delivery toggles (Runtime + Gateway)

Confirmed **not a no-op**: the console (verified 2026-06-23) shows Runtime *and* Identity tabs at "Tracing: Not enabled / Log delivery (0)". Only the **Memory** resource got the delivery trio ([observability.tf:51-92](../../terraform/observability.tf)). We clone that exact, deployed-and-working pattern against the Runtime and Gateway ARNs. The Identity tab has **no standalone resource** — it lights up transitively (see P0.7).

| id | change | target file | effort | risk |
|----|--------|-------------|--------|------|
| P0.1 | Runtime `APPLICATION_LOGS` → vended CWL group | `observability.tf` (append after :92) | low | **PII** (payloads unmasked) |
| P0.2 | Runtime `USAGE_LOGS` → vended CWL group (vCPU/GB-hours) | same | low | none |
| P0.3 | Runtime `TRACES` → X-Ray (flips "Tracing: Enabled") | same | low | eventual-consistency |
| P0.4 | Gateway `APPLICATION_LOGS` → vended CWL group | same | low | **PII** (tool payloads) |
| P0.5 | Gateway `TRACES` → X-Ray | same | low | eventual-consistency |
| ~~P0.6~~ | ~~`AGENT_OBSERVABILITY_ENABLED=true`~~ — **SKIPPED: validated unnecessary** (gen_ai token spans flow without it) | — | — | — |
| P0.7 | Identity/WorkloadIdentity — **NON-ACTION** (no resource to target); **confirmed: console Identity tab now reads Enabled transitively** | n/a | trivial | none (prevents a guaranteed-fail apply) |

**Verified attributes** (do not guess): `aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn` ([outputs.tf:30](../../terraform/outputs.tf)), `aws_bedrockagentcore_agent_runtime.this.agent_runtime_id`, `aws_bedrockagentcore_gateway.this.gateway_arn` ([policy.tf:44](../../terraform/policy.tf)), `aws_bedrockagentcore_gateway.this.gateway_id` ([gateway.tf:44](../../terraform/gateway.tf)). The Memory TRACES block ([observability.tf:78-92](../../terraform/observability.tf)) proves the XRAY destination shape: `delivery_destination_type = "XRAY"`, **no** config block, and `depends_on = [terraform_data.transaction_search]`. `aws_cloudwatch_log_resource_policy.xray_spans` ([observability.tf:10](../../terraform/observability.tf)) already grants xray→`aws/spans` PutLogEvents — **no new resource policy needed.** Note the Memory source uses plain `.arn`/`.id`, but the Runtime/Gateway resources expose the *named* `agent_runtime_arn`/`gateway_arn` attributes — use those.

```hcl
# --- P0.1 Runtime APPLICATION_LOGS (clone of memory_logs trio) ---
resource "aws_cloudwatch_log_group" "runtime_app" {
  name              = "/aws/vendedlogs/bedrock-agentcore/runtime/APPLICATION_LOGS/${aws_bedrockagentcore_agent_runtime.this.agent_runtime_id}"
  retention_in_days = var.memory_log_retention_days
}
resource "aws_cloudwatch_log_delivery_source" "runtime_logs" {
  name = "${var.name_prefix}-runtime-app-logs"; log_type = "APPLICATION_LOGS"
  resource_arn = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
}
resource "aws_cloudwatch_log_delivery_destination" "runtime_logs" {
  name = "${var.name_prefix}-runtime-app-logs"
  delivery_destination_configuration { destination_resource_arn = aws_cloudwatch_log_group.runtime_app.arn }
}
resource "aws_cloudwatch_log_delivery" "runtime_logs" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.runtime_logs.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.runtime_logs.arn
}

# --- P0.2 Runtime USAGE_LOGS (Runtime-only log_type) ---
resource "aws_cloudwatch_log_group" "runtime_usage" {
  name              = "/aws/vendedlogs/bedrock-agentcore/runtime/USAGE_LOGS/${aws_bedrockagentcore_agent_runtime.this.agent_runtime_id}"
  retention_in_days = var.memory_log_retention_days
}
resource "aws_cloudwatch_log_delivery_source" "runtime_usage" {
  name = "${var.name_prefix}-runtime-usage-logs"; log_type = "USAGE_LOGS"
  resource_arn = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
}
resource "aws_cloudwatch_log_delivery_destination" "runtime_usage" {
  name = "${var.name_prefix}-runtime-usage-logs"
  delivery_destination_configuration { destination_resource_arn = aws_cloudwatch_log_group.runtime_usage.arn }
}
resource "aws_cloudwatch_log_delivery" "runtime_usage" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.runtime_usage.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.runtime_usage.arn
}

# --- P0.3 Runtime TRACES → X-Ray (clone of memory_traces pair) ---
resource "aws_cloudwatch_log_delivery_source" "runtime_traces" {
  name = "${var.name_prefix}-runtime-traces"; log_type = "TRACES"
  resource_arn = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
}
resource "aws_cloudwatch_log_delivery_destination" "runtime_traces" {
  name = "${var.name_prefix}-runtime-traces"; delivery_destination_type = "XRAY"
}
resource "aws_cloudwatch_log_delivery" "runtime_traces" {
  depends_on               = [terraform_data.transaction_search]
  delivery_source_name     = aws_cloudwatch_log_delivery_source.runtime_traces.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.runtime_traces.arn
}

# --- P0.4 Gateway APPLICATION_LOGS + P0.5 Gateway TRACES: same two patterns,
#     resource_arn = aws_bedrockagentcore_gateway.this.gateway_arn,
#     group path .../gateway/APPLICATION_LOGS/${aws_bedrockagentcore_gateway.this.gateway_id}
```

**`USAGE_LOGS` enum caveat (medium-confidence):** `USAGE_LOGS` is a newer enum than `APPLICATION_LOGS`/`TRACES`. If `terraform plan` errors *"expected log_type to be one of"*, fall back to a `terraform_data` local-exec mirroring `terraform_data.transaction_search` ([observability.tf:35](../../terraform/observability.tf)): `aws logs put-delivery-source --log-type USAGE_LOGS ...`. **Confirm on first plan.**

**Dependencies / ordering:** P0.3/P0.5 `depends_on terraform_data.transaction_search`. On a fresh account the X-Ray PutLogEvents pre-flight lags minutes after the resource policy (the Memory TRACES block carries this same caveat) — **a re-apply settles it.**

**Definition of Done (P0):** After one live `make status` invoke — Console *Agent Runtime → Tracing* reads **Enabled** and *Gateway → Tracing* reads **Enabled**; `aws logs describe-deliveries` lists `runtime-traces`/`gateway-traces` (deliveryDestinationType XRAY) and the two APPLICATION_LOGS deliveries; and the **strengthened span check in §3 returns ≥1 row** (not merely "delivery exists").

---

### Phase 1 — gen_ai spans, token capture, requestMetadata, structured errors (agent + webapp code)

| id | change | target file | effort | risk |
|----|--------|-------------|--------|------|
| P1.1 | Capture dropped per-turn token usage → EMF + span attr | [runtime.py:65-74](../../../agent/src/order_triage/runtime.py) | low | **medium-conf** (event shape) |
| P1.2 | Inject Bedrock `requestMetadata` tags (agent/session/actor) | [agent.py:68-76](../../../agent/src/order_triage/agent.py) | low | medium |
| P1.3 | Structured log on silent JWT-decode fallback | [identity.py:46-55](../../../agent/src/order_triage/identity.py) | trivial | none |
| P1.4 | Structured server log on webapp invocation failure + stop leaking body to browser | [main.py:181](../../../app/app/main.py) | trivial | none |

**P1.1 — VERIFIED IN-TREE:** runtime.py's loop today yields `event["data"]` then falls through to `step_events(event)` and **does NOT handle a `"result"` key** — so the terminal `AgentResult` is silently discarded (confirmed runtime.py:67-74). **strands-agents is NOT installed in this repo's env** (verified — `import strands` fails), so the `{"result": AgentResult}` shape and `.metrics.accumulated_usage` TypedDict are **external claims, NOT verified here**. → **Implement with the documented fallback so capture does not depend on the unverified event shape:**

```python
import json, logging, time
from opentelemetry import trace as _otel_trace
log = logging.getLogger("order_triage.usage")
_NS = "OrderTriage/Agent"

def _emit_usage_emf(usage, *, agent_id, model_id, session_id, actor):
    inp = int(usage.get("inputTokens", 0)); out = int(usage.get("outputTokens", 0))
    tot = int(usage.get("totalTokens", inp + out))
    emf = {"_aws": {"Timestamp": int(time.time()*1000), "CloudWatchMetrics": [{
              "Namespace": _NS,
              "Dimensions": [["agent_id", "model_id"]],          # ONLY metric dimensions
              "Metrics": [{"Name": n, "Unit": "Count"} for n in ("InputTokens","OutputTokens","TotalTokens")]}]},
           "agent_id": agent_id, "model_id": model_id,
           "InputTokens": inp, "OutputTokens": out, "TotalTokens": tot,
           "session_id": session_id, "actor_id": actor,         # root log fields, NOT dimensions
           "cache_read_input_tokens": int(usage.get("cacheReadInputTokens", 0)),
           "cache_write_input_tokens": int(usage.get("cacheWriteInputTokens", 0))}
    print(json.dumps(emf), flush=True)
    span = _otel_trace.get_current_span()
    if span and span.is_recording():
        span.set_attribute("gen_ai.usage.total_tokens", tot)

# inside `with gw_client:`  — result-branch FIRST so the AgentResult is never yielded:
with gw_client:
    agent = build_agent(session_id=session_id, actor_id=identity.actor_id(),
                        extra_tools=gw_client.list_tools_sync())
    async for event in agent.stream_async(prompt):
        if isinstance(event, dict) and "result" in event:        # terminal AgentResult
            continue                                             # do not yield; usage read below
        if isinstance(event, dict) and "data" in event:
            yield event["data"]; continue
        for step in step_events(event):
            yield step
    # FALLBACK (shape-independent): read accumulated usage after the stream completes.
    m = getattr(agent, "event_loop_metrics", None)
    u = getattr(m, "accumulated_usage", None) if m else None
    if u:
        _emit_usage_emf(dict(u), agent_id="order-triage",
                        model_id=get_config().bedrock_model_id,
                        session_id=session_id, actor=identity.actor_id())
```

> **Cardinality rule (confirmed correct, not a defect):** EMF `Dimensions = [["agent_id","model_id"]]` only; `session_id`/`actor_id`/`cache_*` are root-level queryable log fields. No cardinality explosion.

**P1.2 — requestMetadata.** agent.py BedrockModel today has **no `additional_args`** (verified :69-74). Add it; Strands spreads `additional_args` at the top level of the Converse request. Values must be **opaque ids only** (actor = Entra `sub` GUID, session = runtime hex) — never email/name. Cap `[:256]`, charset `[a-zA-Z0-9 _@$#=/+,.:-]`. `build_agent` gains an `actor_id` param. **This is inert until Phase 2 model-invocation logging is on** — overlaps FINOPS-SPIKE Tier-1; **tag here, defer dollarization to [FINOPS-SPIKE.md](../research/finops-spike.md).**

**P1.3 / P1.4 — structured errors.** identity.py:46-55 swallows the bad-JWT path silently (verified) → log a warning carrying **no token bytes, no claim values** (capped key names only). main.py:181 (`except Exception as exc:`, verified) ships up to 600 chars of raw runtime body to the **browser** → replace with `log.exception(...)` server-side + a generic `{"type":"error","detail":"agent invocation failed; see server logs"}` to the client.

**Definition of Done (P1):** A live invoke yields a **non-zero `TotalTokens` datapoint** in namespace `OrderTriage/Agent` (graphed by agent_id,model_id) AND the Logs-Insights per-session token sum (§3) returns rows; a forced bad JWT logs exactly one `jwt_subject_decode_failed`; a forced upstream 4xx logs one `agent_invocation_failed` with traceback and the browser sees no raw body.

---

### Phase 2 — Bedrock model-invocation logging behind the PII gate + retention/tags

| id | change | target file | effort | risk |
|----|--------|-------------|--------|------|
| P2.1 | CWL group + Bedrock-trusted IAM role (empty, no PII yet) | new `invocation_logging.tf` | low | none |
| **P2.2** | **PII data-protection (mask) policy — BLOCKING PREREQ** | `invocation_logging.tf` | medium | **the PII floor** |
| P2.3 | Turn ON `aws_bedrock_model_invocation_logging_configuration` (singleton) | `invocation_logging.tf` | low | **PII / overwrite** |
| P2.4 | *(deferred)* optional S3 destination — **mask does NOT cover S3** | — | medium | **unmasked PII** |
| P2.5 | retention vars (`bedrock_invocation_log_retention_days`, `function_log_retention_days`) | `variables.tf` (:74 area) | trivial | none |
| P2.6 | retention on the 3 Lambda groups (import-first) | new `log_groups.tf` | low | import trap |
| P2.7 | `CostCenter`/`Environment` default_tags | `versions.tf` (:33-38) | trivial | in-place updates |

**Critical ordering edge:** `aws_bedrock_model_invocation_logging_configuration` (P2.3) **`depends_on` the data-protection policy (P2.2)**. Do **not** split the apply such that P2.3 lands before P2.2 succeeds — any record in that gap is stored unmasked forever. P2.3 is an **account+region SINGLETON** (one per region) — declaring it in TF silently overwrites any console-set config; **confirm none exists in us-west-2 first** (`aws bedrock get-model-invocation-logging-configuration --region us-west-2`).

**P2.2 — corrected per review.** Drop the unverified `Name` and `Address` managed-identifier ARNs (generic `Name`/`Address` are **not** in the CloudWatch Logs managed set — an unknown ARN rejects the *entire* policy). Verify each remaining ARN against the AWS "protect-sensitive-log-data-types" page before apply. Free-text customer names have **no managed identifier** — accept they are unmasked or add a custom regex identifier (out of scope). Audit statement first, Deidentify second, **identical `DataIdentifier` arrays**, `MaskConfig={}`, `FindingsDestination={}` (a real sink must be a *separate* pre-existing group — never self-referential).

```hcl
locals {
  pii_identifiers = [   # VERIFY each ARN before apply; CreditCardNumber is FINANCIAL category
    "arn:aws:dataprotection::aws:data-identifier/EmailAddress",
    "arn:aws:dataprotection::aws:data-identifier/PhoneNumber-US",
    "arn:aws:dataprotection::aws:data-identifier/Ssn-US",
    "arn:aws:dataprotection::aws:data-identifier/DriversLicense-US",
    "arn:aws:dataprotection::aws:data-identifier/CreditCardNumber",
  ]   # Name/Address REMOVED — not confirmed valid managed identifiers
}
resource "aws_cloudwatch_log_data_protection_policy" "bedrock_invocations" {
  log_group_name  = aws_cloudwatch_log_group.bedrock_invocations.name
  policy_document = jsonencode({
    Name = "${var.name_prefix}-bedrock-pii-mask", Version = "2021-06-01"
    Statement = [
      { Sid = "Audit",      DataIdentifier = local.pii_identifiers, Operation = { Audit      = { FindingsDestination = {} } } },
      { Sid = "Deidentify", DataIdentifier = local.pii_identifiers, Operation = { Deidentify = { MaskConfig = {} } } },
    ]
  })
}
resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  depends_on = [
    aws_cloudwatch_log_data_protection_policy.bedrock_invocations,   # PII mask MUST exist first
    aws_iam_role_policy.bedrock_invocation_logging,
  ]
  logging_config {
    text_data_delivery_enabled      = true   # nova-lite = text + embedding only
    embedding_data_delivery_enabled = true
    image_data_delivery_enabled     = false
    video_data_delivery_enabled     = false
    # large_data_delivery_s3_config DELIBERATELY UNSET — bodies >100KB are TRUNCATED in CWL,
    # not spilled to an unmasked S3 path. Setting it reintroduces the unmasked-S3 PII risk.
    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.bedrock_invocations.name
      role_arn       = aws_iam_role.bedrock_invocation_logging.arn
    }
  }
}
```

**>100KB overflow caveat (review-added):** Bedrock offloads any body >100KB to S3 via `large_data_delivery_s3_config`; the CWL mask does **not** cover S3, and Snowflake customer rows can exceed 100KB. Leave it **unset** (bodies truncate in CWL — acceptable for a PII workload). **P2.4 (S3) stays deferred** — only with KMS + Macie + a separate review.

**IAM trust (P2.1):** `Principal = bedrock.amazonaws.com`, `Condition` = `StringEquals aws:SourceAccount` + `ArnLike aws:SourceArn = arn:aws:bedrock:${var.region}:${acct}:*`. Confirm Bedrock presents a matching SourceArn or AssumeRole fails silently and logs never write. `data.aws_caller_identity.current` already exists (observability.tf). On first apply, IAM propagation can 403 `PutModelInvocationLoggingConfiguration` — **re-run** (or add a small `time_sleep`, mirroring the existing `gateway_iam_propagation_delay` pattern).

**P2.6 import trap:** if a `/aws/lambda/order-triage-*` group already exists from a prior auto-create, `terraform apply` errors *"already exists"* — **`terraform import` each first.** Lambda resources verified: sap_lambda.tf, snowflake_lambda.tf (returns customer rows — PII-relevant), order_actions_lambda.tf. AgentCore Runtime/Gateway groups are created **by the Phase-0 delivery trios** — do NOT also create plain groups for them here.

**Definition of Done (P2):** `get-model-invocation-logging-configuration` shows the CWL config + role + `textDataDeliveryEnabled=true`; the **masked-PII check in §3 passes both directions** (masked without `logs:Unmask`, raw with); all `/aws/lambda/order-triage-*` show `retentionInDays`; `default_tags` reaches taggable resources.

---

### Phase 3 — Proactive monitoring layer (dashboards, alarms, anomaly, SNS)

| id | change | target file | effort | risk |
|----|--------|-------------|--------|------|
| P3.1 | SNS topic + email sub (dependency root) | new `alerting.tf` | trivial | none |
| P3.2 | Runtime dashboard (Invocations/Sessions/Errors/Latency/vCPU+GB-hours) | `alerting.tf` | medium | **blank-if-wrong-namespace** |
| P3.3 | Static alarms: SystemErrors>0, Throttles, Latency p99 | `alerting.tf` | low | medium |
| P3.4 | Guardrail `InvocationsIntervened` alarm (security signal) | `alerting.tf` | low | medium |
| P3.5 | Composite "agent-unhealthy" rollup | `alerting.tf` | trivial | none |
| P3.6 | Anomaly-band alarms (Invocations, Latency) | `alerting.tf` | low | low cost |
| ~~P3.7~~ | ~~Application Signals SLO~~ — **DEFERRED** (see below) | — | high | wrong resource type |

**MANDATORY live read-back before P3.2–P3.4/P3.6 (medium-confidence):** the AgentCore activity-metric **namespace** is rendered three ways in AWS docs (`bedrock-agentcore` vs `AWS/BedrockAgentCore` vs `BedrockAgentCore`) and the activity-metric **dimension key** (`Resource`=ARN vs `Endpoint`/`AgentId`) is only documented for the resource-usage table. **Run `aws cloudwatch list-metrics --namespace bedrock-agentcore` (and variants) and pin the literal in ONE `local.agentcore_ns` before trusting any tile/alarm.** Also confirm whether `Latency` supports `extended_statistic` (p99) or only `Average` — if Average only, swap in P3.3. Guardrails namespace = `AWS/Bedrock/Guardrails`, `InvocationsIntervened` dimensioned by `GuardrailArn`+`GuardrailVersion` (verify ARN-vs-id value).

```hcl
locals { agentcore_ns = "bedrock-agentcore"   # PIN after list-metrics read-back
         agent_arn    = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn }
resource "aws_sns_topic" "alarms" { name = "${var.name_prefix}-agent-alarms"; kms_master_key_id = "alias/aws/sns" }
resource "aws_cloudwatch_metric_alarm" "system_errors" {
  alarm_name = "${var.name_prefix}-system-errors"; namespace = local.agentcore_ns
  metric_name = "SystemErrors"; dimensions = { Resource = local.agent_arn }
  statistic = "Sum"; period = 300; evaluation_periods = 1; threshold = 0
  comparison_operator = "GreaterThanThreshold"; treat_missing_data = "notBreaching"
  alarm_actions = [aws_sns_topic.alarms.arn]; ok_actions = [aws_sns_topic.alarms.arn]
}
# latency_p99 (extended_statistic="p99"), throttles, guardrail_intervened (count-gated on
# var.enable_guardrail), composite OR-rollup, anomaly bands — per the grounded snippets.
```

**P3.7 Application Signals SLO — DEFERRED (review HIGH severity).** `aws_applicationsignals_service_level_objective` **does not exist** in hashicorp/aws (issue [#39555](https://github.com/hashicorp/terraform-provider-aws/issues/39555) open). Only `awscc_applicationsignals_service_level_objective` exists (different CFN-cased schema), AgentCore is **not** auto-discovered by App Signals (would need a metric-based SLI), and account-level discovery must be enabled out-of-band. **The P3.3 latency-p99 alarm already covers the operational need** — do not build the SLO unless the team explicitly wants burn-rate semantics.

**Definition of Done (P3):** `list-metrics` read-back matches the pinned namespace/dims; a driven invoke produces a **non-zero datapoint via `get-metric-statistics`** (not just a visually-populated tile); a forced SystemError drives the static alarm AND the composite to **ALARM** with an SNS email, then back to OK.

---

### Phase 4 — Smaller gaps: trace sampling, deployment markers, KB ingestion

| id | change | target file | effort | risk |
|----|--------|-------------|--------|------|
| P4.1 | KB ingestion `APPLICATION_LOGS` delivery trio (clone Memory) | `observability.tf` | low | none |
| P4.2 | KB ingestion `FAILED` metric filter + alarm | `observability.tf` | low | medium (JSON path) |
| P4.3 | Transaction Search indexing % control (cost/PII dial) | `observability.tf` (:35 extend) | low | **low-conf CLI verb** |
| P4.4 | Deployment/version marker (dashboard text + annotation) | `alerting.tf` | trivial | medium |

P4.1 clones the Memory `APPLICATION_LOGS` trio against `aws_bedrockagent_knowledge_base.this.arn`. P4.2's metric-filter JSON path (`$.event.ingestion_job_status` vs top-level) **must be confirmed against one real emitted record.** P4.3 default to a **modest indexing %** (e.g. 10) for a PII workload — verify the exact CLI verb (`update-indexing-rule` vs a Transaction-Search-specific API) before wiring; **low confidence.** P4.4 dashboard marker is infra-only; the richer `service.version` span attribute is a **cross-repo agent-code follow-up**, not assumed done.

**Definition of Done (P4):** a `StartIngestionJob` lands status records in the KB vended group; a forced failing sync trips the FAILED alarm; `get-indexing-rules` shows the chosen %.

---

## 3. Validation protocol — single end-to-end runbook

Run **in order**, after each phase's apply. **Never accept "terraform apply succeeded" as proof — every step below asserts an observed signal, not a created resource.**

1. **One live invoke (the trigger):** `make status` (ROPC test user — the green end-to-end path from HANDOVER.md). All later queries key off this invoke's session.

2. **Console tabs (Phase 0):** Agent Runtime → Tracing = **Enabled**, Log delivery active; Gateway → Tracing = **Enabled**; Runtime/Gateway **Identity tabs now read Enabled with no extra resource** (proves P0.7 transitive claim). CLI cross-check: `aws logs describe-deliveries --region us-west-2` lists `runtime-traces`/`gateway-traces` (XRAY) + both APPLICATION_LOGS deliveries.

3. **Service spans actually land (strengthened — not "delivery exists"):** Logs Insights on `aws/spans`:
   `fields @timestamp, attributes.aws.local.operation | filter attributes.aws.local.operation = 'InvokeAgentRuntime' | sort @timestamp desc | limit 5` → assert **≥1 row** with `aws.resource.arn` = runtime ARN; repeat filtering the gateway ARN.

4. **Token spans (the linchpin §4 experiment):** *first with P0.3 alone* —
   `fields @timestamp, attributes.gen_ai.usage.total_tokens | filter ispresent(attributes.gen_ai.usage.total_tokens) | sort @timestamp desc | limit 5`. If **empty**, apply P0.6 (`AGENT_OBSERVABILITY_ENABLED`), redeploy, re-invoke, re-query. The **delta** answers whether the env var is required.

5. **Token EMF (Phase 1, delivery-independent):** Logs Insights on the runtime APPLICATION_LOGS group:
   `fields @timestamp, session_id, actor_id, InputTokens, OutputTokens, TotalTokens | filter ispresent(TotalTokens) | stats sum(TotalTokens) as total by session_id` → assert **non-zero `total`** for this session (proves the P1.1 fallback fired even though strands shape is unverified). Then `get-metric-statistics` on `OrderTriage/Agent`/`TotalTokens` → assert a datapoint.

6. **USAGE_LOGS (Phase 0, ~lag up to 60min):** Logs Insights on the USAGE_LOGS group → `agent.runtime.vcpu.hours.used` / `agent.runtime.memory.gb_hours.used` rows present.

7. **Masked-PII record (Phase 2 — both directions):** seed an invoke whose payload contains a confirmed-identifier value (test SSN `123-45-6789` / test email). As a principal **without `logs:Unmask`**: `aws logs filter-log-events --log-group-name /aws/bedrock/order-triage/modelinvocations` → value renders **masked**; **with `logs:Unmask`** → renders raw. Same record shows `input.inputTokenCount`/`output.outputTokenCount`. This single check proves token capture **and** that the mask floor held.

8. **Forced-error → ALARM (Phase 3):** invoke with a malformed payload / revoke a downstream perm → `describe-alarms --alarm-names order-triage-system-errors` shows `StateValue=ALARM`, the **composite** `order-triage-agent-unhealthy` also ALARM, an SNS email arrives; recover → both OK. For the guardrail alarm, send a prompt-injection string and confirm `InvocationsIntervened` increments.

9. **Structured errors (Phase 1):** bad JWT → `filter @message like /jwt_subject_decode_failed/` returns one row; forced webapp 4xx → server log shows one `agent_invocation_failed` with traceback and the browser detail is the generic string.

---

## 4. Open questions / spikes-within-the-plan (resolve cheaply BEFORE committing full TF)

1. **~~`AGENT_OBSERVABILITY_ENABLED` — required or auto-injected?~~ → RESOLVED (2026-06-23).** A live invoke after enabling P0.3 produced 37 gen_ai spans in `aws/spans` with `gen_ai.usage.*` token attributes **without** the env var set. **The hosted runtime auto-instruments; the env var is NOT required. P0.6 skipped.**

2. **~~`USAGE_LOGS` provider validator~~ → RESOLVED (2026-06-23).** `terraform validate` *and* `make plan` against hashicorp/aws (lockfile-pinned) accepted `log_type = "USAGE_LOGS"`; the source was created on apply (`describe-delivery-sources` shows it). **No local-exec fallback needed.**

3. **Strands terminal-event shape (medium-conf).** The `{"result": AgentResult}` / `accumulated_usage` TypedDict citations are external (strands not installed in-tree). **Experiment:** `pip show strands-agents` against the *deployed* version in a scratch venv and inspect `strands/types/_events.py` + `strands/telemetry/tracer.py`; OR just rely on the P1.1 `agent.event_loop_metrics.accumulated_usage` fallback (shape-independent) and let step 5 prove a non-zero datapoint lands.

4. **AgentCore metric namespace + dimension literal (medium-conf).** `aws cloudwatch list-metrics --namespace bedrock-agentcore` (+ variants) — pin `local.agentcore_ns` and the dimension key before P3.2–P3.6. Also confirm `Latency` percentile support.

5. **~~Managed-identifier ARNs~~ → RESOLVED (2026-06-23).** Live throwaway-log-group probe: `put-data-protection-policy` **accepted all 5** (EmailAddress, PhoneNumber-US, Ssn-US, DriversLicense-US, CreditCardNumber). `Name`/`Address` excluded. No failed-apply risk.

6. **~~Invocation-logging singleton pre-existing config~~ → RESOLVED (2026-06-23).** `get-model-invocation-logging-configuration` returned **empty** before apply — no console config to overwrite.

---

## 5. Risks & rollback

**PII egress (highest).** Phase 0 APPLICATION_LOGS (P0.1/P0.4) retain request/response payloads **unmasked** — the guardrail has only a PROMPT_ATTACK input filter, no PII policy (guardrail.tf). Phase 2 invocation logs carry full verbatim prompts/completions. **Mitigation:** the P2.2 mask floor (CWL-only), short retention, S3 left unset, and a future sensitive-info guardrail. **Rollback:** delete the delivery/logging-config resources — log groups stop receiving; purge groups for already-landed records. **The mask floor cannot be applied retroactively — this is why P2.2 strictly precedes P2.3.**

**Telemetry cost.** 100% trace indexing maximizes Transaction Search ingest *and* unmasked-PII span volume — P4.3 dials it to ~10%. Anomaly detectors bill ~$0.30/detector/mo (only 2). EMF stays cheap via the 2-dimension rule (P1.1) — **do not** add session_id/actor_id as dimensions. Unbounded retention is closed by P2.5/P2.6 (`var.*_retention_days`). **Rollback:** lower retention vars, drop anomaly alarms, set indexing % to 0.

**Per-phase clean rollback.** Phase 0/3/4 are pure additive TF — `terraform destroy -target` the new resources; vended metrics keep flowing, console toggles revert to "Not enabled". Phase 1 code is revertible by git (P1.1 result-branch is ordered first and only `continue`s, so reverting cannot corrupt the stream). Phase 2 is the only one with a **non-reversible side effect** (records written before P2.2) — hence the hard gate.

**Operational false-signals.** Wrong namespace → alarms sit in INSUFFICIENT_DATA and tiles render blank (visible, not silent) — the step-2/step-8 read-backs catch this. `treat_missing_data=notBreaching` prevents idle-demo flapping.

---

## 6. Effort & sequencing summary (first → last)

1. **Spike-first (hours, blocks TF):** §4 Q1 (`AGENT_OBSERVABILITY_ENABLED`), Q2 (USAGE_LOGS enum), Q4 (`list-metrics` namespace), Q5 (identifier ARNs), Q6 (singleton check). Cheap CLI/plan probes — do these before writing the bulk TF.
2. **Phase 0** — Runtime+Gateway delivery trios (P0.1–P0.5), then gate-decide P0.6. **low effort, high value** (flips the dormant surface). Validate via runbook steps 2–4, 6.
3. **Phase 1** — code: P1.1 token capture (with fallback) + P1.3/P1.4 structured errors (**trivial, no deps**); P1.2 requestMetadata (inert until Phase 2). Validate steps 5, 9.
4. **Phase 2** — **P2.1 → P2.2 (mask) → P2.3 (logging on), in that strict order**; plus P2.5/P2.6 retention, P2.7 tags. **medium effort, the PII gate lives here.** Validate step 7.
5. **Phase 3** — SNS → dashboard → static alarms → guardrail → composite → anomaly. **DEFER P3.7 SLO.** Validate step 8.
6. **Phase 4** — KB ingestion logging+alarm, sampling %, deploy marker. **lowest priority.**

> **Dollarization is out of scope** — once Phase 1 (token EMF + requestMetadata) and Phase 2 (invocation logs) land the counts durably, hand off to **[FINOPS-SPIKE.md](../research/finops-spike.md)** for the price-map / CUR / cost-EMF derivation. This plan deliberately stops at *counts captured, PII-safe, observable*.

---
*Provenance: a 6-agent workflow (4 parallel grounding agents over delivery-toggles / gen_ai-spans+code / invocation-logging+PII / monitoring-layer → 1 adversarial reviewer → 1 synthesizer), with every snippet re-verified against the in-tree files on 2026-06-23. The reviewer caught and corrected: a non-existent `aws_applicationsignals_service_level_objective` resource (→ deferred), unverified `Name`/`Address` PII identifiers that would reject the mask policy (→ removed), the >100KB unmasked-S3 overflow path (→ S3 left unset), and an unverified Strands terminal-event shape (→ `event_loop_metrics` fallback). Consistent with OBSERVABILITY-SPIKE.md and FINOPS-SPIKE.md.*

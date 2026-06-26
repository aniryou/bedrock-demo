# SPIKE REPORT — Unified Token + Cost Visibility for `order-triage-agent`

**Scope:** Bedrock AgentCore Runtime (`order_triage-cwG2Pw7Bnv`) + AgentCore Gateway (Cedar/OBO) + Strands agent + Bedrock Knowledge Base + AgentCore Memory + Snowflake/SAP downstream.
**Audience:** repo owner + admin/ops.
**Deployed model (load-bearing — verified, not assumed):** `amazon.nova-lite-v1:0`. `runtime.tf:41` sets `BEDROCK_MODEL_ID = var.bedrock_model_id`; the `variables.tf:14` default is `amazon.nova-lite-v1:0`; there is **no tfvars override**, and HANDOVER.md confirms it three times. The Python `config.py:37` default (`anthropic.claude-opus-4-8`) is **overridden at deploy by the env var and is NOT what runs** — every economics claim below is derived against Nova Lite, a **first-party Amazon foundation model billed natively under AWS Bedrock**.

**Bottom line up front:** Today there is **zero end-to-end cost visibility**. Bedrock returns token usage on every Converse call, Strands accumulates it in `EventLoopMetrics`, and `aws-opentelemetry-distro` is installed — but `runtime.py` discards the usage metadata event (`stream_steps.py` only forwards `__step__` tool/reason events), no OTLP exporter is configured, and `bedrock:PutModelInvocationLoggingConfiguration` is not set. The fastest credible fix is **two server-side toggles (zero agent code) + one small agent change** to inject `requestMetadata`, which unlocks all five levels of the token portion.

A structural fact that governs every recommendation: **AWS billing alone stops at account → service → resource/IAM-principal → tag.** The agent invokes Bedrock under **one shared AgentCore runtime execution role**, so CUR/Cost Explorer collapse every Entra user into that single principal. **The lower three levels (actor, session, message) are NOT derivable from billing — they MUST be self-instrumented** (via `requestMetadata`, EMF/OTEL, or an observability tool).

A second governing fact, specific to this deployment: Nova Lite is roughly two orders of magnitude cheaper per token than a premium tier. So unlike a typical Opus/GPT-4-class agent, **model token spend is very likely NOT the dominant cost driver on this stack.** The likely heavier line items are the **consumption meters that carry stock/flow costs regardless of token price**: AgentCore Memory's 3-strategy store (monthly record stock + a SUMMARIZATION model call per turn), Knowledge Base retrieval + S3-Vectors index growth, and Snowflake warehouse credits. The plan still leads with model-token capture because it is the cheapest, highest-coverage instrumentation seam — but it does **not** assert tokens dominate; that must be confirmed from the meters once Phase 0 lights them up.

---

## Q1 — Unified token + cost view at five levels

### The identifiers that already exist in this codebase

| Level | Attribution key | Where it lives today | Cardinality |
|---|---|---|---|
| Overall | AWS account + service | AWS billing (native) | trivial |
| Agent | `agent_id = "order-triage"` (`agent.py:38`), deployed `model_id = amazon.nova-lite-v1:0` (env `BEDROCK_MODEL_ID`, `runtime.tf:41` ← `variables.tf:14`), runtime ARN `order_triage-cwG2Pw7Bnv` | fixed per deployment | trivial (1) |
| Actor | Entra JWT **`sub`** claim — currently only `raw_jwt` stored in `identity.py` contextvar (set at `runtime.py:54`), **never decoded** | in `contextvars` for the whole turn; forwarded to Gateway for authz only | medium (bounded user base) |
| Session | `session_id` — `context.session_id` (`runtime.py:52`) / webapp `webapp-`+`token_hex(20)` (`main.py:124`) sent via `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` (`agentcore.py:97`) | passed to `build_agent(session_id=...)` and `AgentCoreMemorySessionManager` (`memory.py`) | high |
| Message/turn | **none exists** — each `invoke()` (`runtime.py:41`) is one turn; Strands `toolUseId` is per-turn-local, not unique; X-Ray trace/span IDs exist at the container level but are not surfaced to Python | must be minted | very high |

**Critical caveat, confirmed in code:** `memory.py:14` declares `build_session_manager(session_id, actor_id="order-triage")` — `actor_id` is a **hardcoded default parameter**, and neither `build_agent()` (`agent.py:36-57`) nor `runtime.py` ever passes an override. So memory-side actor attribution is **structurally blocked** until that signature is changed and the decoded `sub` is threaded through `build_agent` → `build_session_manager`.

### The token source that is being thrown away

Bedrock `converse_stream` (the streaming path actually used — `bedrock.py:971`) returns a `usage` block: `inputTokens`, `outputTokens`, `totalTokens`, and (if caching is on) `cacheReadInputTokens`/`cacheWriteInputTokens`. Strands captures it at **`bedrock.py:1135`** (`metadata['metadata']['usage'] = response['usage']`, guarded at `:1132`) and accumulates it in `EventLoopMetrics.accumulated_usage`, exposed on `AgentResult.metrics`. But `runtime.py:67-75` only yields `event["data"]` text and `step_events(event)` output — the metadata/usage event is **dropped**.

### Level → identifier → emit → store → tool

| Level | Keyed by (real field) | Emit mechanism | Lands in | Tool to read it | Cardinality note |
|---|---|---|---|---|---|
| **Overall** | account + Service (`Bedrock`, `Bedrock AgentCore`, `Lambda`, KB/S3-Vectors) | **None — native today** | CUR 2.0 / Cost Explorer (billing-grade $) | Cost Explorer, Budgets | trivial |
| **Agent** | `agent_id`/runtime ARN; AgentCore vended `CPUUsed-vCPUHours`, `MemoryUsed-GBHours` (dim `Resource=Agent Arn`) | already vended to `AWS/Bedrock-AgentCore`; cost via tags on runtime resource | CloudWatch **metric** + CUR (tagged) | CloudWatch GenAI Observability, Cost Explorer | trivial (1 runtime) |
| **Actor** | decoded JWT **`sub`** | self-instrument: decode `sub` → Bedrock `requestMetadata.actor` / EMF dim / OTEL `session.user.id` | model-invocation **log** / EMF metric (small user set) / OTEL backend | Logs Insights / Athena / OTEL backend | medium — metric dim only for small known user base; else log field |
| **Session** | `session_id` (`runtime.py:52`) | self-instrument: `requestMetadata.session` / EMF log field / OTEL `session.id` | model-invocation **log** / EMF **log field** / OTEL span | Logs Insights `stats … by session` / Athena | **high → log field only**, never a metric dimension |
| **Message** | minted `request_id` (uuid4 at `invoke()` entry) + X-Ray trace/span id | self-instrument: mint id → `requestMetadata.turn` / EMF log field — the **group-by key** that collapses the N per-cycle Converse records into one turn | model-invocation **log** (N records/turn) / EMF **log field** | Logs Insights / Athena | **very high → log field only** |
| **Unit-econ** | per-triage = Σ(model $ keyed by session) + KB-retrieve + Memory (incl. summarization) + Snowflake credits | join token-log $ to per-tool emits + Memory/KB meters + Snowflake usage views | warehouse (S3+Athena / Snowflake) | Athena / QuickSight | derived |

**Per-CALL vs per-MESSAGE — the grouping you must not skip:** one agent **turn** (one `invoke()`) runs **multiple Converse calls** — one per reasoning cycle (tool-call → model again). Model-invocation logging emits **one record per Converse CALL**, so a turn maps to **N log records, not one**. Per-**message** attribution is NOT free from the log alone; it requires the minted `request_id` carried as `requestMetadata.turn` to `GROUP BY` those N records. The log's native `requestId` is the per-**call** join key; `requestMetadata.turn` is the per-**message** rollup key.

**The non-negotiable cardinality rule:** `overall`/`agent`/(small) `actor` are **low-cardinality → safe as CloudWatch/EMF metric dimensions** (cheap, alarmable). `session_id`, `request_id`, X-Ray ids (and `email`/large actor sets) are **high-cardinality → keep them as LOG FIELDS** and roll up at query time. Putting `session_id`/`request_id` in an EMF dimensions block silently spawns a metric stream per unique value and explodes the CloudWatch custom-metric bill.

**Why billing can't do the bottom three:** CUR 2.0 aggregates Bedrock per usage-type, per operation, per IAM principal, per hour — never per request. Its `line_item_iam_principal` records the **shared runtime role**, not the Entra user. So "what did one triage cost / which user drove it" is structurally impossible from billing and must come from in-app capture.

---

## Q2 — What else to consider for FinOps (beyond tokens)

**1. AgentCore service meters (billed separately from model tokens), all consumption-based — likely the heavier line items here given Nova Lite's low token price:**
- **Runtime:** $0.0895/vCPU-hr + $0.00945/GB-hr (active processing only). Already vended as `CPUUsed-vCPUHours`/`MemoryUsed-GBHours`; enable **USAGE_LOGS** (1-sec, per-session) for per-session vCPU/GB-hours — currently NOT enabled.
- **Gateway:** $0.005/1k API invocations, $0.025/1k Search, $0.02/100 tools/mo. Gateway `Call Tool` spans carry `tool.name` + `TargetExecutionTime` → isolates which of `snowflake___`/`sap___`/`orders___` dominates.
- **Memory:** $0.25/1k short-term events, $0.75/1k long-term records/mo, $0.50/1k retrievals. The 3-strategy store (SEMANTIC/SUMMARIZATION/USER_PREFERENCE, `memory.tf`; 90-day retention) carries a **monthly stock cost** per-session metrics won't surface.
- **Identity:** OBO `TOKEN_EXCHANGE` here runs **through** Gateway/Runtime → **$0** per pricing rule. No separate identity meter.

**1a. The Memory SUMMARIZATION model call is a hidden per-turn token cost your session rollup will MISS.** The `SUMMARIZATION` strategy (`memory.tf:17-21`) runs a Bedrock model invocation on **every persisted turn**. That InvokeModel happens **inside the AgentCore Memory service, under the Memory service principal — not in the agent's own `converse_stream` call** — so it does **not** appear in the per-session token rollup and is **not** tagged with your `requestMetadata`. It WILL appear in account-level model-invocation logging (different principal) and in the Memory meter. Treat it as a **meter-attributed** cost.

**2. Downstream costs (mostly invisible today):**
- **Snowflake warehouse credits** — every triage triggers ~2-5 queries; the `orders___flagOrder` path incurs a **hidden dependent Snowflake call** (order-actions Lambda re-queries status, `order_actions_stub/app.py:24-38`). Not in AWS billing at all — needs Snowflake's own usage views. The X-API-Key bypass (`snowflake_stub/app.py:46-61`) and missing `STATEMENT_TIMEOUT` (`setup.sql:79-84`) are **uncontrolled-spend vectors**.
- **Bedrock Knowledge Base** — `search_policies` → `_kb_retrieve` → `retrieve()` (`knowledge.py:14,19,22`, default **k=3**) runs **once per `search_policies` call**, possibly multiple times per triage. Cost = an **embedding-model invocation** (`amazon.titan-embed-text-v2:0`, `variables.tf:34`) + an S3-Vectors query + index storage growth. Nuance: the **embedding InvokeModel IS a Bedrock call**, so model-invocation logging (Tier 0) **captures its token count** — only the S3-Vectors query/storage stays off the model log. KB is **partially** visible once Tier 0 is on.
- **SAP stub** is in-memory → zero cost today (will change in prod).

**3. Prompt caching — verify before assuming savings (model-dependent):** `SYSTEM_PROMPT` (`agent.py:23-33`) is a large static block, ideal cache candidate; `BedrockModel(...)` (`agent.py:48-52`) passes no `cache_config`. Strands cache plumbing is real (`cachePoint`, `bedrock.py`). **But Nova Lite's prompt-caching behavior ≠ a Claude tier's** — HANDOVER.md notes Nova Lite ignores some prompt instructions. **Action: empirically test** whether Nova Lite emits cache usage tokens before claiming a saving. Even if it does, the absolute saving is small (Nova input tokens are already cheap) — it's a **latency/marginal-cost** win here, not a headline lever.

**4. Model selection / routing — already on the cheap tier:** the deployed model is **Nova Lite**, already the cheapest practical tier (on-demand, no model-access form). There is **no "route off premium" saving to capture**. The realistic lever is the inverse: if triage **quality** ever needs a stronger model, that is a **cost increase to plan for** — and switching to an Anthropic tier is **not a pure config change** (`variables.tf:15` documents a Bedrock use-case/model-access form + inference-profile id, e.g. `us.anthropic.claude-sonnet-4-6`). Keep the model behind an **Application Inference Profile** ARN so the *mechanics* of a swap stay config-only even though the *access* step is a prerequisite.

**5. Budgets & anomaly alerts (none exist):** add `aws_budgets_budget` filtered to `Service=Bedrock`/`Bedrock AgentCore` with forecast alerts, and `aws_ce_anomaly_detector`. Nova Lite is **first-party native Bedrock spend**, so Cost Anomaly Detection **does** see it (the "can't see Anthropic Claude Marketplace spend" caveat is only a *future* gotcha if you switch to a Marketplace-subscribed tier). Higher-value anomaly targets here are the **Memory/Gateway meters, Lambda, and KB/S3-Vectors**, not model tokens.

**6. Guardrails against runaway loops/cost — and what already exists:** `max_tokens=2048` **already caps OUTPUT tokens per Converse call** (`config.py:39`, `agent.py:51`) — a real existing ceiling, not a gap. Missing is a **per-turn cycle/iteration ceiling** (the actual runaway-loop lever): Strands exposes a **max-iterations knob on the event loop** — set it rather than building "max turns" from scratch. Also: no Bedrock Guardrail attached (`runtime.tf:19-32`); no retry/circuit-breaker on outbound calls (`data.py:66-71`). With Nova Lite the *token* blast radius of a loop is cheap, but the **Gateway invocation meter, Snowflake re-queries, and Memory writes** per extra cycle are not — the cycle cap protects the *meters*.

**7. Unit economics:** cost-per-triage = model $ (small for Nova Lite) + KB-retrieve $ (embedding + S3-Vectors) + Memory event/record/retrieval $ (incl. per-turn summarization) + Snowflake credits. Map to FinOps-Foundation "cost per unit of work." Cost-per-**resolved**-case needs an outcome signal (was an order actually flagged via `orders___flagOrder`?) — observable in `stream_steps.py` tool_result. **On this stack the per-triage line is likely dominated by meters/Snowflake, not tokens** — assemble the full join before declaring a driver.

**8. Showback/chargeback per tenant/team:** the natural tenant key is the **Entra tenant** in `sub`. Provision **one AIP per tenant/team** (low cardinality — fine); AWS warns against **per-user** AIPs (proliferation, ~1000/account/region ceiling).

**9. Tagging discipline:** the stack has only `Project` + `ManagedBy` (`versions.tf`). Add `cost_center`, `team`, `env`, `application` to the runtime, gateway, memory, KB, and the 3 Lambdas; **activate** the tag keys in Billing (≤24h lag, not retroactive). For Bedrock token $, tags only attach via an **AIP ARN** — a bare model ID yields an untagged lump.

**10. Telemetry's own retention cost — and the NEW sinks this plan adds:** **no CloudWatch log-group retention is set anywhere** (`observability.tf`) → logs never expire → unbounded storage. The plan *adds* two sinks to budget:
- **Model-invocation-logging S3 bucket:** one gzipped JSON record **per Converse call** ≈ N per triage (N = reasoning cycles, ~2-6) + one per KB embedding retrieve + one per Memory summarization. Size as `(turns/day × ~5-10 records × ~2-5 KB)`; set an **S3 lifecycle** (Glacier@30d, expire@90-365d).
- **USAGE_LOGS:** 1-second, **per-session** → highest volume; route to a log group with **explicit retention** (14-30d).
- **EMF custom metrics (Phase 2):** charged **per unique metric stream**. Keep `agent`/`model` as the **only** EMF dimensions; `session`/`turn`/`actor` stay **log fields**.

**11. Token→cost conversion accuracy — keyed to the RIGHT model:** Bedrock returns **tokens, not dollars** everywhere except CUR. Any in-app `computed_cost_usd` is an **estimate** off a hand-maintained price map. Treat in-app $ as **showback/anomaly**; treat CUR as invoice-grade. **Maintain the price map for `amazon.nova-lite-v1:0` and `amazon.titan-embed-text-v2:0`** — NOT `anthropic.claude-opus-4-8` (the un-deployed Python default). Add a Claude id only if a tenant/team AIP later points at one.

---

## Q3 — A single governance pane: feasible? + tiered recommendation

**Is one pane possible with the current stack?** Yes for **overall/agent/session** and **AgentCore-meter unit economics** — but **no single tool covers everything**, because the cost drivers span three billing universes: (a) Bedrock model + embedding tokens, (b) AgentCore service meters (Runtime/Gateway/Memory), (c) Snowflake credits (not AWS billing at all). Any "single pane" is one that **joins** these; it does not eliminate the need to emit actor/session/message dimensions or feed Snowflake usage in separately. Given Nova Lite's low token price, the pane's value is mostly in the meters and Snowflake join, not the token line.

### Tier 0 — Pure AWS-native, fastest path (zero/near-zero agent code)
- **Enable `bedrock:PutModelInvocationLoggingConfiguration` → S3** (Terraform `aws_bedrock_model_invocation_logging_configuration`). One record per Converse **call**: `requestId`, `modelId`, `identity.arn`, token counts, optional `requestMetadata`. Gives **overall + agent + per-CALL token** with **no Python change**. Also captures the **KB embedding** and **Memory summarization** InvokeModels (different principals). Per-MESSAGE needs Phase-1 `requestMetadata.turn`.
- **Set runtime `Tracing=Enable` in `runtime.tf`** — verified **no `Tracing` attribute exists today** (`observability.tf:39` only routes segments via `update-trace-segment-destination`; it does not turn on emission). Until set, the `InvokeAgentRuntime`/`CPUUsed`/`MemoryUsed` spans the session view depends on are **not actually emitted**. With it on → per-agent/session vCPU/GB-hours in **CloudWatch GenAI Observability**.
- **Enable USAGE_LOGS** → per-session vCPU/GB-hours (set log-group retention).
- **CUR 2.0 + cost-allocation tags + `aws_budgets_budget` + `aws_ce_anomaly_detector`**.
- **Application Inference Profile** per workload/tenant → tag-level Bedrock $ in Cost Explorer.

**Gives:** levels overall/agent/session + per-**call** token; partial unit-econ. **Misses:** per-actor (shared role), per-message (needs turn-grouping), dollar-on-dashboard, Snowflake.

### Tier 1 — AWS-native + light DIY (the missing lower levels) ⭐ RECOMMENDED
Add the **`requestMetadata` injection** (smallest Converse-side change, below) so the model-invocation log carries `actor`(=`sub`), `session`, `turn`. Then per-actor/session/message rollups are a Logs Insights query:
```
fields requestMetadata.actor as actor, requestMetadata.session as session,
       requestMetadata.turn as turn,
       input.inputTokenCount as inTok, output.outputTokenCount as outTok
| stats sum(inTok), sum(outTok), count() as converse_calls by actor, session, turn
```
Optionally emit a **parallel EMF/OTEL event per tool call** (you already see `tool_call`/`tool_result` in `stream_steps.py`) to attribute KB-retrieve and Snowflake calls. Keep `agent`+`model` as EMF **metric dimensions**; keep `session`/`turn`/`actor` as **log fields**.

**Two scope honesty notes:**
- **`requestMetadata` log persistence is request-side-verified only.** `additional_args` is spread at the Converse request top level (`bedrock.py:337` — correct slot); `additional_request_fields` maps to `additionalModelRequestFields` (`:369` — wrong slot). **Not** independently verified: that the model-invocation **log** persists `requestMetadata` for the **streaming** `converse_stream` path. **Validate with one live invocation** before relying on it.
- **Per-actor MEMORY attribution is OUT of the small Converse-side change.** Tagging the model log does not tag Memory. To attribute Memory per actor you must also change `build_session_manager(session_id, actor_id=...)` (`memory.py:14`) to accept the real `sub` and thread it through `build_agent` (`agent.py:36-57`). Budget as a **separate, slightly larger edit**.

### Tier 2 — Add a third-party pane (defer)
- **Vantage** (best third-party dollar-join if any): its "LLM Token Allocation" reads the **same S3 model-invocation logs** and joins per-request tokens onto CUR. **Validate, don't assume:** (1) it inherits per-call-not-per-turn — confirm it can group by `requestMetadata.turn`; (2) whether it parses Bedrock `requestMetadata` for actor/session keying.
- **Langfuse / Phoenix** (trace-level LLM cost): real OTLP backends — set `OTEL_EXPORTER_OTLP_ENDPOINT/HEADERS` in `runtime.tf`, dual-export alongside X-Ray; the agent already emits spans. Add custom price rows for `amazon.nova-lite-v1:0` and `amazon.titan-embed-text-v2:0`.
- **LiteLLM proxy — reject for THIS stack on architectural grounds.** Managed AgentCore Runtime: the model call is **internal to the container** (`agent.py` → `BedrockModel` → `converse_stream` directly, `bedrock.py:971/986`). No interceptable hop for a transparent proxy; using it means rewriting the agent to repoint `BedrockModel` + relocating creds/IAM + a Postgres/Redis service — and it would still see **only the LLM hop** (blind to Gateway/Snowflake/KB/Memory, the dominant costs). Only worth it for hard **pre-request budget enforcement**.
- **Datadog/Dynatrace/New Relic** only if the org is **already** on that APM. Adds recurring SaaS cost and **egress PII** (prompts/completions, no Guardrail attached) unless scrubbed. Datadog truncates high-cardinality tags on cost metrics, weakening per-actor/per-message rollups.

### ⭐ Recommended default for THIS team: Tier 1 (AWS-native + `requestMetadata`), with Vantage as an optional read-only pane later.
Small AWS-centric team, one agent, cheap Nova Lite tier, existing CloudWatch/X-Ray path. Tier 1 closes the exact audit gap (`PutModelInvocationLoggingConfig` MISSING), keeps all data **in-account** (no PII egress — important given no Guardrail), costs ~$0 in software, and delivers **all 5 levels for the token portion** plus the per-tool emits needed to reach the **meters and Snowflake** that actually dominate. Vantage layers a zoom-out dollar-join later **without further code** (reads the same S3 logs) — defer until a second agent or real tenants exist. Skip LiteLLM/APM until there's a concrete need for inline budget enforcement or you already pay for the APM.

---

## Phased implementation plan for the spike

**Phase 0 — Server-side toggles (no agent code, ~half a day):**
1. Terraform `aws_bedrock_model_invocation_logging_configuration` → S3 (Gzip JSON) + optional CloudWatch; set **bucket lifecycle** + **log-group retention** (fixes unbounded retention; sizes the new sink).
2. `runtime.tf`: **add `Tracing=Enable`** (absent today) + enable **USAGE_LOGS** with explicit retention; keep the existing Transaction Search routing in `observability.tf`.
3. Activate cost-allocation tags; add `aws_budgets_budget` (Service=Bedrock + Bedrock AgentCore, forecast alert) and `aws_ce_anomaly_detector`.
→ Yields **overall + agent + session + per-CALL token** immediately, plus session vCPU/GB-hours.

**Phase 1 — The smallest agent change that captures actor/session/message (the PoC core):**
- **`identity.py`** — add a decoded `sub` to `UserIdentity` (PyJWT `decode(..., options={"verify_signature": False})` — the AgentCore CUSTOM_JWT authorizer already verified it; do **not** put raw JWT/email/PII in metadata — 256-char cap + PII rules).
- **`runtime.py:54`** — mint `request_id = uuid4()` at `invoke()` entry; you already have `session_id` (`:52`) and the JWT (`:54`).
- **`agent.py:48-52`** — thread the dimensions in:
  ```python
  BedrockModel(
      model_id=cfg.bedrock_model_id,   # = amazon.nova-lite-v1:0 at deploy
      region_name=cfg.aws_region,
      max_tokens=cfg.max_tokens,       # existing 2048 OUTPUT cap (config.py:39)
      additional_args={"requestMetadata": {
          "agent": "order-triage", "actor": sub,
          "session": session_id, "turn": request_id, "env": "prod"}},
  )
  ```
  **Load-bearing:** use `additional_args` (Strands spreads it at the Converse top level, `bedrock.py:337`), **NOT** `additional_request_fields` (maps to `additionalModelRequestFields`, `:369` — wrong slot). `build_agent()` runs per-`invoke()`, so tags are correct per turn. **Then validate** (one live call) that `requestMetadata.{actor,session,turn}` persists in the S3 log on the streaming path.
- **(Separate, larger edit — for per-actor MEMORY attribution)** change `build_session_manager(session_id, actor_id=...)` (`memory.py:14`) to take the real `sub`, and thread `sub` through `build_agent` (`agent.py:36-57`).
→ Yields **actor + message** in the log; join all 5 via the Logs Insights query, grouping by `turn`.

**Phase 2 — Make unit economics whole + enable savings:**
4. **Empirically test prompt caching on Nova Lite** (add `cachePoint` on the static `SYSTEM_PROMPT`; confirm cache tokens appear). Skip if none.
5. Set a **Strands max-iterations / cycle-limit** on the event loop (real runaway-loop lever; protects Gateway/Memory/Snowflake meters per cycle).
6. Emit a **parallel EMF/OTEL event per tool call** in the `runtime.py` stream loop, tagging KB-retrieve and `snowflake___`/`orders___` calls with the same `session`/`turn` (as log fields) — captures the hidden `orders___flagOrder`→Snowflake dependent call.
7. Pull **Snowflake usage views** and **AgentCore Memory/KB meters** into the same warehouse (S3+Athena) keyed by session; assemble **cost-per-triage** and **cost-per-resolved-case** (resolved = `orders___flagOrder` succeeded). Account for Memory summarization as meter-attributed. **Verify whether tokens or meters dominate.**
8. Create an **Application Inference Profile**, tag it, set `BEDROCK_MODEL_ID` to its ARN → tag-level Bedrock $ + a clean model-routing seam.

**Smallest PoC that yields all 5 levels (token portion):** Phase 0 (toggles) + Phase 1 (the `requestMetadata` injection in `identity.py`/`runtime.py`/`agent.py`, with the one-call log-persistence validation). Produces overall/agent/actor/session/message **token** rollups from a single S3 log stream queryable in Athena — grouping per-cycle Converse records by `turn` — with no proxy, no SaaS, no PII egress. Phase 2 converts counts into a full per-triage **dollar** unit cost dominated (on Nova Lite) by **meters + Snowflake**.

---

### Key files cited
- `../../terraform/runtime.tf` (`:41` `BEDROCK_MODEL_ID = var.bedrock_model_id`; **add `Tracing=Enable`** + OTEL/AIP env)
- `../../terraform/variables.tf` (`:14` model default `amazon.nova-lite-v1:0`; `:34` embedding `amazon.titan-embed-text-v2:0`; `:15` Anthropic needs model-access form + inference-profile id)
- `../../../agent/src/order_triage/runtime.py` (`:50-54` session/JWT; `:67-75` usage discarded)
- `../../../agent/src/order_triage/agent.py` (`:23-33` cacheable system prompt; `:48-52` BedrockModel — `requestMetadata` injection site; `:36-57` `build_agent` — thread `sub`)
- `../../../agent/src/order_triage/identity.py` (`raw_jwt` only — decode `sub` here)
- `../../../agent/src/order_triage/stream_steps.py` (filters to `__step__` — usage dropped; tool_call/tool_result observable for per-tool emits + resolved-case signal)
- `../../../agent/src/order_triage/memory.py` (`:14` `actor_id="order-triage"` hardcoded default — blocks actor-level memory attribution)
- `../../../agent/src/order_triage/tools/knowledge.py` (`:14,19,22` KB `retrieve()` k=3 per call — embedding InvokeModel log-captured; S3-Vectors query not)
- `../../terraform/memory.tf` (`:17-21` SUMMARIZATION strategy — per-turn model call under Memory principal, off the session token rollup)
- `../../terraform/observability.tf` (no log retention; `:39` segment routing only — emission needs `Tracing=Enable`), `versions.tf` (only `Project`+`ManagedBy` tags) — add `aws_bedrock_model_invocation_logging_configuration`, `aws_budgets_budget`, `aws_ce_anomaly_detector`.
- Strands internals: `bedrock.py:1135` (usage capture), `:337` (`additional_args` → top level), `:369` (`additional_request_fields` → `additionalModelRequestFields`), `:971` (`converse_stream`).

---
*Generated 2026-06-22 via multi-agent spike workflow (6 stack readers + 10 tooling tracks + adversarial critique). The critique caught and corrected a model-identity error (draft assumed Opus 4.8 from the Python default; live deploy is Nova Lite) — all economics above are re-grounded against `amazon.nova-lite-v1:0`.*

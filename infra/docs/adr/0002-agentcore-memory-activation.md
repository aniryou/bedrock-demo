# ADR-0002: Activate AgentCore long-term memory (per-user) + memory observability

**Status:** Accepted — implemented & deployed 2026-06-22 (deploy run 27964171047). Live-invoke validation (retrieval firing) pending.
**Date:** 2026-06-22
**Deciders:** Anil Choudhary (proposer); platform + security owners
**Related:** [ADR-0001](0001-user-impersonation-obo.md) (the CUSTOM_JWT inbound this builds on); memory spike + `agentcore-memory-retrieval-off`, `cloudwatch-genai-observability`.

## Context

The stack deploys an `aws_bedrockagentcore_memory` resource with **all three long-term strategies** — SEMANTIC (`/facts/{actorId}`), SUMMARIZATION (`/summaries/{actorId}/{sessionId}`), USER_PREFERENCE (`/preferences/{actorId}`) — see `terraform/memory.tf`. The Strands agent consumes memory through `AgentCoreMemorySessionManager` (`../../../lib/src/agent_kit/infra/memory.py`). A spike found three gaps:

1. **Long-term memory is write-only.** `AgentCoreMemoryConfig.retrieval_config` defaults to `None`. The session manager's `retrieve_customer_context()` early-returns when it's unset (`if not self.config.retrieval_config: return None`), so it never issues `RetrieveMemoryRecords` and never injects anything. CreateEvent runs every turn → the async pipeline populates the namespaces → **nothing is ever read back**. In-session continuity still works (the session manager replays short-term events), but cross-session personalization — the entire reason the three strategies exist — is dead weight.

2. **One shared profile.** `actor_id` is hard-coded to the literal `"order-triage"`. Because `/facts` and `/preferences` are keyed on `{actorId}`, **every user shares one fact/preference namespace** — "preferences" become cross-user mush. This is the open `actor_id` decision carried in `../research/handover-2026-06-23.md`.

3. **No memory observability.** Account-level CloudWatch Transaction Search is enabled (`terraform/observability.tf`), but per-memory **tracing and log delivery are not** (AWS does not configure memory log/trace destinations automatically), and there is no app-side signal for whether retrieval actually fires or injects anything per turn.

These compound: even after (1), memory is only *useful* with (2), and only *verifiable* with (3).

## Decision

Three coupled changes. The retrieval mechanics stay in the Strands SDK (we do not hand-roll `RetrieveMemoryRecords`); we supply configuration and identity and observe the result.

**D1 — Activate long-term retrieval.** Set `retrieval_config` on `AgentCoreMemoryConfig`, keyed by the **templated** namespaces from `memory.tf` (the SDK calls `namespace.format(actorId=…, sessionId=…)` at retrieval time, so the keys must carry the `{actorId}`/`{sessionId}` placeholders verbatim):

| Namespace (key) | Strategy | `top_k` | `relevance_score` |
|---|---|---|---|
| `/facts/{actorId}` | SEMANTIC | 5 | 0.3 |
| `/preferences/{actorId}` | USER_PREFERENCE | 5 | 0.3 |
| `/summaries/{actorId}/{sessionId}` | SUMMARIZATION | 3 | 0.3 |

Retrieval then runs **once per user turn** (on `MessageAddedEvent`, when the last message is the user's); hits clearing the threshold are concatenated and **prepended to the latest user message** wrapped in `<user_context>…</user_context>` (the SDK `context_tag`) — note this is **message-level injection, not a system-prompt change**. The system prompt is given a short `<user_context>` instruction so the model treats the block as background (and explicitly **not** as flagging evidence); without it the injected context is easy to ignore, especially on Nova Lite. SDK defaults (`top_k=10`, `relevance_score=0.2`) are loosened from ours deliberately — 0.3 is a conservative starting floor to tune from real scores (see Observability).

**D2 — `actor_id` = Entra subject.** Derive the memory actor from the **verified inbound JWT's `sub` claim** (fall back to `oid`, then to the anonymous fallback — `actor_id(default=spec.agent_id)`, i.e. `"order-triage"` — when no user token is present). The CUSTOM_JWT authorizer has already cryptographically verified the token before the runtime sees it (per ADR-0001), so the runtime decodes the **payload only, without re-verifying the signature**, purely to read the subject. `sub` is an opaque, stable per-(user, app) identifier — it keeps **PII out of the namespace path** (no email/UPN) while giving each user their own `/facts` and `/preferences` partition. `build_session_manager` resolves the actor from the request `identity` contextvar (mirroring how `agent_kit.infra.gateway` pulls the bearer), so the anonymous-fallback default has a **single source** (the spec's `agent_id`, with `identity.ANONYMOUS_ACTOR` as the module-level constant) and nothing is threaded through `build_agent`.

**D3 — Memory observability.** (a) **Terraform**: enable per-memory **tracing** (a `TRACES` delivery source → `XRAY` destination) and **log delivery** (an `APPLICATION_LOGS` delivery source → a dedicated CloudWatch Logs group), via `aws_cloudwatch_log_delivery_source` / `_destination` / `_delivery` (XRAY destination type needs aws provider ≥ 6.21.0, so `versions.tf` is constrained `~> 6.21`; lockfile currently pins 6.50.0). Account-level Transaction Search already exists. (b) **Agent**: observability is **platform-provided, not hand-rolled**. The agent already runs under `opentelemetry-instrument` (ADOT auto-instruments Strands spans + the boto3 `RetrieveMemoryRecords` client call); with (a) enabled, AgentCore emits native memory spans (`RetrieveMemoryRecords`: `memory.id`, `namespace`, `error`/`throttled`/`fault`) and extraction/consolidation logs; and the SDK session manager already logs the retrieved-item count per turn. So the agent carries **no custom span code** — only `retrieval_config` (legitimate agent config). This matches AWS's own samples (the observability-with-strands example relies on ADOT auto-instrumentation; nothing in the samples subclasses the session manager to trace it) and avoids a fragile override of an SDK-internal method.

## Options considered

**Actor identity (D2).**

| Option | Assessment | Verdict |
|---|---|---|
| Keep `"order-triage"` | One shared profile; preferences mingle across users; fails the goal | Rejected |
| Entra `sub` (+ `oid` fallback) | Opaque, stable per-(user,app); no PII in namespace; honors "subject" | **Chosen** |
| Entra `oid` | Stable tenant-wide per user; also opaque. Marginally broader than needed for one app | Fallback only |
| `email`/`upn` | Human-readable but puts PII in the namespace path and is mutable | Rejected |

**Retrieval mechanism (D1).** Use the SDK session manager's built-in retrieval+injection (**chosen** — least code, matches how storage already works) vs. hand-rolling `RetrieveMemoryRecords` calls and prompt assembly (more control, but duplicates the SDK and the `<user_context>` convention). We chose the SDK path and kept all tuning in `retrieval_config`.

**Observability plumbing (D3).** TF-native delivery resources (**chosen** — drift detection, declarative; the `~> 6.21` provider constraint guarantees the XRAY destination type) vs. a `terraform_data` local-exec running the `put-delivery-*`/`create-delivery` CLI sequence (the idiom `observability.tf` uses for the account X-Ray routing; robust but imperative, no drift detection). Native won because the provider version clears the bar. For the per-turn signal we **rejected a custom app-side span** (an initial version subclassed the session manager to record an `injected` attribute): it duplicates the platform's native `RetrieveMemoryRecords` span + ADOT's boto3 span, the SDK already logs the injected-item count, and AWS's samples never instrument retrieval by hand — so a custom span is platform plumbing in the agent repo plus a fragile SDK-internal override, for marginal gain. If the injection-decision-as-span-attribute is ever wanted, prefer a Strands-native hook over subclassing.

## Consequences

**Becomes easier**
- Cross-session personalization actually functions: a user's prior facts/preferences and past-session summaries surface on their next session.
- Per-user accountability and isolation at the memory layer, consistent with the per-user OBO posture of ADR-0001 (same identity, the Entra subject, now also partitions memory).
- Retrieval is observable with no custom code: `RetrieveMemoryRecords` invocation count (≈3/turn when active vs. 0 today), its native span, and the SDK's per-turn "Retrieved N customer context items" log tell you at a glance whether memory is working.

**Becomes harder / new burden**
- **Relevance tuning.** 0.3 is a starting floor; too-low surfaces noise, too-high starves the model. Tune from observed scores.
- **Async lag.** A fact stated this turn is not retrievable for seconds-to-minutes; cross-session payoff, not mid-conversation. (In-session recall still rides short-term replay.)
- **Two more log groups / deliveries** to own and budget retention for.

**Will need to revisit**
- **Namespace cut-over.** Flipping `actor_id` orphans anything already extracted under `/facts/order-triage` etc. (it lives under a different namespace and is never retrieved). Acceptable here — the demo holds no real per-user history — but a production cut-over would need a migration or a clean start.
- Whether to promote `top_k`/`relevance_score` to env-driven tunables once a real corpus exists.
- `sub` stability: it is per-(user, app) for this single agent app; if the audience/app identity changes, subjects rotate (and memories re-partition).

## Risks

1. **Relevance threshold mis-set** → noisy or empty context. *Mitigation:* the memory traces (`RetrieveMemoryRecords` spans) + the SDK's retrieved-item-count log; start conservative (0.3) and tune.
2. **Subject claim absent/odd in the v1 token** → falls back to `oid`, then to anonymous `"order-triage"`; retrieval still degrades safely (shared profile, as today). *Mitigation:* the decode is defensive and the fallback is the current behavior.
3. **Decoding an unverified payload** if the inbound path ever changes so the authorizer no longer verifies first. *Mitigation:* documented invariant — `actor_id` derivation depends on the CUSTOM_JWT authorizer having verified the token (ADR-0001); the subject is used only as a partition key, never for an authorization decision.
4. **PII in memory** (the strategies extract whatever users say). *Mitigation:* opaque `sub` as the only identifier in the path; event-expiry retention (90d) on short-term; revisit data-classification of extracted memories if real users are onboarded.

## Action items

1. [x] **D1** — `retrieval_config` added to `agent_kit.infra.memory` (templated namespaces, `top_k`/`relevance_score`).
2. [x] **D2** — JWT-payload subject decode in `agent_kit.infra.identity` (`sub`→`oid`→anonymous); threaded `agent_kit.app → build_agent → build_session_manager`.
3. [x] **D3 (agent)** — no custom span; rely on ADOT auto-instrumentation + native memory spans/logs + the SDK's retrieval log line. Added a `<user_context>` instruction to the system prompt so the model uses the injected block.
4. [x] **D3 (infra)** — memory tracing (`TRACES`→XRAY) + log delivery (`APPLICATION_LOGS`→CWL) in terraform.
5. [x] **Deploy** — applied 2026-06-22 (deploy run 27964171047; runtime image rolled + 7 memory observability resources created). Needed deploy-role CW Logs delivery/tag perms (a bootstrap re-apply, infra #68). Validation (`RetrieveMemoryRecords` > 0 + span in `aws/spans`) pending a live invoke.
6. [ ] **Tune** — review relevance scores from the first real sessions; adjust the 0.3 floor / `top_k`.
7. [ ] **Follow-up (open):** decide whether to env-drive the retrieval tunables; evaluate extracted-memory quality (periodic `ListMemoryRecords` per namespace).

## References

- AWS Bedrock AgentCore: Memory organization, long-term strategies, `RetrieveMemoryRecords`, observability (Transaction Search, per-memory tracing + log delivery), Strands SDK memory integration.
- Terraform: `aws_cloudwatch_log_delivery_source` / `_destination` / `_delivery` (XRAY destination support, aws provider v6.21.0+).
- Internal: memory spike (this session); `agentcore-memory-retrieval-off`; `cloudwatch-genai-observability`; ADR-0001 (CUSTOM_JWT inbound + the Entra subject identity).

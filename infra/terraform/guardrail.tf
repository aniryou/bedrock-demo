# guardrail.tf — Minimum-recommended native Bedrock Guardrail for order-triage-agent.
#
# Optional: set enable_guardrail=false (e.g. in a sandbox) to skip creation entirely. When
# disabled, BEDROCK_GUARDRAIL_ID/VERSION resolve to "" (see runtime.tf) and the agent omits
# the guardrail kwargs, so Strands injects no guardrailConfig (the both-or-nothing rule).
#
# CLASSIC tier, single region (var.region). The only policy is the PROMPT_ATTACK input
# filter — the native mitigation for AUDIT M13 (prompt injection via untrusted Snowflake
# customer names / KB chunks). There is no PII/sensitive-information policy (this agent
# handles customer PII end-to-end, so all PII flows unmasked), and no content (toxicity) or
# word/profanity policy. See docs/research/spike-guardrails.md.

variable "enable_guardrail" {
  type        = bool
  default     = true
  description = "Create and attach the native Bedrock Guardrail. Set false to run the agent with no guardrail (sandbox)."
}

variable "guardrail_prompt_attack_strength" {
  type        = string
  default     = "MEDIUM"
  description = "PROMPT_ATTACK input filter strength (LOW|MEDIUM|HIGH). MEDIUM is the safe default for an authenticated, Cedar-gated tool; raise to HIGH only after validating a multi-turn fraud-hold session (the whole conversation is re-scanned each turn)."
  validation {
    condition     = contains(["LOW", "MEDIUM", "HIGH"], var.guardrail_prompt_attack_strength)
    error_message = "Must be one of LOW, MEDIUM, HIGH."
  }
}

resource "aws_bedrock_guardrail" "order_triage" {
  count = var.enable_guardrail ? 1 : 0

  name                      = "${var.name_prefix}-order-triage"
  description               = "Baseline guardrail for order-triage: PROMPT_ATTACK input filter only (AUDIT M13). No PII, content/toxicity, or word policies by design."
  blocked_input_messaging   = "This request was blocked by the order-triage safety policy."
  blocked_outputs_messaging = "This response was withheld by the order-triage safety policy."

  # --- Content policy: PROMPT_ATTACK input filter ONLY (M13 prompt-injection defense) -----
  # input-only; output_strength must be NONE. This is the single policy on the guardrail.
  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = var.guardrail_prompt_attack_strength
      output_strength = "NONE" # REQUIRED: PROMPT_ATTACK has no output strength; any other value fails the apply.
    }
  }

  # No sensitive_information_policy_config: this agent handles customer PII end-to-end, so
  # PII flows unmasked. No toxic-content categories and no word/profanity policy either —
  # PROMPT_ATTACK is the only enabled policy.
}

# Immutable numbered version. skip_destroy keeps the published snapshot if the DRAFT policy
# changes, avoiding a deploy gap for a runtime pinned to a version number. NOTE: editing the
# guardrail above does NOT affect the runtime until a NEW version is published AND
# BEDROCK_GUARDRAIL_VERSION is bumped (see runtime.tf) — that is intentional.
resource "aws_bedrock_guardrail_version" "order_triage" {
  count = var.enable_guardrail ? 1 : 0

  guardrail_arn = aws_bedrock_guardrail.order_triage[0].guardrail_arn
  description   = "order-triage baseline v1"
  skip_destroy  = true
}

output "guardrail_id" {
  value       = var.enable_guardrail ? aws_bedrock_guardrail.order_triage[0].guardrail_id : ""
  description = "Bedrock Guardrail id wired into the runtime as BEDROCK_GUARDRAIL_ID (empty when disabled)."
}

output "guardrail_version" {
  value       = var.enable_guardrail ? aws_bedrock_guardrail_version.order_triage[0].version : ""
  description = "Published guardrail version wired into the runtime as BEDROCK_GUARDRAIL_VERSION (empty when disabled)."
}

output "guardrail_arn" {
  value       = var.enable_guardrail ? aws_bedrock_guardrail.order_triage[0].guardrail_arn : ""
  description = "Guardrail ARN (used to scope bedrock:ApplyGuardrail in iam.tf)."
}

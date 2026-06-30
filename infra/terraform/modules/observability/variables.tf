# Inputs for the observability module. Tunables are declared at the root (set via TF_VAR)
# and passed in here; the rest are the identifiers of the resources this module observes.

variable "name_prefix" { type = string }
variable "region" { type = string }
variable "account_id" { type = string }
variable "bedrock_model_id" { type = string }

variable "memory_log_retention_days" { type = number }
variable "bedrock_invocation_log_retention_days" { type = number }
variable "function_log_retention_days" { type = number }

variable "alert_email" {
  type        = string
  description = "Email subscribed to the alarm SNS topic; empty = topic with no subscription."
}

variable "model_input_usd_per_million" {
  type        = number
  description = "Estimate-only input-token price ($/1M) for the FinOps dashboard tile."
}

variable "model_output_usd_per_million" {
  type        = number
  description = "Estimate-only output-token price ($/1M) for the FinOps dashboard tile."
}

variable "trace_indexing_percentage" {
  type        = number
  description = "Transaction Search indexing rate (% of spans indexed for search). Cost/search lever only; does not reduce span storage."
}

variable "deploy_marker_ts" {
  type        = string
  description = "ISO8601 deploy timestamp; empty => no dashboard deploy marker."
}

variable "enable_online_evaluations" {
  type        = bool
  description = "Whether AgentCore online Evaluations are enabled (configured out-of-band); drives the Operations dashboard's eval note."
}

variable "enable_actor_resolution" {
  type        = bool
  default     = true
  description = "Render the FinOps 'Top actors' leaderboard and the Governance audit actor column via a Graph-backed custom-widget Lambda that resolves the Entra oid to a display name (ADR-0007). On by default. Needs the entra/ graph_resolver app + graph_resolver_secret_name. Off => the opaque-id widgets."
}

variable "graph_resolver_secret_name" {
  type        = string
  default     = "order-triage-graph-resolver"
  description = "Secrets Manager secret holding the Graph app creds JSON {tenant_id, client_id, client_secret}. Seed via `make seed-graph-secret`. Used when enable_actor_resolution = true (the default)."
}

# Identifiers of the resources this module observes.
variable "runtime_arn" { type = string }
variable "runtime_id" { type = string }
variable "gateway_arn" { type = string }
variable "gateway_id" { type = string }
variable "memory_arn" { type = string }
variable "memory_id" { type = string }
variable "knowledge_base_arn" { type = string }
variable "knowledge_base_id" { type = string }

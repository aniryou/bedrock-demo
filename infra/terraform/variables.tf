variable "region" {
  type        = string
  default     = "us-west-2"
  description = "AWS region (AgentCore + Bedrock must be available in this region)."
}

variable "name_prefix" {
  type    = string
  default = "order-triage"
}

variable "bedrock_model_id" {
  type        = string
  default     = "amazon.nova-lite-v1:0"
  description = "Bedrock model id the deployed agent uses (runtime env BEDROCK_MODEL_ID). Default Amazon Nova Lite: on-demand pay-per-use, supports tool use, no model-access form. Anthropic models need a use-case form and an inference-profile id (e.g. us.anthropic.claude-sonnet-4-6)."
}

variable "snowflake_api_key" {
  type        = string
  sensitive   = true
  description = "REQUIRED (no default — fail fast). Outbound API key for the Snowflake-query Lambda, whose Function URL stays authorization_type=NONE because its single Gateway egress slot carries the Entra OBO TOKEN_EXCHANGE credential, not SigV4. Presented by the order-actions Lambda's direct call and used as the Snowflake target's creation-time credential placeholder. Supply via TF_VAR_snowflake_api_key; the orchestrator exports it from SNOWFLAKE_API_KEY in .env."
}

variable "snowflake_secret_name" {
  type        = string
  default     = "order-triage/snowflake"
  description = "Secrets Manager secret holding the Snowflake key-pair creds + connection config (account, host, user, role, warehouse, database, schema, private_key_pem). Read by the snowflake-query Lambda. Keep in sync with SNOWFLAKE_SECRET_NAME in scripts/snowflake_bootstrap.py (same default)."
}

# --- tunables (defaults match the deployed demo; override per-environment) ----

variable "embedding_model_id" {
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
  description = "Bedrock embedding model for the Knowledge Base. MUST move in lockstep with var.embedding_dimension — an S3 Vectors index cannot be resized after creation."
}

variable "embedding_dimension" {
  type        = number
  default     = 1024
  description = "Output width of var.embedding_model_id and the S3 Vectors index dimension. Titan Text Embeddings v2 = 1024. Change only together with the model id."
}

variable "lambda_runtime" {
  type        = string
  default     = "python3.12"
  description = "Runtime shared by the stub Lambdas (must match the published zips)."
}

variable "lambda_architectures" {
  type        = list(string)
  default     = ["arm64"]
  description = "CPU architecture shared by the stub Lambdas (must match the prebuilt CI artifacts)."
}

variable "lambda_timeout" {
  type        = number
  default     = 30
  description = "Timeout (seconds) for the SAP + order-actions stub Lambdas."
}

variable "snowflake_lambda_timeout" {
  type        = number
  default     = 60
  description = "Timeout (seconds) for the Snowflake-query Lambda — intentionally higher than var.lambda_timeout to absorb warehouse auto-resume on a cold query."
}

variable "memory_event_expiry_days" {
  type        = number
  default     = 90
  description = "AgentCore Memory short-term raw event retention, in days."
}

variable "memory_log_retention_days" {
  type        = number
  default     = 30
  description = "Retention (days) for the AgentCore Memory APPLICATION_LOGS CloudWatch Logs group (observability.tf)."
}

variable "bedrock_invocation_log_retention_days" {
  type        = number
  default     = 30
  description = "Retention (days) for the Bedrock model-invocation-logging CloudWatch Logs group (invocation_logging.tf)."
}

variable "function_log_retention_days" {
  type        = number
  default     = 30
  description = "Retention (days) for the SAP/Snowflake/order-actions Lambda CloudWatch Logs groups (log_groups.tf)."
}

variable "max_tokens" {
  type        = number
  default     = 4096
  description = "MAX_TOKENS the deployed agent passes to the model (runtime env var)."
}

variable "gateway_iam_propagation_delay" {
  type        = string
  default     = "30s"
  description = "RACE 1 cold-start gate: wait for the gateway IAM role to propagate before CreateGateway. Bump if a from-scratch apply 403s on CreateGateway."
}

variable "target_actions_propagation_delay" {
  type        = string
  default     = "90s"
  description = "RACE 2 cold-start gate: wait for gateway-target OpenAPI actions to register before creating Cedar policies. Bump if a from-scratch apply hits 'unrecognized action'."
}

# --- inputs published by the other repos -------------------------------------

variable "agent_image_uri" {
  type        = string
  description = "ECR image URI built & pushed by order-triage-agent CI (e.g. <acct>.dkr.ecr.<region>.amazonaws.com/order-triage-agent:latest). From `bootstrap` output ecr_repository_url."
}

variable "artifacts_bucket" {
  type        = string
  description = "S3 bucket where the agent publishes kb/ and the stubs publish stubs/*.zip + *.openapi.json. From `bootstrap` output artifacts_bucket."
}

# --- Microsoft Entra (the agent's inbound identity + OBO) ----------------------
# REQUIRED: the agent is Gateway-only and the runtime is CUSTOM_JWT, so these gate the
# inbound user JWT (runtime.tf / gateway.tf) and the Snowflake target's TOKEN_EXCHANGE
# egress (snowflake_lambda.tf). Supplied via TF_VAR_entra_* (the orchestrator exports them
# from the ENTRA_* keys in .env). No defaults — apply fails fast if unset.
variable "entra_tenant_id" {
  type        = string
  description = "Entra tenant id for the CUSTOM_JWT OIDC discovery + the OBO provider. From ENTRA_TENANT_ID."
}

variable "entra_agent_app_id" {
  type        = string
  description = "Entra agent/middle-tier app client_id — the CUSTOM_JWT audience + the OBO OAuth client. From ENTRA_AGENT_APP_ID."
}

variable "entra_obo_scope" {
  type        = string
  description = "Snowflake resource scope the Gateway requests at TOKEN_EXCHANGE time, e.g. api://<snowflake-app>/session:role-any. From ENTRA_OBO_SCOPE (snowflake_lambda.tf egress)."
}

# --- Observability tunables (passed into module.observability) -----------------
variable "trace_indexing_percentage" {
  type        = number
  default     = 100
  description = "Transaction Search indexing rate (% of ingested spans indexed for search/analytics). Cost + search-surface lever only — does not reduce span storage in aws/spans (head sampling + retention + data-protection govern PII volume). 100 = index everything; lower (e.g. 10) to cut indexing cost. AWS may clamp very-low values upward."
}

variable "deploy_marker_ts" {
  type        = string
  default     = ""
  description = "ISO8601 UTC deploy timestamp (set by CI in deploy.yml) marking the release on the dashboards. Empty => no marker rendered, so local `make plan` stays diff-free."
}

variable "alert_email" {
  type        = string
  default     = ""
  description = "Email subscribed to the alarm SNS topic. Empty = topic with no subscription; the recipient must confirm the SNS email before alarms notify."
}

variable "model_input_usd_per_million" {
  type        = number
  default     = 0.06
  description = "Estimate-only input-token price ($/1M) for the FinOps dashboard tile (Nova Lite default; not billing-accurate)."
}

variable "model_output_usd_per_million" {
  type        = number
  default     = 0.24
  description = "Estimate-only output-token price ($/1M) for the FinOps dashboard tile (Nova Lite default; not billing-accurate)."
}

variable "enable_online_evaluations" {
  type        = bool
  default     = false
  description = "Whether AgentCore online Evaluations are enabled (configured out-of-band via bedrock-agentcore-control). Drives the Operations dashboard's eval note; does not itself enable evaluation."
}

variable "enable_actor_resolution" {
  type        = bool
  default     = false
  description = "Resolve the FinOps 'Top actors' Entra oid to a display name via a Graph-backed custom-widget Lambda (ADR-0007). Needs the entra/ graph_resolver app + graph_resolver_secret_name + the agent emitting actor_oid."
}

variable "graph_resolver_secret_name" {
  type        = string
  default     = ""
  description = "Secrets Manager secret holding the Graph app creds JSON {tenant_id, client_id, client_secret} for actor resolution. Seed via `make seed-graph-secret`. Required when enable_actor_resolution = true."
}

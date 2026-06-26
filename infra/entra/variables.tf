variable "resource_app_name" {
  description = "Display name of the Snowflake resource app registration."
  type        = string
  default     = "order-triage-snowflake"
}

variable "agent_app_name" {
  description = "Display name of the agent / middle-tier app registration."
  type        = string
  default     = "order-triage-agent"
}

variable "obo_scope_value" {
  description = "Delegated scope exposed by the resource app and carried in the OBO token's scp. Snowflake AZURE only parses session:role-any or session:role:<ROLE>."
  type        = string
  default     = "session:role-any"
}

variable "agent_scope_value" {
  description = "Delegated scope the agent app exposes for inbound user sign-in."
  type        = string
  default     = "access_as_user"
}

variable "redirect_uris" {
  description = "Web redirect URIs on the agent app (webapp callback + the CLI loopback mint). A host:port URI with no path needs a trailing slash (azuread provider validation)."
  type        = list(string)
  default     = ["http://localhost:8000/callback", "http://localhost:8400/"]
}

variable "secret_name" {
  description = "Display name of the agent app's client secret."
  type        = string
  default     = "obo-agent-secret"
}

variable "secret_end_date_relative" {
  description = "Lifetime of the generated client secret (Go duration; 17520h = 2 years)."
  type        = string
  default     = "17520h"
}

variable "graph_resolver_app_name" {
  description = "Display name of the app-only Graph resolver app (dashboard actor resolution, ADR-0007)."
  type        = string
  default     = "order-triage-graph-resolver"
}

variable "graph_resolver_secret_name" {
  description = "Display name of the Graph resolver app's client secret."
  type        = string
  default     = "graph-resolver-secret"
}

# These map 1:1 to the ENTRA_* keys in bedrock-demo/.env (see the README).
output "tenant_id" {
  value = data.azuread_client_config.current.tenant_id
}
output "resource_app_id" {
  value = azuread_application.resource.client_id
}
output "resource_audience" {
  value = azuread_application_identifier_uri.resource.identifier_uri
}
output "agent_app_id" {
  value = azuread_application.agent.client_id
}
output "agent_audience" {
  value = azuread_application_identifier_uri.agent.identifier_uri
}
output "agent_scope" {
  value = "api://${azuread_application.agent.client_id}/${var.agent_scope_value}"
}
output "obo_scope" {
  value = "api://${azuread_application.resource.client_id}/${var.obo_scope_value}"
}
output "token_endpoint" {
  value = "https://login.microsoftonline.com/${data.azuread_client_config.current.tenant_id}/oauth2/v2.0/token"
}
output "agent_client_secret" {
  value     = azuread_application_password.agent.value
  sensitive = true
}

# Graph resolver app (ADR-0007). `make seed-graph-secret` reads these into the Secrets Manager
# secret the actor-resolver Lambda consumes; the secret value never enters the main stack state.
output "graph_resolver_client_id" {
  value = azuread_application.graph_resolver.client_id
}
output "graph_resolver_client_secret" {
  value     = azuread_application_password.graph_resolver.value
  sensitive = true
}

data "azuread_client_config" "current" {}

# Microsoft Graph: well-known appId + an SP handle to resolve the User.Read scope GUID.
data "azuread_application_published_app_ids" "well_known" {}

resource "azuread_service_principal" "msgraph" {
  client_id    = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
  use_existing = true
}

# Stable GUIDs for the exposed scopes (kept in state, so re-applies don't churn grants).
resource "random_uuid" "obo_scope" {}
resource "random_uuid" "agent_scope" {}

# ── Resource app (Snowflake) ─────────────────────────────────────────────────
resource "azuread_application" "resource" {
  display_name     = var.resource_app_name
  sign_in_audience = "AzureADMyOrg"

  api {
    # v1 access tokens → iss=https://sts.windows.net/<tenant>/ (+ upn), required by
    # Snowflake EXTERNAL_OAUTH_TYPE=AZURE. (v2 tokens silently fail there.)
    requested_access_token_version = 1

    oauth2_permission_scope {
      id                         = random_uuid.obo_scope.result
      value                      = var.obo_scope_value
      type                       = "Admin"
      admin_consent_display_name = var.obo_scope_value
      admin_consent_description  = "OBO role carrier: ${var.obo_scope_value}"
      enabled                    = true
    }
  }
}

# api://<client_id> — a separate resource breaks the application↔URI self-reference cycle.
resource "azuread_application_identifier_uri" "resource" {
  application_id = azuread_application.resource.id
  identifier_uri = "api://${azuread_application.resource.client_id}"
}

resource "azuread_service_principal" "resource" {
  client_id = azuread_application.resource.client_id
}

# ── Agent app (middle tier) ──────────────────────────────────────────────────
resource "azuread_application" "agent" {
  display_name     = var.agent_app_name
  sign_in_audience = "AzureADMyOrg"

  web {
    redirect_uris = var.redirect_uris
  }

  api {
    requested_access_token_version = 1

    oauth2_permission_scope {
      id                         = random_uuid.agent_scope.result
      value                      = var.agent_scope_value
      type                       = "User"
      admin_consent_display_name = var.agent_scope_value
      admin_consent_description  = "Allow the app to act as the signed-in user."
      user_consent_display_name  = var.agent_scope_value
      user_consent_description   = "Allow the app to act as you."
      enabled                    = true
    }
  }

  # Delegated permissions the agent needs: the resource OBO scope + Graph User.Read.
  required_resource_access {
    resource_app_id = azuread_application.resource.client_id
    resource_access {
      id   = random_uuid.obo_scope.result
      type = "Scope"
    }
  }
  required_resource_access {
    resource_app_id = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
    resource_access {
      id   = azuread_service_principal.msgraph.oauth2_permission_scope_ids["User.Read"]
      type = "Scope"
    }
  }
}

resource "azuread_application_identifier_uri" "agent" {
  application_id = azuread_application.agent.id
  identifier_uri = "api://${azuread_application.agent.client_id}"
}

resource "azuread_service_principal" "agent" {
  client_id = azuread_application.agent.client_id
}

resource "azuread_application_password" "agent" {
  application_id    = azuread_application.agent.id
  display_name      = var.secret_name
  end_date_relative = var.secret_end_date_relative
}

# Pre-authorize the agent app for the resource OBO scope → no consent prompt at OBO time.
resource "azuread_application_pre_authorized" "agent_on_resource" {
  application_id       = azuread_application.resource.id
  authorized_client_id = azuread_application.agent.client_id
  permission_ids       = [random_uuid.obo_scope.result]
}

# Admin consent (tenant-wide delegated grants): agent SP → resource (role-any) + Graph (User.Read).
resource "azuread_service_principal_delegated_permission_grant" "agent_to_resource" {
  service_principal_object_id          = azuread_service_principal.agent.object_id
  resource_service_principal_object_id = azuread_service_principal.resource.object_id
  claim_values                         = [var.obo_scope_value]
}

resource "azuread_service_principal_delegated_permission_grant" "agent_to_graph" {
  service_principal_object_id          = azuread_service_principal.agent.object_id
  resource_service_principal_object_id = azuread_service_principal.msgraph.object_id
  claim_values                         = ["User.Read"]
}

# ── Graph resolver app (app-only; dashboard actor resolution, ADR-0007) ───────
# A daemon app with the application permission Graph User.Read.All, so the actor-resolver Lambda
# can resolve an Entra oid -> displayName via client credentials (no signed-in user). Distinct
# from the agent app's DELEGATED User.Read (which acts as the signed-in user).
resource "azuread_application" "graph_resolver" {
  display_name     = var.graph_resolver_app_name
  sign_in_audience = "AzureADMyOrg"

  required_resource_access {
    resource_app_id = data.azuread_application_published_app_ids.well_known.result["MicrosoftGraph"]
    resource_access {
      id   = azuread_service_principal.msgraph.app_role_ids["User.Read.All"]
      type = "Role" # application permission (app role), not a delegated scope
    }
  }
}

resource "azuread_service_principal" "graph_resolver" {
  client_id = azuread_application.graph_resolver.client_id
}

resource "azuread_application_password" "graph_resolver" {
  application_id    = azuread_application.graph_resolver.id
  display_name      = var.graph_resolver_secret_name
  end_date_relative = var.secret_end_date_relative
}

# Admin consent for the app-only User.Read.All (app-role assignment grant).
resource "azuread_app_role_assignment" "graph_resolver_user_read_all" {
  app_role_id         = azuread_service_principal.msgraph.app_role_ids["User.Read.All"]
  principal_object_id = azuread_service_principal.graph_resolver.object_id
  resource_object_id  = azuread_service_principal.msgraph.object_id
}

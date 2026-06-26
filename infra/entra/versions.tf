# Declarative alternative to scripts/entra_provision.py — the Entra OBO apps as IaC.
# Authenticates via the Azure CLI (run `az login --tenant <id>` first). Separate state
# (not part of the AWS main/bootstrap stacks) so it's never torn down with the AWS stack.
terraform {
  required_version = ">= 1.5"
  required_providers {
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azuread" {
  # Uses Azure CLI auth by default (the `az login` context). To target a specific
  # tenant explicitly, set ARM_TENANT_ID or `tenant_id` here.
}

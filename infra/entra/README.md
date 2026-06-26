# entra/ — Entra OBO apps as Terraform (azuread)

Declarative alternative to `scripts/entra_provision.py` (the az-CLI provisioner). Same
result — the two app registrations (resource + agent), scopes, `api://` URIs, **v1 tokens**,
pre-authorization, delegated perms, a client secret, and admin consent — but managed as IaC
with drift detection. Authenticates via the **Azure CLI** (`az login`), so no extra creds.

Separate Terraform state (local, not the AWS S3 backend) so these tenant-level apps are
**never** torn down with the AWS stack.

## Use (fresh tenant)
```bash
az login --tenant <TENANT_ID>     # an admin who can create apps + grant consent (manual; MFA)
cd bedrock-demo-infra
make entra-tf-plan                # review
make entra-tf                     # apply
# copy outputs into bedrock-demo/.env:
terraform -chdir=entra output -raw resource_app_id   # → ENTRA_RESOURCE_APP_ID
terraform -chdir=entra output -raw agent_app_id      # → ENTRA_AGENT_APP_ID
terraform -chdir=entra output -raw agent_client_secret  # → ENTRA_AGENT_CLIENT_SECRET (sensitive)
# ... (resource_audience, agent_audience, agent_scope, obo_scope, token_endpoint, tenant_id) ...
then: make snowflake-obo   # Snowflake AZURE integration from the ENTRA_* values
```

## az CLI vs Terraform — pick one
- **`make entra-setup`** (az CLI): idempotent, imperative, no state file, safe to re-run on an
  already-configured tenant (reuses scope GUIDs, keeps the existing secret). This is what the
  live `163debb3…` tenant was provisioned with.
- **`make entra-tf`** (this module): declarative + drift detection, but it will **create new
  apps** in whatever tenant you're logged into — so use it for a **fresh** tenant, or
  `terraform import` the existing apps first (otherwise you get duplicates).

## Stays manual (both paths)
The tenant itself, `az login`, and user creation + MFA enrolment.

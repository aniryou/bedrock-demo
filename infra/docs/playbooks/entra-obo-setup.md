# Runbook: Entra ID → AgentCore OBO → Snowflake (native OBO)

Stands up the **Microsoft Entra ID** side of the full-native on-behalf-of chain and the
Snowflake trust, replacing the Cognito spike (which couldn't do the OBO token exchange).
Verified against Microsoft identity-platform + Snowflake docs. This is **deployed and live**:
the runtime and Gateway run `CUSTOM_JWT` inbound on the Entra user JWT (the earlier SigV4
inbound was retired) — see `terraform/runtime.tf` / `terraform/gateway.tf`.

> **Access note:** the Entra app registrations need an Azure tenant + admin (App
> registrations, admin consent). **Steps 1–2 are now fully reproducible via the az CLI —
> `make entra-setup`** (see "Reproducible setup" immediately below); the portal walk-through
> in Steps 1–2 is the *explanation* of what that script does. The Snowflake integration
> (Step 3) is `make snowflake-obo`, and the AWS OBO credential provider (Step 4) is Terraform.

## The chain (what we're building)

```
user signs in to Entra (front-end app)
  -> inbound user access token (aud = AGENT app)         [CUSTOM_JWT inbound — live]
  -> AgentCore OBO: GetWorkloadAccessTokenForJWT -> GetResourceOauth2Token
       (provider = MicrosoftOauth2 + tenant_id; oauth2_flow=ON_BEHALF_OF_TOKEN_EXCHANGE;
        scope = api://<SNOWFLAKE-APP>/session:role-any; vendor adds requested_token_use itself)
  -> downstream token (aud = SNOWFLAKE resource app, scp contains session:role-any)
  -> Snowflake SQL REST API (X-Snowflake-Authorization-Token-Type: OAUTH)
       EXTERNAL_OAUTH_TYPE=AZURE maps upn -> Snowflake user, scp -> login role
```

## Reproducible setup (az CLI) — preferred

The whole Entra + Snowflake-trust setup is automated. In a fresh tenant:

```bash
az login --tenant <TENANT_ID>          # an admin who can create apps + grant consent (manual; MFA)
cd infra
make entra-setup ARGS=--dry-run        # preview (reads only, mutates nothing)
make entra-setup ARGS=--write-env      # provision BOTH apps (idempotent) → writes ENTRA_* to ../.env
make snowflake-obo                     # Snowflake EXTERNAL_OAUTH (AZURE) integration from the ENTRA_* values
# then (manual / Terraform):
#   - create demo users + MFA enrolment (privileged) + their Snowflake users (snowflake/test_user.sql)
#   - AWS OBO credential provider — Terraform identity.tf, applied by `make deploy`
```

- **`make entra-setup`** = `scripts/entra_provision.py`, an **idempotent** wrapper over `az`
  + `az rest` (Microsoft Graph). It creates/updates the **resource app** (`api://<id>`,
  **v1 tokens** = `requestedAccessTokenVersion:null`, scope `session:role-any`, agent app
  **pre-authorized**) and the **agent app** (`api://<id>`, redirect `http://localhost:8000/callback`
  + `:8400` for the CLI token mint, `access_as_user`, delegated perms = resource scope +
  Graph `User.Read`, a client secret, and **admin consent**). Re-runs reuse existing scope
  GUIDs and **keep the existing secret** (so it's safe to re-run on a live tenant).
  `ARGS=--dry-run` plans without mutating; `ARGS=--write-env` writes the resulting `ENTRA_*`
  (including a freshly-created secret) into `bedrock-demo/.env`.
- **Stays manual** (privileged / interactive — not scripted): the tenant itself, `az login`,
  and user creation + MFA enrolment.
- The script intentionally **drops** the legacy `session:scope:AGENT_RO` scope from the
  hand-built apps — Snowflake's AZURE handler can't parse `session:scope:<ROLE>` (→ 390317);
  the role carrier is `session:role-any`.

The per-field rationale for everything the script sets is in Steps 1–4 below.

---

## Step 1 — Entra: the **Snowflake resource** app  *(automated by `make entra-setup`; manual walk-through)*

1. Register an app, e.g. `order-triage-snowflake`.
2. **Expose an API** → set the **Application ID URI**, e.g. `api://order-triage-snowflake`.
   This URI is the token `aud`, the `EXTERNAL_OAUTH_AUDIENCE_LIST` value, and the base of
   the OBO scope.
3. **Add a scope** named **`session:role-any`** (delegated, "Admins only" is fine).
   > ⚠️ CORRECTION (proven 2026-06-20): Snowflake's AZURE External OAuth only recognises
   > `session:role-any` or `session:role:<ROLE>` in the token's `scp`. A scope named
   > `session:scope:<ROLE>` is **not** parsed as a role → login fails with **390317** even with
   > `ANY_ROLE_MODE=ENABLE`. Name the scope `session:role-any` (the user's Snowflake grants then
   > govern the role — the intersection model) or `session:role:<ROLE>` to pin a specific role.
   > It must still be a **delegated scope** (not an App Role) — OBO only carries delegated
   > scopes — but it is the *value* `session:role-any` (colon + hyphen) that Snowflake parses.
   > **Pre-authorize the agent app** for this scope under the resource app's *Authorized client
   > applications* (preAuthorizedApplications) so the OBO/auth-code exchange needs no runtime consent.
4. **Pin v1 tokens**: in the app **Manifest**, set `requestedAccessTokenVersion` to `null`
   (or `1`). This makes the issued token `iss = https://sts.windows.net/<tenant>/` and
   include `upn` — both required by Snowflake's AZURE integration. (v2 tokens use
   `login.microsoftonline.com/.../v2.0` + `preferred_username` and will silently fail login.)

## Step 2 — Entra: the **agent / middle-tier** app  *(yours)*

1. Register an app, e.g. `order-triage-agent`. Create a **client secret** (→ the OBO
   credential provider's `client_id` / `client_secret`).
2. **API permissions** → add a **delegated** permission to `order-triage-snowflake`'s
   `session:role-any` → **Grant admin consent**. (AZURE External OAuth does **not** parse the
   `session:scope:<ROLE>` carrier — the role must arrive as `session:role-any` or
   `session:role:<ROLE>` in `scp`, else Snowflake errors `390317`.)
   (OBO does not prompt at runtime; consent must be pre-granted — admin consent or list the
   agent app under the resource app's `preAuthorizedApplications`.)
3. Leave the agent app on **v1 tokens** (`requestedAccessTokenVersion = null`/`1`) so the
   **inbound** user token's `aud` is `api://<agent-app-client-id>` → the runtime's/Gateway's
   `CUSTOM_JWT` `allowed_audience = ["api://<agent-app-client-id>"]`. This is what the live
   build sets (`entra/main.tf`, `terraform/gateway.tf`, `terraform/runtime.tf`, and
   `scripts/entra_provision.py`). (The alternative — v2 tokens
   (`accessTokenAcceptedVersion = 2`) → a bare-GUID `aud` → `allowedAudiences = ["<guid>"]` —
   is **not** what's deployed; don't mix the two or CUSTOM_JWT auth fails on an `aud` mismatch.)
4. The user-facing sign-in (front-end) app's `client_id` → `CUSTOM_JWT` **`allowedClients`**
   (the `azp`/`appid`), or omit `allowedClients`. Do **not** point `allowedClients` at the
   agent app.

**Hand back to the build:** tenant id, `api://order-triage-snowflake` (audience), the
exposed scope full name `api://order-triage-snowflake/session:role-any`, and the agent
app's client_id + client_secret.

## Step 3 — Snowflake: the AZURE External OAuth integration  *(I can apply once Step 1 IDs exist)*

Run as ACCOUNTADMIN via the bootstrap key-pair (helper:
`python scripts/extoauth_spike.py create-azure-integration`, parameterized by env):

```sql
CREATE OR REPLACE SECURITY INTEGRATION entra_obo
  TYPE = external_oauth
  ENABLED = true
  EXTERNAL_OAUTH_TYPE = azure
  EXTERNAL_OAUTH_ISSUER = 'https://sts.windows.net/<TENANT_ID>/'                         -- v1 issuer, trailing slash, exact case
  EXTERNAL_OAUTH_JWS_KEYS_URL = 'https://login.microsoftonline.com/<TENANT_ID>/discovery/v2.0/keys'
  EXTERNAL_OAUTH_AUDIENCE_LIST = ('api://order-triage-snowflake')                        -- = resource app's Application ID URI
  EXTERNAL_OAUTH_TOKEN_USER_MAPPING_CLAIM = ('upn','email')   -- email covers guest/live.com users w/o upn
  EXTERNAL_OAUTH_SNOWFLAKE_USER_MAPPING_ATTRIBUTE = 'login_name'
  EXTERNAL_OAUTH_ANY_ROLE_MODE = 'ENABLE';
-- Do NOT set EXTERNAL_OAUTH_SCOPE_MAPPING_ATTRIBUTE: it's CUSTOM-only and AZURE rejects it.
-- The login role comes from `session:role-any` / `session:role:<ROLE>` in `scp` (NOT session:scope:).
-- With session:role-any + ANY_ROLE_MODE=ENABLE the user's Snowflake grants govern (default role,
-- or an explicitly-requested granted role) — the intersection-authz model.
```

**User provisioning:** each demo human is a Snowflake user whose `LOGIN_NAME` equals the token's
mapping claim (managed users: `upn`; guest/live.com: `email`) — matched **case-insensitively** —
GRANTed the read role. The live read-only role is **`ORDER_TRIAGE_RO`** (the test-fixture
`AGENT_RO` does not exist on GA20262):
```sql
CREATE USER IF NOT EXISTS ANIL_ENTRA LOGIN_NAME='anil.iiitm@gmail.com'
  EMAIL='anil.iiitm@gmail.com' DEFAULT_ROLE=ORDER_TRIAGE_RO MUST_CHANGE_PASSWORD=FALSE;
GRANT ROLE ORDER_TRIAGE_RO TO USER ANIL_ENTRA;
```

## Step 4 — AWS: the OBO credential provider  *(FINAL — verified live)*

**Canonical: the `MicrosoftOauth2` vendor WITH `tenant_id`, via `awscc`** (verified
2026-06-21 → `current_user()=ANIL_ENTRA`). OBO is NOT a provider setting — there's no
on-behalf-of config; OBO is a **runtime flow** chosen at token-fetch. The provider is
just the OAuth2 client. `tenant_id` is the key: it makes discovery tenant-specific so the
exchange works for personal/guest accounts (omitting it → `/common` → AADSTS500202), AND
the MicrosoftOauth2 vendor then adds `requested_token_use=on_behalf_of` itself.

`tenant_id` exists only on the **awscc** (Cloud Control) resource — `hashicorp/aws` v6's
`microsoft_oauth2_provider_config` has no tenant field (so it's stuck on `/common`).

Terraform (`terraform/identity.tf`, count-guarded on `var.entra_agent_app_id`):
```hcl
data "aws_secretsmanager_secret" "entra_obo" {
  count = var.entra_agent_app_id != "" ? 1 : 0
  name  = "order-triage/entra-agent-client-secret"
}

resource "awscc_bedrockagentcore_o_auth_2_credential_provider" "entra_obo" {
  count                      = var.entra_agent_app_id != "" ? 1 : 0
  name                       = "entra-obo"
  credential_provider_vendor = "MicrosoftOauth2"
  oauth_2_provider_config_input = {
    microsoft_oauth_2_provider_config = {
      client_id            = var.entra_agent_app_id   # the AGENT app
      tenant_id            = var.entra_tenant_id      # → tenant-specific discovery
      client_secret_source = "EXTERNAL"               # secret read from Secrets Manager, not state
      client_secret_config = {
        secret_id = data.aws_secretsmanager_secret.entra_obo[0].arn
        json_key  = "client_secret"
      }
    }
  }
}
```
The client secret VALUE lives in AWS Secrets Manager (container created by the bootstrap
stack), injected out-of-band by **`make seed-entra-secret`** (`scripts/seed_entra_secret.sh`) —
never as a `TF_VAR`, so it never lands in Terraform state. The other `TF_VAR_entra_*` (tenant /
app id / scope) are still injected from `.env`.

> **Rotate before expiry.** The Entra **agent** app's client secret expires **2026-12-17**.
> This tenant blocks *creating* new secrets, so add an exempting `appManagementPolicy` first,
> then update `ENTRA_AGENT_CLIENT_SECRET` in `../.env` and re-seed with `make seed-entra-secret`
> (existing-secret auth keeps working; only creation is blocked).
>
> `make seed-entra-secret` does a `put-secret-value` **in place**, so the Secrets Manager
> ARN (incl. its random suffix) is unchanged — and the gateway role's `GetSecretValue` grant,
> which pins that **exact** ARN (`iam.tf:aws_iam_role_policy.gateway`, ADR-0006 D4/R2), keeps
> working. Only **deleting + recreating** the secret container gives it a new suffix; if that
> ever happens, run `make deploy` so the gateway policy re-resolves the new ARN — otherwise the
> Gateway-brokered OBO fails with a silent `GetSecretValue` AccessDenied at `TOKEN_EXCHANGE`.

> **Fallback (if you can't use awscc):** a **CustomOauth2** provider with a tenant-specific
> `oauth_discovery.discovery_url` + `on_behalf_of_token_exchange_config.grant_type =
> JWT_AUTHORIZATION_GRANT`. That works too, but it does NOT add `requested_token_use`, so the
> agent must pass `customParameters={"requested_token_use":"on_behalf_of"}` at fetch time
> (else AADSTS900144).

> **Runtime IAM gotcha (required):** `GetResourceOauth2Token` reads the provider's
> client_secret (an AgentCore-managed secret, prefix `bedrock-agentcore-identity!`) using
> the **caller's** role. The runtime execution role needs `secretsmanager:GetSecretValue` on
> `arn:...:secret:bedrock-agentcore-identity!*` — without it the OBO fails AccessDenied
> (already added to `aws_iam_role_policy.runtime` in iam.tf).

The OBO is a **two-call flow** that the **Gateway** now performs (grantType=TOKEN_EXCHANGE on
the snowflake target — see `terraform/snowflake_lambda.tf`), retiring the old in-agent mint:
`GetWorkloadAccessTokenForJWT(workload, <inbound user JWT>)` →
`GetResourceOauth2Token(workload_token, "entra-obo", scopes=[<.../session:role-any>],
oauth2_flow=ON_BEHALF_OF_TOKEN_EXCHANGE)` → the Snowflake-bound token. With MicrosoftOauth2
no custom parameters are needed.

## Step 5 — Validate (Snowflake side, once a token can be minted)

Mint an Entra user token for the resource-app scope. **Device-code does NOT work** here: the
agent app is confidential (has a secret) and this tenant blocks public-client device-code —
`AADSTS7000218` both with and without the secret, even with "Allow public client flows" enabled.
Use the **authorization-code flow** (confidential client + secret), capturing the code with a
throwaway loopback listener so nothing is hand-transcribed:

```bash
# 1. add an http://localhost (Web) redirect to the AGENT app; start a listener on :8400
python3 -c 'import http.server,socketserver,urllib.parse as u; \
 H=type("H",(http.server.BaseHTTPRequestHandler,),{"do_GET":lambda s:(open(".code","w").write(\
 dict(u.parse_qsl(u.urlparse(s.path).query)).get("code","")),s.send_response(200),s.end_headers()),\
 "log_message":lambda *a:None}); socketserver.TCPServer(("127.0.0.1",8400),H).serve_forever()' &
# 2. open the authorize URL in a signed-in browser (Entra accepts the :8400 loopback port):
#    https://login.microsoftonline.com/<TENANT>/oauth2/v2.0/authorize?client_id=<AGENT>
#      &response_type=code&redirect_uri=http%3A%2F%2Flocalhost%3A8400&response_mode=query
#      &scope=api%3A%2F%2F<SNOWFLAKE-APP>%2Fsession%3Arole-any
# 3. exchange the captured code (confidential — send client_secret; secret may start with '~',
#    so read it with grep/cut, never `source .env`, to avoid shell tilde-expansion):
curl -s https://login.microsoftonline.com/<TENANT>/oauth2/v2.0/token \
  -d grant_type=authorization_code -d client_id=<AGENT> --data-urlencode client_secret=<SECRET> \
  --data-urlencode code@.code -d redirect_uri=http://localhost:8400 \
  --data-urlencode 'scope=api://<SNOWFLAKE-APP>/session:role-any'
```
The token must show `iss=https://sts.windows.net/<tenant>/` (v1), `aud=api://<SNOWFLAKE-APP>`, and
`scp` containing `session:role-any`. Then on Snowflake:
```sql
SELECT SYSTEM$VERIFY_EXTERNAL_OAUTH_TOKEN('<entra_access_token>');  -- expect Passed + the mapped user
```
then the SQL REST API call (`X-Snowflake-Authorization-Token-Type: OAUTH`, body may omit the role)
→ `current_user()` = ANIL_ENTRA, `current_role()` = ORDER_TRIAGE_RO. **Proven live 2026-06-20**
(both omit-role/default and explicit-role paths; read 10 ORDERS rows under the impersonated user).

## Step 6 — The AgentCore OBO broker (PROVEN END-TO-END)

Full chain through AgentCore Identity (no manual Microsoft calls), canonical provider:
```
inbound Entra user token (aud = agent app, carries email/upn)
  → GetWorkloadAccessTokenForJWT(--workload-name <wi> --user-token <inbound>)  → workloadAccessToken
  → GetResourceOauth2Token(--workload-identity-token <wit>
        --resource-credential-provider-name entra-obo            # MicrosoftOauth2 + tenant_id
        --scopes 'api://<snowflake-app>/session:role-any'
        --oauth2-flow ON_BEHALF_OF_TOKEN_EXCHANGE)               → Snowflake-bound token
  → Snowflake SQL REST (token-type OAUTH) → current_user() = the human (ANIL_ENTRA)
```
**With the canonical MicrosoftOauth2 + `tenant_id` provider, NO `--custom-parameters` is needed**
(the vendor adds `requested_token_use=on_behalf_of` itself). Proven via both the standalone broker
CLI test and the deployed agent runtime (Snowflake QUERY_HISTORY → `user=ANIL_ENTRA`).

**How we got here — 5 silent failure modes (the journey to the recipe):**
1. `MicrosoftOauth2` on `hashicorp/aws` v6 has no tenant field → discovery `/common` → `AADSTS500202`
   for the personal/guest admin (works only for managed org members).
2. → fix on **awscc** by setting **`tenant_id`** → tenant-specific discovery (works for all accounts).
   *(Before discovering tenant_id, the interim path was a CustomOauth2 provider with a tenant-specific
   `discoveryUrl` — the documented FALLBACK below.)*
3. CustomOauth2 needs `onBehalfOfTokenExchangeConfig.grantType = JWT_AUTHORIZATION_GRANT` (NOT the
   default `TOKEN_EXCHANGE`/RFC 8693, which Microsoft rejects).
4. CustomOauth2 omits `requested_token_use` → `AADSTS900144` → the agent must inject
   `customParameters={"requested_token_use":"on_behalf_of"}`. **MicrosoftOauth2 + tenant_id does NOT
   need this** — that's the main reason it's canonical.
5. `GetWorkloadAccessTokenForJWT` validates the inbound JWT generically; the workload identity needs no
   JWT-trust config (`create-workload-identity` is just `--name`). Same-app assertion is accepted.
   **Also required:** the runtime role needs `secretsmanager:GetSecretValue` on
   `bedrock-agentcore-identity!*` (the OBO reads the provider secret with the caller's role).

**IaC:** one provider `entra-obo` = `awscc_bedrockagentcore_o_auth_2_credential_provider` with
`microsoft_oauth_2_provider_config { client_id, client_secret, tenant_id }` in `terraform/identity.tf`
(`awscc` in `versions.tf`; `TF_VAR_entra_*` are exported from `../.env` by `scripts/_demo_env.sh`
on `make deploy`, or set by `deploy.yml` in CI). `tenant_id` is awscc-only.

**Gateway seam (no agent code):** the Gateway brokers the OBO itself via the snowflake target's
`grantType=TOKEN_EXCHANGE` egress credential (`terraform/snowflake_lambda.tf`,
`terraform_data.snowflake_obo_egress`): it calls `get_workload_access_token_for_jwt` →
`get_resource_oauth2_token` (oauth2Flow=`ON_BEHALF_OF_TOKEN_EXCHANGE`, **no customParameters** with
the MicrosoftOauth2 provider) and injects the resulting Snowflake-bound token (token-type OAUTH,
role omitted) on the upstream call. The earlier in-agent mint (`identity_obo.user_headers()`, gated
by `OBO_ENABLED`/`OBO_SCOPE`/`OBO_SNOWFLAKE_PROVIDER`/`AGENTCORE_WORKLOAD_NAME`) was removed in the
gateway-only migration — the agent now carries no OBO code.

## Gotchas (verified — each silently breaks the chain)

| Gotcha | Right value |
|---|---|
| Role carrier on the OBO path | delegated scope **`session:role-any`** (or `session:role:<ROLE>`) in `scp`. Snowflake AZURE does **not** parse `session:scope:<ROLE>` → **390317** even with `ANY_ROLE_MODE=ENABLE` |
| User-mapping claim | `('upn','email')` — managed users have `upn`; guest/`live.com` accounts have only `email`/`unique_name`; match is case-insensitive |
| Live read role | **`ORDER_TRIAGE_RO`** (not the test-fixture `AGENT_RO`, which doesn't exist on GA20262) |
| Token mint | auth-code + loopback listener; **device-code fails** (confidential app, AADSTS7000218) |
| Client secret in shell | secret may start with `~` → never `source .env` (tilde-expansion empties it); read via `grep/cut` |
| Snowflake scope mapping | **omit** `EXTERNAL_OAUTH_SCOPE_MAPPING_ATTRIBUTE` for `TYPE=AZURE` |
| Token version | resource app emits **v1** (`requestedAccessTokenVersion=null/1`); issuer `sts.windows.net` |
| Inbound audience | agent app on **v1** (`requestedAccessTokenVersion=null/1`) → `aud` = `api://<agent-app>` → `CUSTOM_JWT allowed_audience` = `api://<agent-app>` (matches gateway.tf/runtime.tf; do NOT set v2/bare-GUID) |
| Consent | admin-consent the agent→resource delegated permission (OBO doesn't prompt) |
| Provider vendor | **MicrosoftOauth2 + `tenant_id`** (canonical) — `tenant_id` → tenant-specific discovery (works for personal accounts) AND the vendor adds `requested_token_use` itself (no custom param). Omitting `tenant_id` = `/common` = AADSTS500202 for personal/guest |
| Terraform provider | `tenant_id` is only on **`awscc`** (`awscc_bedrockagentcore_o_auth_2_credential_provider`, `microsoft_oauth_2_provider_config`). `hashicorp/aws` v6's MicrosoftOauth2 has no tenant field (stuck on `/common`). OBO itself is a runtime flow, not provider config |
| Runtime IAM | runtime role needs `secretsmanager:GetSecretValue` on `bedrock-agentcore-identity!*` — `GetResourceOauth2Token` reads the provider secret with the **caller's** role (else AccessDenied) |
| Snowflake TF provider | `snowflakedb/snowflake` (migrated from `Snowflake-Labs`) if managing the integration in TF |

## References
- Microsoft: OAuth 2.0 on-behalf-of flow (`v2-oauth2-on-behalf-of-flow`); Expose an API / delegated scopes; token version (`requestedAccessTokenVersion`).
- Snowflake: External OAuth + Azure (`oauth-azure`); `CREATE SECURITY INTEGRATION` (External OAuth).
- AWS: AgentCore on-behalf-of token exchange (`GetWorkloadAccessTokenForJWT` → `GetResourceOauth2Token` `ON_BEHALF_OF_TOKEN_EXCHANGE`); `aws_bedrockagentcore_oauth2_credential_provider` (`microsoft_oauth2_provider_config`).
- Internal: [ADR-0001](../adr/0001-user-impersonation-obo.md) (the Cognito spike this supersedes was removed once Entra became the live build).

# Playbook — Snowflake bootstrap (`make snowflake-setup`)

The Snowflake data path (`terraform/snowflake_lambda.tf`): a Lambda signs a key-pair JWT
and queries the Snowflake SQL REST API, reading the RSA private key + connection config
from a Secrets Manager secret (`var.snowflake_secret_name`). This runbook seeds Snowflake
**once, outside Terraform**, and populates that secret.

## What it creates

`snowflake/setup.sql` + `scripts/snowflake_bootstrap.py` create the warehouse / DB /
`ORDERS`+`CUSTOMERS` tables, seed the sample data, create a read-only key-pair service
user, generate + register its RSA key, and store the private key + connection config in
the Secrets Manager secret the Lambda reads. Idempotent / re-runnable.

Config lives in the **single root `bedrock-demo/.env`** (gitignored; copy this repo's
`.env.example` to it — the one config file for all deploy/ops). The recipe sources that
file (`../.env`) — no exports, no per-repo `.env`:

```dotenv
SNOWFLAKE_ACCOUNT=GA20262
SNOWFLAKE_HOST=ga20262.<region>.snowflakecomputing.com   # <account>.<region>...
SNOWFLAKE_ADMIN_USER=SVC_ORDER_TRIAGE_BOOTSTRAP
SNOWFLAKE_ADMIN_AUTH=keypair                             # auth modes below
SNOWFLAKE_ADMIN_PRIVATE_KEY_B64=<inline base64 of the PKCS#8 PEM>
```

```bash
make snowflake-setup                 # full seed + key-pair + secret
make snowflake-setup ARGS=--verify   # read-only check of the live setup
```

## Admin auth modes (`SNOWFLAKE_ADMIN_AUTH`)

- `keypair` — **recommended**, fully headless.
- `password`.
- `externalbrowser` — interactive browser SSO; only on accounts that allow it. **This
  demo's account returns a SAML-IdP error**, so it is not usable here.
- `pat` / `oauth` — token via `SNOWFLAKE_ADMIN_TOKEN_FILE`; a PAT also requires a
  Snowflake **network policy**.

The keypair key is supplied inline as `SNOWFLAKE_ADMIN_PRIVATE_KEY_B64` (single-line
base64 of the PKCS#8 PEM — `.env`-safe) or as a path in `SNOWFLAKE_ADMIN_PRIVATE_KEY`
(b64 wins if both set); add `SNOWFLAKE_ADMIN_PRIVATE_KEY_PASSPHRASE` for an encrypted key.

## Headless setup (no browser) — `make bootstrap-admin`

The seeding needs an ACCOUNTADMIN login, and the *first* such login can't bootstrap
itself. To make every run after that headless:

```bash
make bootstrap-admin    # generates an admin key-pair (snowflake/.keys/, gitignored) and
                        # prints (1) one-time Snowsight SQL and (2) the .env lines to add
```

1. Paste the printed SQL **once** into a Snowsight worksheet as an ACCOUNTADMIN — it
   creates a `TYPE=SERVICE` key-pair user `SVC_ORDER_TRIAGE_BOOTSTRAP`, registers its
   public key, and grants it ACCOUNTADMIN (**Option A** — matches `setup.sql`'s
   `USE ROLE ACCOUNTADMIN`, so no other code changes).
2. Put the printed `SNOWFLAKE_ADMIN_PRIVATE_KEY_B64` in `.env` (already filled if you ran
   `make bootstrap-admin` locally).
3. `make snowflake-setup` is now fully headless, forever.

> **Option B (least privilege):** instead of granting ACCOUNTADMIN, create a custom role
> with only `CREATE WAREHOUSE/DATABASE/ROLE/USER ON ACCOUNT`, grant that to the bootstrap
> user, and change `setup.sql`'s `USE ROLE ACCOUNTADMIN` + the `role` in `run_admin_sql()`
> to that role. A leaked key is then bounded to those objects.

## Security

Under Option A the bootstrap user is a standing key-pair ACCOUNTADMIN — treat
`snowflake/.keys/bootstrap_admin_rsa_key.p8` like a **root credential**; rotate or
`DROP USER` it when the demo is done. `snowflake/.keys/` also holds the read-only
service-user key (`rsa_key.p8`); the live path reads only the Secrets Manager copy, so you
can delete `snowflake/.keys/` once the secret is populated. The `order-triage/snowflake`
secret is encrypted with the default `aws/secretsmanager` KMS key and scoped by IAM only —
use a dedicated CMK / resource policy for anything beyond a demo.

## Overrides

Object/secret names are overridable via env (`SNOWFLAKE_DATABASE`, `SNOWFLAKE_WAREHOUSE`,
`SNOWFLAKE_SECRET_NAME`, …). All generated key-pairs land in `snowflake/.keys/`
(gitignored). On an account that allows interactive browser login you can skip
`bootstrap-admin` and use `SNOWFLAKE_ADMIN_AUTH=externalbrowser`.

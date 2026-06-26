#!/usr/bin/env python3
"""Reproducibly provision the Microsoft Entra apps for the order-triage OBO chain.

An **idempotent** wrapper over the Azure CLI (`az` + `az rest` / Microsoft Graph) that
creates/updates the two app registrations exactly as the proven setup — so the Entra
half of the OBO chain is reproducible in any tenant, with no portal clicking.

Manual prerequisites (privileged / interactive — NOT done here):
  * an Entra tenant + `az login --tenant <id>` as an admin who can create app
    registrations AND grant admin consent (Application Administrator / Global Admin);
  * demo USERS + their MFA enrolment, and the matching Snowflake users (see test_user.sql).

What it provisions:
  RESOURCE app (order-triage-snowflake): `api://<id>`, **v1 access tokens**
      (requestedAccessTokenVersion=null → iss=sts.windows.net, required by Snowflake
      EXTERNAL_OAUTH_TYPE=AZURE), exposes the `session:role-any` scope (Admin consent),
      and PRE-AUTHORIZES the agent app for it (no consent prompt at OBO time).
  AGENT app (order-triage-agent): `api://<id>`, redirect `http://localhost:8000/callback`,
      exposes `access_as_user`, delegated perms = the resource scope + Graph `User.Read`,
      a client secret, and admin consent granted.

Scope constraint: Snowflake's AZURE handler can't parse `session:scope:<ROLE>`
(error 390317); the role carrier must be `session:role-any` (or `session:role:<ROLE>`).

Outputs the resulting IDs (+ a freshly-created secret) as `.env` lines; `--write-env`
updates `bedrock-demo/.env` in place (only writing the secret when it just created one).

Usage:
  python scripts/entra_provision.py [--dry-run] [--write-env]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

# ── Config (override via env) ────────────────────────────────────────────────
RESOURCE_NAME = os.environ.get("ENTRA_RESOURCE_APP_NAME", "order-triage-snowflake")
AGENT_NAME = os.environ.get("ENTRA_AGENT_APP_NAME", "order-triage-agent")
OBO_SCOPE_VALUE = os.environ.get("ENTRA_OBO_SCOPE_VALUE", "session:role-any")
AGENT_SCOPE_VALUE = os.environ.get("ENTRA_AGENT_SCOPE_VALUE", "access_as_user")
REDIRECT_URIS = [
    u.strip()
    for u in os.environ.get(
        "ENTRA_REDIRECT_URIS", "http://localhost:8000/callback,http://localhost:8400"
    ).split(",")
    if u.strip()
]
SECRET_NAME = os.environ.get("ENTRA_SECRET_NAME", "obo-agent-secret")
SECRET_YEARS = os.environ.get("ENTRA_SECRET_YEARS", "2")
SIGN_IN_AUDIENCE = "AzureADMyOrg"  # single tenant

GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"
GRAPH_USER_READ_ID = "e1fe6dd8-ba31-4d61-89e7-88639da4683d"  # well-known, constant across tenants
GRAPH_ROOT = "https://graph.microsoft.com/v1.0"

DRY_RUN = False


# ── az helpers ───────────────────────────────────────────────────────────────
def az(*args: str, parse: bool = True, mutating: bool = False):
    """Run an `az` command. Read calls always run; mutating calls are skipped on --dry-run."""
    if mutating and DRY_RUN:
        print(f"  [dry-run] az {' '.join(args)}")
        return None
    proc = subprocess.run(["az", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"az {' '.join(args)} failed:\n{proc.stderr.strip()}")
    out = proc.stdout.strip()
    if not parse or not out:
        return out
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out


def graph_patch(object_id: str, body: dict, what: str) -> None:
    """PATCH /applications/{id} via `az rest` (Graph)."""
    if DRY_RUN:
        print(f"  [dry-run] PATCH applications/{object_id} ({what}): {json.dumps(body)}")
        return
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(body, fh)
        path = fh.name
    try:
        az(
            "rest", "--method", "PATCH",
            "--uri", f"{GRAPH_ROOT}/applications/{object_id}",
            "--headers", "Content-Type=application/json",
            "--body", f"@{path}",
            parse=False, mutating=True,
        )
    finally:
        os.unlink(path)
    print(f"  patched {what}")


# ── app helpers ──────────────────────────────────────────────────────────────
def find_app(display_name: str) -> dict | None:
    apps = az("ad", "app", "list", "--filter", f"displayName eq '{display_name}'", "--query",
              "[].{appId:appId, id:id, displayName:displayName}", "-o", "json") or []
    for a in apps:
        if a.get("displayName") == display_name:
            return a
    return None


def ensure_app(display_name: str) -> dict:
    existing = find_app(display_name)
    if existing:
        print(f"  app '{display_name}' exists (appId={existing['appId']})")
        return existing
    print(f"  creating app '{display_name}' …")
    if DRY_RUN:
        return {"appId": "<new-appId>", "id": "<new-objectId>", "displayName": display_name}
    created = az("ad", "app", "create", "--display-name", display_name,
                 "--sign-in-audience", SIGN_IN_AUDIENCE, "-o", "json", mutating=True)
    return {"appId": created["appId"], "id": created["id"], "displayName": display_name}


def existing_scope_id(app_obj_id: str, value: str) -> str:
    """Reuse an existing scope's GUID (so re-runs don't churn grants); else mint one."""
    if app_obj_id.startswith("<"):  # dry-run placeholder
        return str(uuid.uuid4())
    app = az("ad", "app", "show", "--id", app_obj_id, "-o", "json")
    for s in (app.get("api") or {}).get("oauth2PermissionScopes") or []:
        if s.get("value") == value:
            return s["id"]
    return str(uuid.uuid4())


def ensure_sp(app_id: str) -> None:
    if DRY_RUN:
        print(f"  [dry-run] ensure service principal for {app_id}")
        return
    sps = az("ad", "sp", "list", "--filter", f"appId eq '{app_id}'", "--query", "[].id", "-o", "json") or []
    if sps:
        print(f"  service principal exists for {app_id}")
        return
    az("ad", "sp", "create", "--id", app_id, "-o", "none", parse=False, mutating=True)
    print(f"  created service principal for {app_id}")


def ensure_secret(agent_app_id: str, agent_obj_id: str) -> str | None:
    """Create the client secret only if one with SECRET_NAME doesn't exist. Returns the
    new secret value (shown once) or None when an existing one is kept."""
    if not agent_obj_id.startswith("<"):
        app = az("ad", "app", "show", "--id", agent_obj_id, "-o", "json")
        for c in app.get("passwordCredentials") or []:
            if c.get("displayName") == SECRET_NAME:
                print(f"  client secret '{SECRET_NAME}' already exists — keeping it "
                      f"(expires {c.get('endDateTime')}); ENTRA_AGENT_CLIENT_SECRET unchanged")
                return None
    if DRY_RUN:
        print(f"  [dry-run] az ad app credential reset (create secret '{SECRET_NAME}')")
        return None
    res = az("ad", "app", "credential", "reset", "--id", agent_app_id, "--append",
             "--display-name", SECRET_NAME, "--years", SECRET_YEARS, "-o", "json", mutating=True)
    print(f"  created client secret '{SECRET_NAME}' (shown once)")
    return res.get("password")


def configure_resource(obj_id: str, res_uri: str, desired_scopes: list[dict], desired_preauth: list[dict]) -> None:
    """Set the resource app's identifier URI, v1 tokens, exposed scope(s) and pre-authorized
    clients.

    Microsoft Graph refuses to delete/modify an ENABLED oauth2PermissionScope in one shot
    (error CannotDeleteOrUpdateEnabledEntitlement). So if any *current* scope is being
    removed, we first PATCH it **disabled** while moving preAuth to the desired set
    (Phase 1), then PATCH the final scope set (Phase 2). Graph PATCH replaces the whole
    `api` complex object, so each PATCH sends it in full.
    """
    graph_patch(obj_id, {"identifierUris": [res_uri]}, "resource identifierUris")
    desired_ids = {s["id"] for s in desired_scopes}
    if not DRY_RUN and not obj_id.startswith("<"):
        app = az("ad", "app", "show", "--id", obj_id, "-o", "json")
        current = (app.get("api") or {}).get("oauth2PermissionScopes") or []
        if any(s["id"] not in desired_ids and s.get("isEnabled") for s in current):
            phase1 = [({**s, "isEnabled": False} if s["id"] not in desired_ids else s) for s in current]
            graph_patch(obj_id, {"api": {"requestedAccessTokenVersion": None,
                                         "oauth2PermissionScopes": phase1,
                                         "preAuthorizedApplications": desired_preauth}},
                        "disable removed scope(s) [phase 1]")
    graph_patch(obj_id, {"api": {"requestedAccessTokenVersion": None,
                                 "oauth2PermissionScopes": desired_scopes,
                                 "preAuthorizedApplications": desired_preauth}},
                "resource api: v1 + scope + preauth [phase 2]")


def scope_def(scope_id: str, value: str, admin_only: bool) -> dict:
    consent = "Admin" if admin_only else "User"
    d = {
        "id": scope_id, "value": value, "type": consent, "isEnabled": True,
        "adminConsentDisplayName": value, "adminConsentDescription": f"OBO scope: {value}",
    }
    if not admin_only:
        d["userConsentDisplayName"] = value
        d["userConsentDescription"] = f"Allow the app to act as you ({value})."
    return d


# ── .env emission ────────────────────────────────────────────────────────────
def env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"  # bedrock-demo/.env


def write_env(updates: dict[str, str]) -> None:
    path = env_path()
    lines = path.read_text().splitlines() if path.exists() else []
    keys = {k: i for i, ln in enumerate(lines) for k in [ln.split("=", 1)[0]] if "=" in ln}
    for k, v in updates.items():
        if k in keys:
            lines[keys[k]] = f"{k}={v}"
        else:
            lines.append(f"{k}={v}")
    path.write_text("\n".join(lines) + "\n")
    print(f"  updated {path} ({', '.join(updates)})")


def main() -> int:
    global DRY_RUN
    ap = argparse.ArgumentParser(description="Provision the Entra OBO apps via az CLI (idempotent).")
    ap.add_argument("--dry-run", action="store_true", help="show planned actions; mutate nothing")
    ap.add_argument("--write-env", action="store_true", help="write the resulting IDs/secret into bedrock-demo/.env")
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    acct = az("account", "show", "-o", "json")
    tenant = acct["tenantId"]
    print(f"tenant: {tenant}  signed in as: {acct['user']['name']}{'  [DRY-RUN]' if DRY_RUN else ''}\n")

    # 1) Apps must both exist before we can cross-reference them (preAuth / requiredResourceAccess).
    print(f"== resource app ({RESOURCE_NAME}) ==")
    res = ensure_app(RESOURCE_NAME)
    print(f"\n== agent app ({AGENT_NAME}) ==")
    agent = ensure_app(AGENT_NAME)

    res_uri = f"api://{res['appId']}"
    agent_uri = f"api://{agent['appId']}"
    obo_scope_id = existing_scope_id(res["id"], OBO_SCOPE_VALUE)
    agent_scope_id = existing_scope_id(agent["id"], AGENT_SCOPE_VALUE)

    # 2) Resource app: identifier URI + v1 tokens + the OBO scope + pre-authorize the agent.
    #    (disable-then-set, so removing a current scope doesn't trip Graph's
    #    "cannot delete an enabled entitlement" guard.)
    print(f"\n== configure resource app ==")
    configure_resource(
        res["id"], res_uri,
        desired_scopes=[scope_def(obo_scope_id, OBO_SCOPE_VALUE, admin_only=True)],
        desired_preauth=[{"appId": agent["appId"], "delegatedPermissionIds": [obo_scope_id]}],
    )

    # 3) Agent app: URI + redirect URIs + access_as_user + delegated perms (resource scope + Graph).
    print(f"\n== configure agent app ==")
    graph_patch(agent["id"], {
        "identifierUris": [agent_uri],
        "web": {"redirectUris": REDIRECT_URIS},
        "api": {
            "requestedAccessTokenVersion": None,
            "oauth2PermissionScopes": [scope_def(agent_scope_id, AGENT_SCOPE_VALUE, admin_only=False)],
        },
        "requiredResourceAccess": [
            {"resourceAppId": res["appId"], "resourceAccess": [{"id": obo_scope_id, "type": "Scope"}]},
            {"resourceAppId": GRAPH_APP_ID, "resourceAccess": [{"id": GRAPH_USER_READ_ID, "type": "Scope"}]},
        ],
    }, "agent app (uri/redirect/scope/perms)")

    # 4) Service principals (needed for consent + token issuance).
    print(f"\n== service principals ==")
    ensure_sp(res["appId"])
    ensure_sp(agent["appId"])

    # 5) Client secret (only if missing).
    print(f"\n== agent client secret ==")
    secret = ensure_secret(agent["appId"], agent["id"])

    # 6) Admin consent for the agent's delegated permissions (resource scope + Graph User.Read).
    print(f"\n== admin consent ==")
    az("ad", "app", "permission", "admin-consent", "--id", agent["appId"],
       parse=False, mutating=True)
    print("  admin consent granted" if not DRY_RUN else "  [dry-run] admin-consent")

    # 7) Emit .env lines.
    updates = {
        "ENTRA_TENANT_ID": tenant,
        "ENTRA_RESOURCE_APP_ID": res["appId"],
        "ENTRA_RESOURCE_AUDIENCE": res_uri,
        "ENTRA_AGENT_APP_ID": agent["appId"],
        "ENTRA_AGENT_AUDIENCE": agent_uri,
        "ENTRA_AGENT_SCOPE": f"{agent_uri}/{AGENT_SCOPE_VALUE}",
        "ENTRA_OBO_SCOPE": f"{res_uri}/{OBO_SCOPE_VALUE}",
        "ENTRA_TOKEN_ENDPOINT": f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
    }
    if secret:
        updates["ENTRA_AGENT_CLIENT_SECRET"] = secret

    print("\n== resulting .env values ==")
    for k, v in updates.items():
        print(f"{k}={'<secret, shown once>' if k == 'ENTRA_AGENT_CLIENT_SECRET' else v}")
    if secret:
        print(f"\n(client secret value — store it now, it cannot be retrieved again:)\nENTRA_AGENT_CLIENT_SECRET={secret}")

    if args.write_env and not DRY_RUN:
        print()
        write_env(updates)

    print("\nEntra provisioning complete." + ("  (dry-run — nothing changed)" if DRY_RUN else ""))
    print("Next: `make snowflake-obo` (Snowflake AZURE integration) + create users (manual, MFA).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

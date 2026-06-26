"""Shared helpers for the provisioning scripts.

Terraform (`infra/terraform/`) owns resource provisioning. The Python pieces are
the read-only **preflight** (a deploy-role access check) and the **Registry**
registration (no Terraform resource exists for it).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

REPO_ROOT = Path(__file__).resolve().parents[1]
REGION = os.getenv("AWS_REGION", "us-west-2")


def log(msg: str) -> None:
    print(f"[deploy] {msg}", flush=True)


def client(service: str):
    return boto3.client(service, region_name=REGION)


# --- preflight ----------------------------------------------------------------


@dataclass
class Preflight:
    identity: dict
    region: str
    blocked: list[str] = field(default_factory=list)
    scp_policy: str | None = None

    @property
    def ok(self) -> bool:
        return not self.blocked


def _is_scp_deny(err: ClientError) -> str | None:
    msg = str(err)
    if "service control policy" in msg:
        for token in msg.split():
            if "service_control_policy" in token or token.startswith("p-"):
                return token.rstrip(".")
        return "service control policy"
    return None


def preflight() -> Preflight:
    """Read-only access check. Returns which services are denied + the SCP id."""
    try:
        identity = client("sts").get_caller_identity()
    except Exception as exc:
        log(f"FATAL: cannot call STS — are AWS creds in .env? ({exc})")
        sys.exit(2)

    pf = Preflight(identity=identity, region=REGION)
    # Probe a read-only action the deploy role ACTUALLY holds and the apply uses, so an
    # AccessDenied here means the org SCP denies the service family — not a gap in the
    # deploy role's least-privilege IAM policy. Tuple is (label, boto3-client, call):
    # bedrock:ListKnowledgeBases is granted in bootstrap/github_oidc.tf and exercised by the
    # KB resources — its client is the "bedrock-agent" control plane, not "bedrock".
    probes = [
        ("bedrock", "bedrock-agent", lambda c: c.list_knowledge_bases()),
        ("bedrock-agentcore", "bedrock-agentcore-control", lambda c: c.list_gateways()),
    ]
    for label, svc, call in probes:
        try:
            call(client(svc))
        except ClientError as exc:
            scp = _is_scp_deny(exc)
            if scp:
                pf.blocked.append(label)
                pf.scp_policy = scp
            elif exc.response["Error"]["Code"] in {"AccessDeniedException", "AccessDenied"}:
                pf.blocked.append(label)
        except Exception:
            pf.blocked.append(label)
    return pf


def print_preflight(pf: Preflight) -> None:
    log(f"identity: {pf.identity.get('Arn')}")
    log(f"account:  {pf.identity.get('Account')}   region: {pf.region}")
    if pf.ok:
        log("access OK — bedrock + bedrock-agentcore reachable. `make deploy` can run.")
    else:
        log(f"BLOCKED services: {', '.join(pf.blocked)}")
        if pf.scp_policy:
            log(f"cause: explicit deny in SCP {pf.scp_policy}")
        log("Deploy blocked: deploy role can't reach the service(s) above (SCP deny or missing IAM) — see docs/playbooks/cd-setup.md.")


def require_access() -> Preflight:
    pf = preflight()
    print_preflight(pf)
    if not pf.ok:
        sys.exit(2)
    return pf

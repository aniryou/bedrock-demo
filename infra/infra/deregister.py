"""AgentCore **Registry** teardown — the destroy-time counterpart to `register.py`.

Registry has no Terraform resource, so `terraform destroy` cannot remove it and a
redeploy would otherwise leak a fresh one. This script deletes every registry
matching the manifest name (its records first), so destroy/replace leaves nothing
behind. Invoked by the `when = destroy` provisioner in `infra/terraform/registry.tf`
(and runnable standalone). Fail-soft throughout — a teardown hiccup never blocks
`terraform destroy`.
"""

from __future__ import annotations

import json
import time

from ._common import REPO_ROOT, client, log


def _wait_out_of_creating(ctl, reg_id: str, attempts: int = 12, delay: int = 5) -> None:
    """A registry mid-CREATING rejects record listing and deletion; wait it out."""
    for _ in range(attempts):
        try:
            if ctl.get_registry(registryId=reg_id).get("status") != "CREATING":
                return
        except Exception:
            return
        time.sleep(delay)


def _registry_ids(ctl, name: str) -> list[str]:
    ids: list[str] = []
    token = None
    while True:
        resp = ctl.list_registries(**({"nextToken": token} if token else {}))
        for r in resp.get("registries", resp.get("registrySummaries", [])):
            if r.get("name") == name:
                ids.append(r.get("registryId") or r.get("id"))
        token = resp.get("nextToken")
        if not token:
            return ids


def main() -> None:
    ctl = client("bedrock-agentcore-control")
    name = json.loads((REPO_ROOT / "registry" / "manifest.json").read_text())["registry"]["name"]

    ids = _registry_ids(ctl, name)
    if not ids:
        log(f"registry: none named {name!r} — nothing to deregister")
        return

    for reg_id in ids:
        try:
            _wait_out_of_creating(ctl, reg_id)
            recs = ctl.list_registry_records(registryId=reg_id)
            for rec in recs.get("registryRecords", recs.get("records", [])):
                rec_id = rec.get("recordId") or rec.get("id")
                try:
                    ctl.delete_registry_record(registryId=reg_id, recordId=rec_id)
                except Exception:
                    pass
            ctl.delete_registry(registryId=reg_id)
            log(f"deregistered: {reg_id}")
        except Exception as exc:
            log(f"(delete_registry skipped for {reg_id}: {exc})")


if __name__ == "__main__":
    main()

"""AgentCore **Registry** — register the agent, tools, and skills.

Registry has no Terraform resource (in either the aws or awscc provider), so this
script is invoked by `infra/terraform/registry.tf` (and the CI deploy job) after
`terraform apply`. Reads `registry/manifest.json`, creates one record per
agent / tools / skills entry, and submits each for approval. Each step is
fail-soft so a shape/availability issue never blocks the deploy.
"""

from __future__ import annotations

import json

from ._common import REPO_ROOT, client, log


def _descriptors(record: dict) -> dict:
    dt = record["descriptorType"]
    if dt == "MCP":
        tools = [{"name": t} for t in record.get("tools", [])]
        return {"mcp": {"tools": {"inlineContent": json.dumps({"tools": tools})}}}
    if dt == "AgentSkills":
        return {"agentSkills": {"inlineContent": json.dumps({"skills": record.get("skills", [])})}}
    return {"a2a": {"inlineContent": json.dumps({"name": record["name"], "summary": record.get("summary", "")})}}


def _find_registry(ctl, name: str) -> str | None:
    """Return the id of an existing registry with this name, or None.

    The control API allows duplicate names and mints a fresh id per call, so we
    must look up by name ourselves to stay idempotent across redeploys.
    """
    token = None
    while True:
        resp = ctl.list_registries(**({"nextToken": token} if token else {}))
        for r in resp.get("registries", resp.get("registrySummaries", [])):
            if r.get("name") == name:
                return r.get("registryId") or r.get("id")
        token = resp.get("nextToken")
        if not token:
            return None


def main() -> None:
    ctl = client("bedrock-agentcore-control")
    manifest = json.loads((REPO_ROOT / "registry" / "manifest.json").read_text())
    name = manifest["registry"]["name"]

    reg_id = _find_registry(ctl, name)
    if reg_id:
        log(f"registry: {reg_id} (reused existing)")
    else:
        try:
            resp = ctl.create_registry(
                name=name,
                description=manifest["registry"]["description"],
            )
            # CreateRegistry returns only registryArn; the id is its last path segment.
            reg_arn = resp.get("registryArn") or resp.get("registry", {}).get("registryArn", "")
            reg_id = reg_arn.rsplit("/", 1)[-1] if reg_arn else _find_registry(ctl, name)
            log(f"registry: {reg_id} (created)")
        except Exception as exc:
            log(f"(create_registry skipped — unavailable: {exc})")
            return

    for rec in manifest["records"]:
        try:
            r = ctl.create_registry_record(
                registryId=reg_id,
                name=rec["name"],
                descriptorType=rec["descriptorType"],
                descriptors=_descriptors(rec),
                recordVersion="1.0",
            )
            rec_id = r.get("recordId") or r.get("registryRecord", {}).get("recordId")
            try:
                ctl.submit_registry_record_for_approval(registryId=reg_id, recordId=rec_id)
            except Exception:
                pass
            log(f"registered + submitted: {rec['name']}")
        except Exception as exc:
            log(f"(record {rec['name']} skipped: {exc})")


if __name__ == "__main__":
    main()

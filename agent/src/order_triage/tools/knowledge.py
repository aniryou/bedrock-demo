"""Knowledge Bases tool — Amazon Bedrock Knowledge Base retrieval.

`search_policies` queries the Bedrock Knowledge Base via the `bedrock-agent-runtime`
`retrieve` API. `KNOWLEDGE_BASE_ID` is required (no local fallback).
"""

from __future__ import annotations

from strands import tool

from ..config import get_config


def _kb_retrieve(query: str, k: int = 3) -> str:
    import boto3

    cfg = get_config()
    client = boto3.client("bedrock-agent-runtime", region_name=cfg.aws_region)
    resp = client.retrieve(
        knowledgeBaseId=cfg.knowledge_base_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": k}},
    )
    results = resp.get("retrievalResults", [])
    if not results:
        return "No relevant policy found."
    out = []
    for r in results:
        text = r.get("content", {}).get("text", "")
        source = r.get("location", {}).get("s3Location", {}).get("uri", "kb")
        out.append(f"[{source}]\n{text}")
    return "\n\n".join(out)


@tool
def search_policies(query: str) -> str:
    """Search the order/credit/dispute policy knowledge base for relevant rules.

    Use this to ground decisions in policy (review thresholds, credit-hold rules,
    dispute handling) and cite the policy you relied on.
    """
    return _kb_retrieve(query)

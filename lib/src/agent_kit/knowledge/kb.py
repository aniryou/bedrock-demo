"""Knowledge Bases tool — Amazon Bedrock Knowledge Base retrieval.

`_kb_retrieve` queries the Bedrock Knowledge Base via the `bedrock-agent-runtime`
`retrieve` API. `KNOWLEDGE_BASE_ID` is required (no local fallback). `make_kb_tool` wraps
it in a strands `@tool` whose name and docstring are supplied per-agent.
"""

from __future__ import annotations

from strands import tool

from agent_kit.config import get_config


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


def make_kb_tool(name: str, description: str):
    """Build a strands @tool with the given name and docstring that wraps _kb_retrieve.

    strands derives the tool name from the function `__name__` and the description from
    `__doc__`, so the wrapper's identity is set before decoration. The returned object
    exposes `.tool_name == name`.
    """

    def _kb(query: str) -> str:
        return _kb_retrieve(query)

    _kb.__name__ = name
    _kb.__doc__ = description
    return tool(_kb)

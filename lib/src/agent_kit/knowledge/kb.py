"""Knowledge Bases tool — Amazon Bedrock Knowledge Base retrieval.

`_kb_retrieve` queries the Bedrock Knowledge Base via the `bedrock-agent-runtime`
`retrieve` API against an explicit knowledge-base id and region. `make_kb_tool` wraps it in
a strands `@tool` whose name and docstring are supplied per-agent.
"""

from __future__ import annotations

from strands import tool


def _kb_retrieve(query: str, knowledge_base_id: str, region: str, k: int = 3) -> str:
    import boto3

    client = boto3.client("bedrock-agent-runtime", region_name=region)
    resp = client.retrieve(
        knowledgeBaseId=knowledge_base_id,
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


def make_kb_tool(name: str, description: str, knowledge_base_id: str, region: str = "us-west-2"):
    """Build a strands @tool with the given name and docstring that wraps _kb_retrieve.

    strands derives the tool name from the function `__name__` and the description from
    `__doc__`, so the wrapper's identity is set before decoration. The returned object
    exposes `.tool_name == name`.
    """

    def _kb(query: str) -> str:
        return _kb_retrieve(query, knowledge_base_id, region)

    _kb.__name__ = name
    _kb.__doc__ = description
    return tool(_kb)

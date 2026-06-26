locals {
  account_id = data.aws_caller_identity.current.account_id

  # --- naming regimes (the repo deliberately uses BOTH) ----------------------
  # AgentCore APIs require UNDERSCORED names; var.name_prefix is hyphenated.
  # Use this for agent_runtime_name / memory_name / policy-engine name.
  name_prefix_us = replace(var.name_prefix, "-", "_") # order-triage -> order_triage

  # Knowledge Base + S3 Vectors index name (hyphenated, like IAM/S3).
  kb_name = "${var.name_prefix}-policies"

  # Embedding model ARN for the Knowledge Base. Dimension lives in var.embedding_dimension.
  embedding_model_arn = "arn:aws:bedrock:${var.region}::foundation-model/${var.embedding_model_id}"

  # AgentCore resource names (underscored where the API requires it).
  memory_name = "${local.name_prefix_us}_memory"
}

# Built-in tool: Knowledge Bases. The policy docs are published to the artifacts
# bucket (kb/ prefix) by order-triage-agent CI; the KB ingests from there. The
# vector store (S3 Vectors) is infra-owned.

resource "aws_s3vectors_vector_bucket" "kb" {
  vector_bucket_name = "${var.name_prefix}-kb-vectors-${local.account_id}"
}

resource "aws_s3vectors_index" "kb" {
  vector_bucket_name = aws_s3vectors_vector_bucket.kb.vector_bucket_name
  index_name         = local.kb_name
  data_type          = "float32"
  dimension          = var.embedding_dimension # must match var.embedding_model_id's output width
  distance_metric    = "cosine"
}

resource "aws_bedrockagent_knowledge_base" "this" {
  name     = local.kb_name
  role_arn = aws_iam_role.kb.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = local.embedding_model_arn
    }
  }

  storage_configuration {
    type = "S3_VECTORS"
    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.kb.index_arn
    }
  }
}

resource "aws_bedrockagent_data_source" "kb" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.this.id
  name              = "policy-docs"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn         = "arn:aws:s3:::${var.artifacts_bucket}"
      inclusion_prefixes = ["kb/"]
    }
  }
}

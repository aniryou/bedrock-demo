# AgentCore Memory: short-term events + three long-term strategies.

resource "aws_bedrockagentcore_memory" "this" {
  name                      = local.memory_name
  description               = "Order-triage agent memory (short-term events + long-term strategies)"
  event_expiry_duration     = var.memory_event_expiry_days # days of raw short-term event retention
  memory_execution_role_arn = aws_iam_role.memory.arn
}

resource "aws_bedrockagentcore_memory_strategy" "semantic" {
  memory_id  = aws_bedrockagentcore_memory.this.id
  name       = "facts"
  type       = "SEMANTIC"
  namespaces = ["/facts/{actorId}"]
}

resource "aws_bedrockagentcore_memory_strategy" "summary" {
  memory_id  = aws_bedrockagentcore_memory.this.id
  name       = "summaries"
  type       = "SUMMARIZATION"
  namespaces = ["/summaries/{actorId}/{sessionId}"]
}

resource "aws_bedrockagentcore_memory_strategy" "preferences" {
  memory_id  = aws_bedrockagentcore_memory.this.id
  name       = "preferences"
  type       = "USER_PREFERENCE"
  namespaces = ["/preferences/{actorId}"]
}

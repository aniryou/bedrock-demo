output "memory_log_group_name" {
  value       = aws_cloudwatch_log_group.memory.name
  description = "CloudWatch Logs group receiving AgentCore Memory APPLICATION_LOGS."
}

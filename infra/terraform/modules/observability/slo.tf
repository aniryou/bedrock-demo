# Application Signals SLOs, created via the AWS CLI in a terraform_data local-exec.
# Why not a resource: hashicorp/aws has none (issue #39555), and the awscc resource
# self-collides on create (its Cloud Control create+stabilize re-issues the create within a
# single apply). The SLI uses the metric_data_queries form against concrete vended metrics —
# the KeyAttributes/service form does not resolve for an SLO. The CLI request shape is
# SliConfig.SliMetricConfig (not the awscc Sli.SliMetric names). Needs the deploy role's
# application-signals:* + cloudwatch:GetMetricData.

locals {
  _slo_dims = [
    { Name = "Name", Value = local.runtime_name_dim },
    { Name = "Operation", Value = "InvokeAgentRuntime" },
    { Name = "Resource", Value = local.runtime_arn },
  ]

  # Latency SLO: 99% of 1-min periods with runtime p99 latency <= 5s, rolling 7 days.
  slo_latency_sli = jsonencode({
    SliMetricConfig = {
      MetricDataQueries = [{
        Id         = "lat"
        ReturnData = true
        MetricStat = { Period = 60, Stat = "p99", Metric = { Namespace = local.ns_vended, MetricName = "Latency", Dimensions = local._slo_dims } }
      }]
    }
    MetricThreshold    = 5000
    ComparisonOperator = "LessThanOrEqualTo"
  })

  # Availability SLO: 99% of 1-min periods system-error-free, rolling 7 days.
  slo_avail_sli = jsonencode({
    SliMetricConfig = {
      MetricDataQueries = [{
        Id         = "err"
        ReturnData = true
        MetricStat = { Period = 60, Stat = "Sum", Metric = { Namespace = local.ns_vended, MetricName = "SystemErrors", Dimensions = local._slo_dims } }
      }]
    }
    MetricThreshold    = 0
    ComparisonOperator = "LessThanOrEqualTo"
  })

  slo_goal = jsonencode({
    Interval         = { RollingInterval = { Duration = 7, DurationUnit = "DAY" } }
    AttainmentGoal   = 99
    WarningThreshold = 50
  })
}

resource "terraform_data" "slo_latency" {
  input            = { region = var.region, name = "${var.name_prefix}-latency-slo" }
  triggers_replace = [local.slo_latency_sli, local.slo_goal]

  provisioner "local-exec" {
    command = "aws application-signals create-service-level-objective --region ${var.region} --name ${var.name_prefix}-latency-slo --description 'order-triage runtime p99 latency <= 5s (99%, rolling 7d)' --sli '${local.slo_latency_sli}' --goal '${local.slo_goal}' || aws application-signals update-service-level-objective --region ${var.region} --id ${var.name_prefix}-latency-slo --sli '${local.slo_latency_sli}' --goal '${local.slo_goal}'"
  }
  provisioner "local-exec" {
    when    = destroy
    command = "aws application-signals delete-service-level-objective --region ${self.input.region} --id ${self.input.name} || true"
  }
}

resource "terraform_data" "slo_availability" {
  input            = { region = var.region, name = "${var.name_prefix}-availability-slo" }
  triggers_replace = [local.slo_avail_sli, local.slo_goal]

  provisioner "local-exec" {
    command = "aws application-signals create-service-level-objective --region ${var.region} --name ${var.name_prefix}-availability-slo --description 'order-triage runtime system-error-free (99%, rolling 7d)' --sli '${local.slo_avail_sli}' --goal '${local.slo_goal}' || aws application-signals update-service-level-objective --region ${var.region} --id ${var.name_prefix}-availability-slo --sli '${local.slo_avail_sli}' --goal '${local.slo_goal}'"
  }
  provisioner "local-exec" {
    when    = destroy
    command = "aws application-signals delete-service-level-objective --region ${self.input.region} --id ${self.input.name} || true"
  }
}

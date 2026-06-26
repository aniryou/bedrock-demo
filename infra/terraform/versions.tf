terraform {
  required_version = ">= 1.10" # use_lockfile (S3-native state locking) is GA from 1.10
  required_providers {
    aws = {
      source = "hashicorp/aws"
      # >= 6.21 for the XRAY log-delivery-destination type (memory tracing, observability.tf);
      # native AgentCore resources land in aws v6.x, so stay within the 6 major.
      version = "~> 6.21"
    }
    awscc = {
      source  = "hashicorp/awscc"
      version = "~> 1.0" # Cloud Control; expresses the CustomOauth2 OBO config aws v6 can't
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12" # time_sleep absorbs AgentCore cold-start eventual-consistency races
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4" # zips the actor-resolver custom-widget Lambda (observability module)
    }
  }

  # Remote state in S3. bucket/region are supplied at init via -backend-config
  # (the bucket name is account-scoped). Locking is S3-native (use_lockfile) — no
  # DynamoDB table needed. Survives a re-clone — state is never local.
  backend "s3" {
    key          = "order-triage/main.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

# Credentials come from the environment (the .env AWS_* vars). Region is a var.
provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "${var.name_prefix}-agent"
      ManagedBy = "terraform"
    }
  }
}

provider "awscc" {
  region = var.region
}

data "aws_caller_identity" "current" {}

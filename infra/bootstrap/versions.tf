terraform {
  required_version = ">= 1.10" # use_lockfile (S3-native state locking) is GA from 1.10
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Remote state in S3. bucket/region are supplied at init via -backend-config
  # (the bucket name is account-scoped). Locking is S3-native (use_lockfile) — no
  # DynamoDB table needed. Survives a re-clone — state is never local.
  backend "s3" {
    key          = "order-triage/bootstrap.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "${var.name_prefix}-agent"
      ManagedBy = "terraform"
    }
  }
}

variable "region" {
  type    = string
  default = "us-west-2"
}

variable "name_prefix" {
  type    = string
  default = "order-triage"
}

data "aws_caller_identity" "current" {}

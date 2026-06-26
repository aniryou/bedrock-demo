"""AWS Lambda entrypoint for the dummy SAP API (deploy path).

The bedrock-demo-infra repo deploys this behind a Lambda Function URL (its Terraform
references the zip built by `build_lambdas.sh`) so the AgentCore Gateway can reach it.
Locally you don't need this — use `make sap`. `mangum` (the ASGI-to-Lambda adapter) is a
core dependency and is bundled into the Lambda zip by `build_lambdas.sh`.
"""

from __future__ import annotations

from mangum import Mangum

from .app import app

handler = Mangum(app)

"""Provisioning helpers.

Resource provisioning lives in Terraform (`infra/terraform/`). The Python pieces are
the read-only **preflight** (`infra.preflight`, a deploy-role access check) and the
**Registry** registration (`infra.register`, no Terraform resource exists for it —
invoked by `infra/terraform/registry.tf` and the CI deploy job).
"""

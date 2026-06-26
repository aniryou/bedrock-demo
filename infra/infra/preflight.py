"""`python -m infra.preflight` — read-only AWS access check (wired to `make preflight`).

Confirms the deploy role can reach bedrock / bedrock-agentcore before `make deploy`
applies.
"""

from __future__ import annotations

from ._common import require_access

if __name__ == "__main__":
    require_access()

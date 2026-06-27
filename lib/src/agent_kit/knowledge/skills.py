"""Skill tool — load a named skill's full playbook on demand.

A local tool (the skill manifests are fetched into SKILLS_DIR); it never traverses the
Gateway.
"""

from __future__ import annotations

from strands import tool

from agent_kit.knowledge.skill_loader import skill_loader


@tool
def load_skill(name: str) -> str:
    """Load the full playbook (markdown) for one of the agent's named skills."""
    skill = skill_loader.get_skill(name)
    if skill is None:
        return f"No skill named {name!r}. Available:\n{skill_loader.skills_catalog()}"
    return skill.body

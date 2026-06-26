"""Skill loader — reads ontology-bound skill manifests fetched from the
order-triage-knowledge repo.

Each skill is a `*.skill.md` file: YAML frontmatter (the ontology binding — `apiName`,
`description`, `appliesTo`, …) followed by the markdown procedure body. The loader reads
the frontmatter to render an enriched catalog into the system prompt (name, description,
and the ontology entities/actions the skill governs) and returns the body on demand via
the `load_skill` tool. Plain `.md` files with a leading `>` description are also
supported. The loader degrades gracefully to an empty catalog when
`SKILLS_DIR` is absent, so the agent still runs without the skills fetched.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import yaml

from .config import get_config


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    entities: tuple[str, ...] = ()  # ontology object types the skill appliesTo
    actions: tuple[str, ...] = ()  # ontology actions the skill appliesTo
    invokes: tuple[str, ...] = ()  # ontology actions the skill actually invokes
    preload: bool = False  # if true, body is injected into the system prompt at startup
    version: int | None = None


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a `---`-fenced YAML frontmatter block from the markdown body."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                meta = yaml.safe_load("\n".join(lines[1:i])) or {}
                body = "\n".join(lines[i + 1 :]).lstrip("\n")
                return (meta if isinstance(meta, dict) else {}), body
    return {}, text


def _first_blockquote(text: str) -> str | None:
    return next(
        (line[1:].strip() for line in text.splitlines() if line.strip().startswith(">")),
        None,
    )


class SkillLoader:
    def __init__(self, playbook_dir: Path | None = None):
        self._dir = playbook_dir or get_config().skills_dir

    @cached_property
    def _skills(self) -> dict[str, Skill]:
        skills: dict[str, Skill] = {}
        if not self._dir.exists():
            return skills
        for path in sorted(self._dir.glob("*.md")):
            text = path.read_text()
            meta, body = _split_frontmatter(text)
            name = meta.get("apiName") or path.name.removesuffix(".md").removesuffix(".skill")
            description = meta.get("description") or _first_blockquote(text) or "(no description)"
            description = " ".join(description.split())  # collapse folded/multi-line scalars
            applies = meta.get("appliesTo") or {}
            skills[name] = Skill(
                name=name,
                description=description,
                body=body,
                entities=tuple(applies.get("objectTypes", []) or ()),
                actions=tuple(applies.get("actions", []) or ()),
                invokes=tuple(meta.get("invokes", []) or ()),
                preload=bool(meta.get("preload", False)),
                version=meta.get("version"),
            )
        return skills

    def get_skill(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all_skills(self) -> tuple[Skill, ...]:
        return tuple(self._skills.values())

    def preloaded_skills(self) -> tuple[Skill, ...]:
        """Skills flagged preload — injected into the system prompt at startup."""
        return tuple(s for s in self._skills.values() if s.preload)

    def required_actions(self) -> set[str]:
        """Every ontology action any loaded skill may `invoke` (from its frontmatter)."""
        return {a for s in self._skills.values() for a in s.invokes}

    def skills_catalog(self) -> str:
        # Preload skills are injected into the prompt directly, not lazy-loaded, so they
        # are omitted from the on-demand catalog.
        catalog = [s for s in self._skills.values() if not s.preload]
        if not catalog:
            return "(no skills available)"
        lines = []
        for s in catalog:
            tags = []
            if s.entities:
                tags.append("applies to: " + ", ".join(s.entities))
            if s.actions:
                tags.append("actions: " + ", ".join(s.actions))
            suffix = f"  ({'; '.join(tags)})" if tags else ""
            lines.append(f"- {s.name}: {s.description}{suffix}")
        return "\n".join(lines)


skill_loader = SkillLoader()

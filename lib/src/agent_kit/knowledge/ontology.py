"""Ontology lookup tool + loader (on-demand, pay-per-use).

`describe_entity` answers "which skills / actions / KB govern this ontology entity?" from
the release-pinned bindings.json (fetched into ONTOLOGY_DIR), plus its properties /
datasource / related governed entities. It pulls context at call time exactly like the KB
tool pulls KB chunks — nothing ontology-related sits in the prompt.

The OntologyLoader (a read-only consumer of the design/governance layer) is co-located here
since `describe_entity` is its only consumer. It degrades gracefully to empty when the
artifacts are absent, so the agent still runs with zero ontology fetched.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from strands import tool


@dataclass(frozen=True)
class EntityView:
    api_name: str
    display_name: str
    primary_key: str | list[str] | None
    datasource: str | None  # ontology source-of-truth, NOT a runtime table
    properties: tuple[tuple[str, str], ...]  # (apiName, type) — empty if compiled file absent
    skills: tuple[str, ...]  # index.objectType[x].skills + skillsViaLink
    actions: tuple[str, ...]  # index.objectType[x].actions
    kb: tuple[str, ...]  # index.objectType[x].kb tags
    related: tuple[tuple[str, str, str], ...]  # (linkApiName, direction "out"|"in", otherEntity)


class OntologyLoader:
    def __init__(self, ontology_dir: Path | None = None):
        self._dir = ontology_dir or Path(os.getenv("ONTOLOGY_DIR", "ontology"))

    @cached_property
    def _bindings(self) -> dict:
        p = self._dir / "bindings.json"
        return json.loads(p.read_text()) if p.exists() else {}

    @cached_property
    def _ontology(self) -> dict:
        # Optional: bindings.json alone covers skills/actions/kb; the compiled file only
        # adds properties / primaryKey / datasource / relationships.
        p = self._dir / "ontology.compiled.json"
        return json.loads(p.read_text()) if p.exists() else {}

    @cached_property
    def _by_name(self) -> dict[str, dict]:
        return {o["apiName"]: o for o in self._ontology.get("objectTypes", [])}

    @property
    def version(self) -> str:
        return (self._bindings.get("generatedFrom") or {}).get("ontologyVersion", "?")

    def entity_names(self) -> list[str]:
        # Only the entities the knowledge layer actually binds, never all 42.
        return sorted(self._bindings.get("index", {}).get("objectType", {}))

    def describe_entity(self, api_name: str) -> EntityView | None:
        # Case-insensitive resolve against the bound set (cheap recovery for the model).
        bound = self._bindings.get("index", {}).get("objectType", {})
        key = next((k for k in bound if k.lower() == api_name.lower()), None)
        if key is None:
            return None
        idx = bound[key]
        o = self._by_name.get(key, {})  # {} when compiled file not shipped
        bound_set = set(bound)
        related = tuple(
            (
                lt["apiName"],
                "out" if lt["from"]["objectType"] == key else "in",
                lt["to"]["objectType"] if lt["from"]["objectType"] == key else lt["from"]["objectType"],
            )
            for lt in self._ontology.get("linkTypes", [])
            if key in (lt["from"]["objectType"], lt["to"]["objectType"])
            and lt["from"]["objectType"] in bound_set
            and lt["to"]["objectType"] in bound_set
        )
        return EntityView(
            api_name=key,
            display_name=o.get("displayName", key),
            primary_key=o.get("primaryKey"),
            datasource=(o.get("backing") or {}).get("datasource"),
            properties=tuple((p["apiName"], p.get("type", "")) for p in o.get("properties", [])),
            skills=tuple(sorted(set(idx.get("skills", []) + idx.get("skillsViaLink", [])))),
            actions=tuple(idx.get("actions", [])),
            kb=tuple(idx.get("kb", [])),
            related=related,
        )


ontology_loader = OntologyLoader()


@tool
def describe_entity(api_name: str) -> str:
    """Look up an ontology entity: the skills, actions, and KB docs that govern it, its
    properties and source-of-truth datasource, and how it relates to other governed
    entities. Use it to decide which skill/action applies to a request (e.g. CreditProfile,
    SalesOrder, Dispute) before acting, then call load_skill(name) to read its steps.

    NOTE: this is the DESIGN/ontology model. Entity and property names differ from the
    runtime Snowflake fields the snowflake___* Gateway tools return
    (order_id/amount/status/channel) — never pass ontology names as tool arguments.
    """
    v = ontology_loader.describe_entity(api_name)
    if v is None:
        names = ", ".join(ontology_loader.entity_names()) or "(ontology unavailable)"
        return f"No governed ontology entity {api_name!r}. Governed entities: {names}"
    props = ", ".join(f"{n}:{t}" for n, t in v.properties) or "(property detail not shipped)"
    rels = (
        "; ".join(
            f"{v.api_name} -{ln}-> {other}" if d == "out" else f"{other} -{ln}-> {v.api_name}"
            for ln, d, other in v.related
        )
        or "-"
    )
    return (
        f"{v.api_name} ({v.display_name}) [ontologyVersion {ontology_loader.version}]\n"
        f"primaryKey: {v.primary_key}\n"
        f"source-of-truth datasource: {v.datasource or 'unmapped'} "
        f"(ontology model; NOT the agent's Snowflake runtime table)\n"
        f"properties: {props}\n"
        f"governing skills: {', '.join(v.skills) or '-'}  "
        f"(call load_skill(name) to read its steps)\n"
        f"actions: {', '.join(v.actions) or '-'}\n"
        f"KB: {', '.join(v.kb) or '-'}\n"
        f"related governed entities: {rels}"
    )

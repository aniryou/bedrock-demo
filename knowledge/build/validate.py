#!/usr/bin/env python3
"""Validate and compile the ontology.

  1. Loads every YAML layer in ontology/ and merges into one document.
  2. Validates that document against schema/ontology.schema.json (Draft 2020-12).
  3. Runs referential-integrity checks JSON Schema can't express.
  4. Writes build/ontology.compiled.json — the single artifact you hand the agent.

Usage:  python build/validate.py   (non-zero exit on any problem; drops into CI)
"""
import json
import sys
import pathlib
import yaml
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parents[1]
ONT = ROOT / "ontology"
SCHEMA = ROOT / "schema" / "ontology.schema.json"
OUT = ROOT / "build" / "ontology.compiled.json"

LAYER_FILES = [
    "_meta.yaml", "datasources.yaml", "object-types.yaml",
    "link-types.yaml", "action-types.yaml",
]


def load_merged():
    doc = {}
    for fname in LAYER_FILES:
        data = yaml.safe_load((ONT / fname).read_text()) or {}
        if not isinstance(data, dict):
            sys.exit(f"{fname}: top level must be a mapping")
        clash = doc.keys() & data.keys()
        if clash:
            sys.exit(f"{fname}: duplicate top-level keys across layers: {clash}")
        doc.update(data)
    return doc


def ids(items):
    return {i.get("apiName") for i in items}


def pk_fields(o):
    pk = o.get("primaryKey")
    if pk is None:
        return []
    return pk if isinstance(pk, list) else [pk]


def referential_checks(doc):
    errs = []
    ds_ids = ids(doc.get("datasources", []))
    conn_ids = ids(doc.get("connections", []))
    obj_ids = ids(doc.get("objectTypes", []))

    for d in doc.get("datasources", []):
        c = d.get("connection")
        if c and c not in conn_ids:
            errs.append(f"datasource '{d['apiName']}' references unknown connection '{c}'")

    for o in doc.get("objectTypes", []):
        oid = o["apiName"]
        b = o.get("backing")
        if b and b.get("datasource") and b["datasource"] not in ds_ids:
            errs.append(f"object '{oid}' backing datasource '{b['datasource']}' not in registry")
        prop_ids = ids(o.get("properties", []))
        for kf in pk_fields(o):
            if kf not in prop_ids:
                errs.append(f"object '{oid}' primaryKey component '{kf}' is not a declared property")
        if o.get("titleProperty") and o["titleProperty"] not in prop_ids:
            errs.append(f"object '{oid}' titleProperty '{o['titleProperty']}' is not a declared property")
        for p in o.get("properties", []):
            managed = p.get("managed", False)
            if managed and ("column" in p or "source" in p):
                errs.append(f"object '{oid}.{p['apiName']}' is managed:true but also declares a "
                            f"column/source — managed properties have no source of truth")
            if "source" in p and p["source"].get("datasource") not in ds_ids:
                errs.append(f"object '{oid}.{p['apiName']}' source datasource "
                            f"'{p['source'].get('datasource')}' not in registry")

    for l in doc.get("linkTypes", []):
        for end in ("from", "to"):
            ot = l.get(end, {}).get("objectType")
            if ot not in obj_ids:
                errs.append(f"link '{l['apiName']}' {end}.objectType '{ot}' is unknown")

    for a in doc.get("actionTypes", []):
        if a.get("targetObjectType") not in obj_ids:
            errs.append(f"action '{a['apiName']}' targetObjectType '{a.get('targetObjectType')}' is unknown")

    for layer in ("datasources", "objectTypes", "linkTypes", "actionTypes"):
        seen = set()
        for it in doc.get(layer, []):
            k = it.get("apiName")
            if k in seen:
                errs.append(f"{layer}: duplicate apiName '{k}'")
            seen.add(k)
    return errs


# Data sensitivity tiers that, on their own, make a read require the user's authority.
_SENSITIVE = {"confidential", "restricted"}


def enrich_authority(doc):
    """Derive per-action `authority` (agent|user) into the compiled artifact.

    authority = 'user' (the agent must impersonate the human) when the action
    mutates enterprise state OR its target object is confidential/restricted;
    otherwise 'agent' (the agent acts on its own service identity). An explicit
    `authority` on the action overrides the derivation. This is the single
    declarative source the consuming agent's credential-routing layer reads — the
    ontology says WHAT is privileged, never HOW it is enforced.
    """
    obj_class = {o["apiName"]: o.get("classification") for o in doc.get("objectTypes", [])}
    counts = {"agent": 0, "user": 0}
    for a in doc.get("actionTypes", []):
        target_cls = obj_class.get(a.get("targetObjectType"))
        derived = "user" if (a.get("mutates") or target_cls in _SENSITIVE) else "agent"
        if a.get("authority"):
            a["authoritySource"] = "declared"
        else:
            a["authority"] = derived
            a["authoritySource"] = "derived"
        a["targetClassification"] = target_cls or "unclassified"
        counts[a["authority"]] += 1
    return counts


def main():
    doc = load_merged()
    validator = Draft202012Validator(json.loads(SCHEMA.read_text()))
    problems = []
    for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
        loc = "/".join(str(x) for x in e.path) or "(root)"
        problems.append(f"[schema] {loc}: {e.message}")
    problems += [f"[ref]    {m}" for m in referential_checks(doc)]

    if problems:
        print("FAILED validation:\n  " + "\n  ".join(problems))
        sys.exit(1)

    authority = enrich_authority(doc)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2))
    print(f"OK  ·  {len(doc.get('datasources', []))} datasources, "
          f"{len(doc.get('objectTypes', []))} object types, "
          f"{len(doc.get('linkTypes', []))} links, "
          f"{len(doc.get('actionTypes', []))} actions "
          f"({authority['user']} user / {authority['agent']} agent)")
    print(f"     compiled -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

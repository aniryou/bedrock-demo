#!/usr/bin/env python3
"""Resolve skill/KB bindings against the ontology and emit the reverse index.

  1. Loads the ontology (via validate.load_merged) and the skill manifests
     (skills/*.skill.md frontmatter + skills/examples/*.skill.yaml) and KB
     registry (kb/index.yaml).
  2. Validates each manifest against schema/bindings.schema.json.
  3. Resolves every reference against the compiled ontology — a dangling
     objectType / linkType / action / datasource / property reference, or a
     missing KB file, fails the build (non-zero exit). This is the cross-layer
     drift gate: a skill or KB pointing at a renamed/removed entity breaks CI.
  4. Expands link references to their endpoint objects.
  5. Writes:
       build/bindings.json  resolved bindings + reverse index (committed; CI-gated)
       build/bindings.md     human-readable coverage report (generated; git-ignored)

Coverage gaps (actions with no skill, skills bound to nothing, entities with no
skill/KB) are reported but do NOT fail the build.

Usage:  python build/bindings.py
"""
import json
import sys
import pathlib
import yaml
from jsonschema import Draft202012Validator

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from validate import load_merged  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills"
KB_INDEX = ROOT / "kb" / "index.yaml"
BSCHEMA = ROOT / "schema" / "bindings.schema.json"
OUT_JSON = ROOT / "build" / "bindings.json"
OUT_MD = ROOT / "build" / "bindings.md"

# Datasources that have a working mock backend in bedrock-demo-stubs. Used only
# for an advisory coverage line: a skill that reads a datasource
# with no stub can't be demoed end-to-end. Advisory — it does NOT fail the build.
STUBBED_DATASOURCES = {"sap"}


def uniq(xs):
    return sorted(set(xs))


def _frontmatter(text):
    """Parse the leading ``---``-fenced YAML frontmatter of a skill markdown file."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return yaml.safe_load("\n".join(lines[1:i])) or {}
    return {}


def _read_manifest(path):
    """Load a skill manifest from either ``*.skill.yaml`` or ``*.skill.md`` (frontmatter)."""
    text = path.read_text()
    if path.name.endswith(".skill.md"):
        return _frontmatter(text)
    return yaml.safe_load(text) or {}


def main():
    ont = load_merged()
    objs = {o["apiName"] for o in ont.get("objectTypes", [])}
    link_ends = {l["apiName"]: (l["from"]["objectType"], l["to"]["objectType"])
                 for l in ont.get("linkTypes", [])}
    links = set(link_ends)
    action_target = {a["apiName"]: a.get("targetObjectType") for a in ont.get("actionTypes", [])}
    actions = set(action_target)
    datasources = {d["apiName"] for d in ont.get("datasources", [])}
    props = set()
    for o in ont.get("objectTypes", []):
        for p in o.get("properties", []):
            props.add(f"{o['apiName']}.{p['apiName']}")

    errs = []

    def check_refset(rs, where):
        if not rs:
            return
        for ot in rs.get("objectTypes", []):
            if ot not in objs:
                errs.append(f"{where}: unknown objectType '{ot}'")
        for lt in rs.get("linkTypes", []):
            if lt not in links:
                errs.append(f"{where}: unknown linkType '{lt}'")
        for ac in rs.get("actions", []):
            if ac not in actions:
                errs.append(f"{where}: unknown action '{ac}'")
        for ds in rs.get("datasources", []):
            if ds not in datasources:
                errs.append(f"{where}: unknown datasource '{ds}'")
        for pr in rs.get("properties", []):
            if pr not in props:
                errs.append(f"{where}: unknown property '{pr}'")

    # ---- load manifests ----
    # Skills are authored as `*.skill.md` (YAML frontmatter + procedure body, the
    # agent-consumed form) or `*.skill.yaml` (metadata-only examples under skills/).
    # Both are resolved recursively against the ontology.
    skills = []
    skill_paths = sorted(
        set(SKILLS_DIR.rglob("*.skill.yaml")) | set(SKILLS_DIR.rglob("*.skill.md")),
        key=lambda p: p.as_posix(),
    )
    for p in skill_paths:
        d = _read_manifest(p)
        skills.append((p.relative_to(ROOT).as_posix(), d))
    kb_index = yaml.safe_load(KB_INDEX.read_text()) if KB_INDEX.exists() else {"kb": []}
    kb_docs = (kb_index or {}).get("kb", [])

    # ---- schema validation ----
    bschema = json.loads(BSCHEMA.read_text())
    defs = {"$defs": bschema["$defs"]}
    skill_v = Draft202012Validator({**defs, "$ref": "#/$defs/skill"})
    kbindex_v = Draft202012Validator({**defs, "$ref": "#/$defs/kbIndex"})
    for fname, d in skills:
        for e in skill_v.iter_errors(d):
            errs.append(f"[schema] {fname}: {e.message}")
    if KB_INDEX.exists():
        for e in kbindex_v.iter_errors(kb_index):
            loc = "/".join(str(x) for x in e.path) or "(root)"
            errs.append(f"[schema] kb/index.yaml {loc}: {e.message}")

    # ---- reference resolution ----
    for fname, s in skills:
        w = f"skill '{s.get('apiName', fname)}'"
        check_refset(s.get("appliesTo"), w + " appliesTo")
        for ac in s.get("invokes", []):
            if ac not in actions:
                errs.append(f"{w} invokes unknown action '{ac}'")
        check_refset(s.get("reads"), w + " reads")
    for doc in kb_docs:
        w = f"kb '{doc.get('apiName')}'"
        if not (ROOT / doc.get("path", "")).exists():
            errs.append(f"{w}: file not found at '{doc.get('path')}'")
        check_refset(doc.get("concerns"), w + " concerns")
        for ch in doc.get("chunks", []):
            check_refset(ch.get("concerns"), f"{w} chunk '{ch.get('id')}' concerns")

    if errs:
        print("FAILED bindings:\n  " + "\n  ".join(errs))
        sys.exit(1)

    # ---- reverse index ----
    obj_idx = {ot: {"skills": [], "skillsViaLink": [], "kb": [], "actions": []} for ot in objs}
    link_idx = {lt: {"skills": [], "kb": []} for lt in links}
    act_idx = {ac: {"governedBySkills": [], "invokedBySkills": [], "targetObjectType": tgt}
               for ac, tgt in action_target.items()}

    for ac, tgt in action_target.items():
        if tgt in obj_idx:
            obj_idx[tgt]["actions"].append(ac)

    for _, s in skills:
        name = s["apiName"]
        at = s.get("appliesTo", {}) or {}
        for ot in at.get("objectTypes", []):
            obj_idx[ot]["skills"].append(name)
        for lt in at.get("linkTypes", []):
            link_idx[lt]["skills"].append(name)
            for ep in link_ends.get(lt, ()):
                if ep in obj_idx:
                    obj_idx[ep]["skillsViaLink"].append(name)
        for ac in at.get("actions", []):
            act_idx[ac]["governedBySkills"].append(name)
        for ac in s.get("invokes", []):
            act_idx[ac]["invokedBySkills"].append(name)

    def add_kb_concerns(concerns, tag):
        c = concerns or {}
        for ot in c.get("objectTypes", []):
            obj_idx[ot]["kb"].append(tag)
        for lt in c.get("linkTypes", []):
            link_idx[lt]["kb"].append(tag)
        for pr in c.get("properties", []):
            owner = pr.split(".")[0]
            if owner in obj_idx:
                obj_idx[owner]["kb"].append(tag)

    for doc in kb_docs:
        dn = doc["apiName"]
        add_kb_concerns(doc.get("concerns"), dn)
        for ch in doc.get("chunks", []):
            add_kb_concerns(ch.get("concerns"), f"{dn}#{ch['id']}")

    for node in obj_idx.values():
        for k in node:
            node[k] = uniq(node[k])
    for node in link_idx.values():
        for k in node:
            node[k] = uniq(node[k])
    for node in act_idx.values():
        node["governedBySkills"] = uniq(node["governedBySkills"])
        node["invokedBySkills"] = uniq(node["invokedBySkills"])

    # prune empty entity/link nodes (keep all action nodes — they carry a target)
    obj_idx = {k: v for k, v in obj_idx.items()
               if v["skills"] or v["skillsViaLink"] or v["kb"] or v["actions"]}
    link_idx = {k: v for k, v in link_idx.items() if v["skills"] or v["kb"]}

    # ---- coverage ----
    bound_objs = set(obj_idx)
    entities_no_binding = uniq([o for o in objs
                                if o not in obj_idx
                                or not (obj_idx[o]["skills"] or obj_idx[o]["skillsViaLink"] or obj_idx[o]["kb"])])
    # skills that read a datasource with no mock backend in bedrock-demo-stubs
    skills_unstubbed = {
        s["apiName"]: miss
        for _, s in skills
        if (miss := uniq(set((s.get("reads") or {}).get("datasources", [])) - STUBBED_DATASOURCES))
    }
    coverage = {
        "actionsWithoutGoverningSkill": uniq([a for a in actions if not act_idx[a]["governedBySkills"]]),
        # preload (doctrine) skills are intentionally not entity-bound — exclude them.
        "skillsBoundToNothing": uniq([s["apiName"] for _, s in skills
                                      if not s.get("preload")
                                      and not ((s.get("appliesTo") or {}).get("objectTypes")
                                               or (s.get("appliesTo") or {}).get("linkTypes")
                                               or (s.get("appliesTo") or {}).get("actions"))]),
        "entitiesWithoutSkillOrKb": entities_no_binding,
        "skillsReadingUnstubbedDatasources": skills_unstubbed,
    }

    # resolved manifests (with link-endpoint expansion for skills)
    resolved_skills = []
    for fname, s in sorted(skills, key=lambda t: t[1]["apiName"]):
        at = s.get("appliesTo", {}) or {}
        expanded = set(at.get("objectTypes", []))
        for lt in at.get("linkTypes", []):
            expanded.update(e for e in link_ends.get(lt, ()) if e)
        resolved_skills.append({**s, "_file": fname, "appliesToExpandedObjectTypes": uniq(expanded)})

    out = {
        "generatedFrom": {
            "title": ont.get("title"),
            "ontologyVersion": ont.get("ontologyVersion"),
            "skills": len(skills),
            "kbDocs": len(kb_docs),
        },
        "skills": resolved_skills,
        "kb": sorted(kb_docs, key=lambda d: d["apiName"]),
        "index": {"objectType": obj_idx, "linkType": link_idx, "action": act_idx},
        "coverage": coverage,
    }
    OUT_JSON.write_text(json.dumps(out, indent=2, sort_keys=True))

    # ---- markdown report ----
    md = []
    md.append(f"# Skill / KB bindings — {ont.get('title', 'ontology')}")
    md.append("")
    md.append(f"`{len(skills)}` skills · `{len(kb_docs)}` KB docs · "
              f"`{len(obj_idx)}` entities bound · `{len(link_idx)}` relationships bound · "
              f"`{len(coverage['entitiesWithoutSkillOrKb'])}` entities with no skill/KB.")
    md.append("")
    md.append("## Entities and what binds to them")
    md.append("")
    md.append("| Entity | Skills | Skills via link | KB | Actions |")
    md.append("|---|---|---|---|---|")
    for ot in sorted(obj_idx):
        n = obj_idx[ot]
        md.append(f"| {ot} | {', '.join(n['skills']) or '·'} | {', '.join(n['skillsViaLink']) or '·'} "
                  f"| {', '.join(n['kb']) or '·'} | {', '.join(n['actions']) or '·'} |")
    md.append("")
    if link_idx:
        md.append("## Relationships with bindings")
        md.append("")
        md.append("| Relationship | Skills | KB |")
        md.append("|---|---|---|")
        for lt in sorted(link_idx):
            n = link_idx[lt]
            md.append(f"| {lt} | {', '.join(n['skills']) or '·'} | {', '.join(n['kb']) or '·'} |")
        md.append("")
    md.append("## Coverage gaps (advisory — do not fail the build)")
    md.append("")
    md.append(f"- Actions with no governing skill: {', '.join(coverage['actionsWithoutGoverningSkill']) or 'none'}")
    md.append(f"- Skills bound to nothing: {', '.join(coverage['skillsBoundToNothing']) or 'none'}")
    md.append(f"- Entities with no skill or KB ({len(coverage['entitiesWithoutSkillOrKb'])}): "
              f"{', '.join(coverage['entitiesWithoutSkillOrKb']) or 'none'}")
    unstubbed = coverage["skillsReadingUnstubbedDatasources"]
    md.append("- Skills reading datasources with no stub in bedrock-demo-stubs: "
              + (", ".join(f"{k} → {', '.join(v)}" for k, v in sorted(unstubbed.items())) or "none"))
    md.append("")
    OUT_MD.write_text("\n".join(md))

    # ---- stdout ----
    print(f"OK  ·  {len(skills)} skills, {len(kb_docs)} KB docs  ->  "
          f"{len(obj_idx)} entities + {len(link_idx)} relationships bound")
    print(f"     actions without a skill: {len(coverage['actionsWithoutGoverningSkill'])} · "
          f"skills bound to nothing: {len(coverage['skillsBoundToNothing'])} · "
          f"entities with no skill/KB: {len(coverage['entitiesWithoutSkillOrKb'])} · "
          f"skills reading unstubbed datasources: {len(coverage['skillsReadingUnstubbedDatasources'])}")
    print(f"     wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

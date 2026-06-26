#!/usr/bin/env python3
"""Render the compiled ontology to a self-contained interactive HTML page and a
GitHub-flavoured markdown overview, for quick human inspection.

Reads:
  build/ontology.compiled.json   the compiled ontology (validate.py output)
  build/bindings.json            skill / KB / action reverse index (bindings.py output; optional)

Writes:
  build/ontology.html            interactive entity-relationship graph (vis-network).
                                 Uploaded as a CI artifact — download and open in a browser.
  build/ontology-summary.md      stats + datasource table + a Mermaid graph. The CI appends
                                 this to the GitHub job summary, so the ontology is visible on
                                 the Actions run page without downloading anything.

Usage:  python build/render_ontology.py
"""
import collections
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
ONT = ROOT / "build" / "ontology.compiled.json"
BIND = ROOT / "build" / "bindings.json"
OUT_HTML = ROOT / "build" / "ontology.html"
OUT_MD = ROOT / "build" / "ontology-summary.md"

WORKSTREAMS = {
    "A": ("A · Bean sourcing & procurement", "#2e7d57"),
    "B": ("B · Planning, blend & inventory", "#b07a16"),
    "C": ("C · Sales, contracting & fulfilment", "#3f57b5"),
}


def _mermaid_label(text):
    """Reduce a string to a Mermaid-safe label (node, edge, or subgraph text).

    Mermaid's flowchart parser treats & ( ) [ ] { } | ; # < > as significant even
    inside quoted labels on some renderers (GitHub's included), so strip them — one
    bad character breaks the whole diagram.
    """
    s = (text or "").replace("&", " and ")
    s = re.sub(r'[|()\[\]{}"#;<>]', " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or "node"


def build_model():
    ont = json.loads(ONT.read_text())
    bind = json.loads(BIND.read_text()) if BIND.exists() else {"index": {"objectType": {}}}
    obj_idx = bind.get("index", {}).get("objectType", {})

    objs = ont.get("objectTypes", [])
    links = ont.get("linkTypes", [])
    datasources = ont.get("datasources", [])
    actions = ont.get("actionTypes", [])

    # datasource apiName -> entities it backs (source-of-truth registry rollup)
    ds_backs = collections.defaultdict(list)
    for o in objs:
        ds = (o.get("backing") or {}).get("datasource")
        if ds:
            ds_backs[ds].append(o["apiName"])

    nodes, meta = [], {}
    for o in objs:
        name = o["apiName"]
        idx = obj_idx.get(name, {})
        nodes.append({
            "id": name,
            "label": o.get("displayName", name),
            "group": o.get("workstream") or "_",
            "value": len(o.get("properties", [])),
            "bound": bool(idx.get("skills") or idx.get("skillsViaLink") or idx.get("kb")),
        })
        meta[name] = {
            "displayName": o.get("displayName", name),
            "workstream": o.get("workstream"),
            "group": o.get("group"),
            "primaryKey": o.get("primaryKey"),
            "datasource": (o.get("backing") or {}).get("datasource"),
            "properties": [
                {"apiName": p["apiName"], "type": p.get("type", "")}
                for p in o.get("properties", [])
            ],
            "skills": sorted(set(idx.get("skills", []) + idx.get("skillsViaLink", []))),
            "actions": idx.get("actions", []),
            "kb": idx.get("kb", []),
        }

    edges = []
    for ln in links:
        edges.append({
            "from": ln["from"]["objectType"],
            "to": ln["to"]["objectType"],
            "label": ln.get("displayName", ln["apiName"]),
            "apiName": ln["apiName"],
            "kind": ln.get("kind", "association"),
            "cardinality": ln.get("cardinality", ""),
        })

    return {
        "meta": {
            "title": ont.get("title", "Ontology"),
            "ontologyVersion": ont.get("ontologyVersion", ""),
            "schemaVersion": ont.get("schemaVersion", ""),
            "domain": ont.get("domain", ""),
            "status": ont.get("status", ""),
        },
        "nodes": nodes,
        "edges": edges,
        "nodeMeta": meta,
        "datasources": [
            {
                "apiName": d["apiName"],
                "kind": d.get("kind", ""),
                "connection": d.get("connection", ""),
                "note": d.get("note", ""),
                "backs": sorted(ds_backs.get(d["apiName"], [])),
            }
            for d in datasources
        ],
        "actions": [
            {"apiName": a["apiName"], "target": a.get("targetObjectType", "")}
            for a in actions
        ],
        "workstreams": {k: v[0] for k, v in WORKSTREAMS.items()},
        "colors": {k: v[1] for k, v in WORKSTREAMS.items()},
        "counts": {
            "entities": len(objs),
            "links": len(links),
            "associations": sum(1 for ln in links if ln.get("kind") == "association"),
            "dependencies": sum(1 for ln in links if ln.get("kind") == "dependency"),
            "datasources": len(datasources),
            "actions": len(actions),
            "skills": (bind.get("generatedFrom") or {}).get("skills", 0),
            "kbDocs": (bind.get("generatedFrom") or {}).get("kbDocs", 0),
        },
    }


# ── HTML (vis-network). Placeholders are replaced (not f-string) so JS braces survive. ──
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — ontology</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.45 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         color: #1c2330; background: #f6f7f9; }
  header { padding: 12px 16px; border-bottom: 1px solid #d8dce3; background: #fff; }
  h1 { font-size: 18px; margin: 0 0 2px; }
  .sub { color: #5b6473; font-size: 12px; }
  .bar { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; margin-top: 8px; }
  .chip { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; padding: 2px 8px;
          border: 1px solid #d8dce3; border-radius: 999px; background: #fff; cursor: pointer; user-select: none; }
  .chip input { margin: 0; }
  .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
  .stat { font-size: 12px; color: #3a4151; }
  .stat b { color: #1c2330; }
  input[type=search] { padding: 4px 8px; border: 1px solid #cfd4dd; border-radius: 6px; font-size: 12px; }
  button { font-size: 12px; padding: 4px 10px; border: 1px solid #cfd4dd; border-radius: 6px;
           background: #fff; cursor: pointer; }
  #wrap { display: flex; height: calc(100vh - 96px); }
  #net { flex: 1 1 auto; background:
         radial-gradient(circle at 1px 1px, #e4e7ec 1px, transparent 0) 0 0 / 22px 22px, #fbfcfd; }
  aside { width: 320px; flex: 0 0 320px; border-left: 1px solid #d8dce3; background: #fff;
          overflow: auto; padding: 14px 16px; }
  aside h2 { font-size: 15px; margin: 0 0 2px; }
  aside .muted { color: #6b7280; font-size: 12px; }
  aside table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12px; }
  aside td { padding: 3px 4px; border-bottom: 1px solid #eef0f3; vertical-align: top; }
  aside td.k { color: #6b7280; width: 38%; }
  .tag { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 999px;
         background: #eef1f6; color: #36507e; margin: 2px 3px 0 0; }
  .hint { color: #6b7280; }
  @media (prefers-color-scheme: dark) {
    body { color: #e6e9ef; background: #0f1115; }
    header, aside { background: #161a21; border-color: #2a2f3a; }
    .chip, button, input[type=search] { background: #1d222b; border-color: #2a2f3a; color: #e6e9ef; }
    #net { background: radial-gradient(circle at 1px 1px, #232833 1px, transparent 0) 0 0 / 22px 22px, #121620; }
    aside td { border-color: #232833; } .tag { background: #222a38; color: #9fc0ff; }
    h1, aside h2, .stat b { color: #f2f4f8; }
  }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <div class="sub">__SUBLINE__</div>
  <div class="bar" id="filters"></div>
  <div class="bar">
    <span class="stat" id="stats"></span>
    <input type="search" id="search" placeholder="Find an entity…" autocomplete="off">
    <button id="fit">Fit</button>
    <button id="physics">Pause layout</button>
  </div>
</header>
<div id="wrap">
  <div id="net"></div>
  <aside id="details"><p class="hint">Click an entity to see its key, source of truth, properties and bound skills.</p></aside>
</div>
<script>
const DATA = __DATA__;
const COLORS = DATA.colors, WS = DATA.workstreams;
function wsColor(g){ return COLORS[g] || "#6b7280"; }

const nodes = new vis.DataSet(DATA.nodes.map(n => ({
  id: n.id, label: n.label, group: n.group, value: n.value,
  shape: "dot",
  borderWidth: n.bound ? 3 : 1,
  color: { background: wsColor(n.group), border: n.bound ? "#111827" : wsColor(n.group),
           highlight: { background: wsColor(n.group), border: "#111827" } },
  font: { color: "#11151c" }
})));
const edges = new vis.DataSet(DATA.edges.map((e, i) => ({
  id: i, from: e.from, to: e.to, label: e.label, arrows: "to",
  dashes: e.kind === "dependency",
  color: { color: "#9aa3b2", highlight: "#4b5563" },
  font: { size: 10, color: "#6b7280", strokeWidth: 3, strokeColor: "#fbfcfd", align: "middle" },
  smooth: { type: "dynamic" }, title: e.apiName + " — " + e.kind + " · " + e.cardinality
})));

const net = new vis.Network(document.getElementById("net"), { nodes, edges }, {
  nodes: { scaling: { min: 10, max: 34 } },
  edges: { selectionWidth: 2 },
  interaction: { hover: true, tooltipDelay: 120, navigationButtons: false, keyboard: false },
  physics: { stabilization: { iterations: 220 },
             barnesHut: { gravitationalConstant: -9000, springLength: 150, springConstant: 0.035 } }
});

// stats + workstream legend/filters
const counts = DATA.counts;
document.getElementById("stats").innerHTML =
  "<b>" + counts.entities + "</b> entities · <b>" + counts.links + "</b> links (" +
  counts.associations + " assoc / " + counts.dependencies + " dep) · <b>" + counts.datasources +
  "</b> datasources · <b>" + counts.actions + "</b> actions · <b>" + counts.skills + "</b> skills";

const active = new Set(Object.keys(WS).concat(["_"]));
const filters = document.getElementById("filters");
Object.keys(WS).forEach(code => {
  const lab = document.createElement("label"); lab.className = "chip";
  lab.innerHTML = '<input type="checkbox" checked><span class="dot" style="background:' +
    wsColor(code) + '"></span>' + WS[code];
  lab.querySelector("input").addEventListener("change", e => {
    if (e.target.checked) active.add(code); else active.delete(code); applyFilter();
  });
  filters.appendChild(lab);
});
function applyFilter(){
  nodes.update(DATA.nodes.map(n => ({ id: n.id, hidden: !active.has(n.group) })));
  edges.update(DATA.edges.map((e, i) => {
    const fg = (DATA.nodeMeta[e.from]||{}).workstream || "_";
    const tg = (DATA.nodeMeta[e.to]||{}).workstream || "_";
    return { id: i, hidden: !(active.has(fg) && active.has(tg)) };
  }));
}

// details panel
function esc(s){ return String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }
function showDetails(id){
  const m = DATA.nodeMeta[id]; if(!m){ return; }
  const tags = a => a && a.length ? a.map(x => '<span class="tag">'+esc(x)+'</span>').join("") : '<span class="muted">—</span>';
  const props = m.properties.map(p => '<tr><td class="k">'+esc(p.apiName)+'</td><td>'+esc(p.type)+'</td></tr>').join("");
  document.getElementById("details").innerHTML =
    '<h2>'+esc(m.displayName)+'</h2><div class="muted">'+esc(id)+
    (m.workstream ? ' · workstream '+esc(m.workstream) : '')+(m.group ? ' · '+esc(m.group) : '')+'</div>'+
    '<table>'+
      '<tr><td class="k">Primary key</td><td>'+esc(Array.isArray(m.primaryKey)?m.primaryKey.join(", "):(m.primaryKey||"—"))+'</td></tr>'+
      '<tr><td class="k">Source of truth</td><td>'+(m.datasource?esc(m.datasource):'<span class="muted">unmapped</span>')+'</td></tr>'+
      '<tr><td class="k">Skills</td><td>'+tags(m.skills)+'</td></tr>'+
      '<tr><td class="k">Actions</td><td>'+tags(m.actions)+'</td></tr>'+
      '<tr><td class="k">KB</td><td>'+tags(m.kb)+'</td></tr>'+
    '</table>'+
    '<h2 style="margin-top:14px;font-size:13px">Properties ('+m.properties.length+')</h2>'+
    '<table>'+(props||'<tr><td class="muted">none</td></tr>')+'</table>';
}
net.on("selectNode", p => showDetails(p.nodes[0]));

// controls
document.getElementById("fit").onclick = () => net.fit({ animation: true });
let physicsOn = true;
document.getElementById("physics").onclick = e => {
  physicsOn = !physicsOn; net.setOptions({ physics: { enabled: physicsOn } });
  e.target.textContent = physicsOn ? "Pause layout" : "Resume layout";
};
document.getElementById("search").addEventListener("input", e => {
  const q = e.target.value.trim().toLowerCase(); if(!q){ return; }
  const hit = DATA.nodes.find(n => n.id.toLowerCase().includes(q) || n.label.toLowerCase().includes(q));
  if(hit){ net.selectNodes([hit.id]); net.focus(hit.id, { scale: 1.1, animation: true }); showDetails(hit.id); }
});
net.once("stabilizationIterationsDone", () => net.fit());
</script>
</body>
</html>
"""


def render_html(model):
    sub = (f"{model['meta']['domain']} · ontologyVersion {model['meta']['ontologyVersion']} · "
           f"schema {model['meta']['schemaVersion']} · status {model['meta']['status']} — "
           "node size = property count · bold border = has a bound skill/KB · dashed edge = dependency")
    out = (HTML_TEMPLATE
           .replace("__TITLE__", model["meta"]["title"])
           .replace("__SUBLINE__", sub)
           .replace("__DATA__", json.dumps(model, separators=(",", ":"))))
    OUT_HTML.write_text(out)


def render_markdown(model):
    c = model["counts"]
    m = model["meta"]
    by_ws = collections.defaultdict(list)
    for n in model["nodes"]:
        by_ws[n["group"]].append(n)

    md = []
    md.append(f"## 🧬 {m['title']}")
    md.append("")
    md.append(f"`ontologyVersion {m['ontologyVersion']}` · `schema {m['schemaVersion']}` · "
              f"domain `{m['domain']}` · status `{m['status']}`")
    md.append("")
    md.append(f"**{c['entities']}** entities · **{c['links']}** links "
              f"({c['associations']} association / {c['dependencies']} dependency) · "
              f"**{c['datasources']}** datasources · **{c['actions']}** actions · "
              f"**{c['skills']}** skills · **{c['kbDocs']}** KB docs")
    md.append("")
    md.append("> 📊 **Full interactive graph:** download the **ontology-build** artifact from this "
              "run and open `ontology.html` (zoom, drag, filter by work-stream, click an entity for "
              "its source of truth, properties and bound skills).")
    md.append("")

    # entities by work-stream
    md.append("### Entities by work-stream")
    md.append("")
    md.append("| Work-stream | Entities | Names |")
    md.append("|---|--:|---|")
    for code in ["A", "B", "C"]:
        ns = sorted(n["id"] for n in by_ws.get(code, []))
        if ns:
            md.append(f"| {model['workstreams'].get(code, code)} | {len(ns)} | {', '.join(ns)} |")
    md.append("")

    # datasource registry
    md.append("### Source-of-truth registry")
    md.append("")
    md.append("| Datasource | Kind | Backs | Entities |")
    md.append("|---|---|--:|---|")
    for d in sorted(model["datasources"], key=lambda x: (-len(x["backs"]), x["apiName"])):
        md.append(f"| `{d['apiName']}` | {d['kind']} | {len(d['backs'])} | "
                  f"{', '.join(d['backs']) if d['backs'] else '—'} |")
    md.append("")

    # mermaid: work-stream-grouped entity-relationship graph
    md.append("### Entity-relationship graph")
    md.append("")
    md.append("```mermaid")
    md.append("flowchart LR")
    for code in ["A", "B", "C"]:
        ns = sorted(by_ws.get(code, []), key=lambda n: n["id"])
        if not ns:
            continue
        md.append(f'  subgraph WS{code}["{_mermaid_label(model["workstreams"].get(code, code))}"]')
        for n in ns:
            md.append(f'    {n["id"]}["{_mermaid_label(n["label"])}"]')
        md.append("  end")
    for e in model["edges"]:
        connector = "-.->" if e["kind"] == "dependency" else "-->"
        md.append(f'  {e["from"]} {connector}|{_mermaid_label(e["label"])}| {e["to"]}')
    md.append("```")
    md.append("")
    md.append("_Solid = association · dashed = dependency. Diagram is generated from "
              "`build/ontology.compiled.json`; if it is too dense to read here, use the interactive "
              "HTML artifact._")
    md.append("")
    OUT_MD.write_text("\n".join(md))


def main():
    model = build_model()
    render_html(model)
    render_markdown(model)
    c = model["counts"]
    print(f"OK  ·  rendered {c['entities']} entities + {c['links']} links")
    print(f"     wrote {OUT_HTML.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

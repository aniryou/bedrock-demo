#!/usr/bin/env python3
"""Source-of-truth lineage report.

Reads the merged ontology and writes, for every property, where its value comes
from. Two outputs:

  build/lineage.md   human-readable: rollup by system of record, the migration
                     backlog (entities with no defined source), full table.
  build/lineage.csv  one row per property, for spreadsheets / filtering.

"System of record" is the backing connection's kind when there is one, else the
datasource kind (so spreadsheet / email / manual / derived sources show up as
themselves). Properties with no backing at all are "(unmapped)".

Usage:  python build/lineage_report.py
"""
import csv
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from validate import load_merged, pk_fields  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
MD = ROOT / "build" / "lineage.md"
CSV = ROOT / "build" / "lineage.csv"

COLS = ["object", "property", "type", "workstream", "system",
        "datasource", "kind", "column", "pk", "managed", "override"]


def build_rows(doc):
    ds_by_id = {d["apiName"]: d for d in doc.get("datasources", [])}
    conn_kind = {c["apiName"]: c.get("kind", "") for c in doc.get("connections", [])}
    rows = []
    for o in doc.get("objectTypes", []):
        keys = set(pk_fields(o))
        backing = (o.get("backing") or {}).get("datasource")
        for p in o.get("properties", []):
            managed = bool(p.get("managed", False))
            override = "source" in p
            if managed:
                ds_id, ds, column = "", {}, ""
                system, kind = "(managed)", ""
            else:
                if override:
                    ds_id = p["source"].get("datasource", "")
                    column = p["source"].get("column", "")
                else:
                    ds_id = backing or ""
                    column = p.get("column", "")
                ds = ds_by_id.get(ds_id, {})
                if ds_id:
                    kind = ds.get("kind", "")
                    system = conn_kind.get(ds.get("connection", ""), "") or kind
                else:
                    kind, system = "", "(unmapped)"
            rows.append({
                "object": o["apiName"],
                "property": p["apiName"],
                "type": p.get("type", ""),
                "workstream": o.get("workstream", ""),
                "system": system,
                "datasource": ds_id,
                "kind": kind,
                "column": column,
                "pk": "Y" if p["apiName"] in keys else "",
                "managed": "Y" if managed else "",
                "override": "Y" if override else "",
            })
    return rows


def main():
    doc = load_merged()
    rows = build_rows(doc)

    # rollup by system
    by_system = {}
    for r in rows:
        s = by_system.setdefault(r["system"], {"props": 0, "objects": set(), "datasources": set()})
        s["props"] += 1
        s["objects"].add(r["object"])
        if r["datasource"]:
            s["datasources"].add(r["datasource"])

    # entities with no defined source of truth
    unmapped_objs = [o for o in doc.get("objectTypes", []) if not (o.get("backing") or {}).get("datasource")]

    # ---- markdown ----
    out = []
    out.append(f"# Source-of-truth lineage — {doc.get('title', 'ontology')}")
    out.append("")
    out.append(f"`{len(doc.get('objectTypes', []))}` object types · `{len(rows)}` properties · "
               f"`{len(doc.get('datasources', []))}` datasources · "
               f"`{len(unmapped_objs)}` entities without a defined source of truth.")
    out.append("")
    out.append("## By system of record")
    out.append("")
    out.append("| System | Datasources | Objects | Properties |")
    out.append("|---|---|--:|--:|")
    for s in sorted(by_system, key=lambda k: (-by_system[k]["props"], k)):
        v = by_system[s]
        ds_list = ", ".join(sorted(v["datasources"])) or "—"
        out.append(f"| {s} | {ds_list} | {len(v['objects'])} | {v['props']} |")
    out.append("")
    out.append("## Migration backlog — entities with no defined source of truth")
    out.append("")
    out.append("| Object | Work-stream | Properties |")
    out.append("|---|:--:|--:|")
    for o in sorted(unmapped_objs, key=lambda o: (o.get("workstream", ""), o["apiName"])):
        out.append(f"| {o['apiName']} | {o.get('workstream', '')} | {len(o.get('properties', []))} |")
    out.append("")
    out.append("## Property-level lineage")
    out.append("")
    out.append("| Object | Property | Type | WS | System | Datasource | Column | PK | Override |")
    out.append("|---|---|---|:--:|---|---|---|:--:|:--:|")
    for r in rows:
        out.append(f"| {r['object']} | {r['property']} | {r['type']} | {r['workstream']} | "
                   f"{r['system']} | {r['datasource'] or '—'} | {r['column'] or '·'} | "
                   f"{r['pk'] or ''} | {r['override'] or ''} |")
    out.append("")
    MD.write_text("\n".join(out))

    # ---- csv ----
    with CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in COLS})

    # ---- stdout rollup ----
    print(f"Lineage: {len(rows)} properties across {len(doc.get('objectTypes', []))} objects")
    for s in sorted(by_system, key=lambda k: (-by_system[k]["props"], k)):
        v = by_system[s]
        print(f"  {s:<24} {len(v['objects']):>3} objects  {v['props']:>3} properties")
    print(f"  {'-'*24}")
    print(f"  {len(unmapped_objs)} entities still without a defined source of truth")
    print(f"  wrote {MD.relative_to(ROOT)} and {CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

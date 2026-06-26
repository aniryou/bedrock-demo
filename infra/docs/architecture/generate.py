#!/usr/bin/env python3
"""Generate the AWS-style architecture SVGs for the order-triage AgentCore docs.

The diagrams' editable source of truth is ``specs.json`` — one object per plane
(security, agent, memory, observability, evaluation, system-overview). Each object is a
declarative node / edge / group spec (see ``_awsviz.py`` for the grammar). This script
loads them and writes a self-contained ``<key>-architecture.svg`` per plane (official AWS
icons base64-embedded, left-to-right). Run:

    uv run --with diagrams python docs/architecture/generate.py

Optionally rasterizes a ``.png`` fallback per plane when ``rsvg-convert`` (librsvg) is on
PATH. Edit ``specs.json`` and re-run; don't hand-edit the SVGs.
"""
import json
import shutil
import subprocess
from pathlib import Path

import _awsviz as A

HERE = Path(__file__).resolve().parent


def normalize(raw: dict) -> dict:
    """specs.json shape (nodes as a list, size as {w,h}) → the renderer's shape."""
    spec = dict(raw)
    spec["nodes"] = {n["key"]: {k: v for k, v in n.items() if k != "key"}
                     for n in raw["nodes"]}
    spec["size"] = (raw["size"]["w"], raw["size"]["h"])
    return spec


def main() -> None:
    specs = json.loads((HERE / "specs.json").read_text())
    rsvg = shutil.which("rsvg-convert")
    for raw in specs:
        spec = normalize(raw)
        svg = A.write(spec, HERE)
        print(f"wrote {svg.name}: {len(spec['nodes'])} nodes, {len(spec.get('edges', []))} edges")
        if rsvg:
            w, h = spec["size"]
            png = svg.with_suffix(".png")
            subprocess.run([rsvg, "-w", str(w * 2), "-h", str(h * 2), str(svg), "-o", str(png)],
                           check=True)
            print(f"  + {png.name}")
    if not rsvg:
        print("rsvg-convert not found — SVGs written; PNG fallbacks skipped "
              "(brew install librsvg to enable).")


if __name__ == "__main__":
    main()

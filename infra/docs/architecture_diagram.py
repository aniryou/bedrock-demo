#!/usr/bin/env python3
"""Generate the AWS-style system-architecture diagram for the README.

Places the **official AWS Architecture icons** at explicit coordinates in a clean
left-to-right request path, and emits a self-contained ``docs/system-architecture.svg``
(icons embedded as base64 so GitHub renders it) plus a ``.png`` raster fallback.

Requires the ``diagrams`` package (only for the bundled AWS icon PNGs) and, for the
PNG, ``rsvg-convert`` (librsvg) on PATH:

    pip install diagrams           # or: uv run --with diagrams python docs/architecture_diagram.py
    brew install librsvg           # provides rsvg-convert

Edit the NODES / EDGES / GROUPS tables below and re-run; don't hand-edit the SVG.
"""

import base64
import os
import shutil
import subprocess
from pathlib import Path

import diagrams

# ── Official AWS (+ Azure/SaaS) icons from the `diagrams` package ────────────────
_PARENT = Path(os.path.abspath(os.path.dirname(diagrams.__file__))).parent
_ICONS = {
    "user": ("diagrams.aws.general", "User"),
    "client": ("diagrams.aws.general", "Client"),
    "entra": ("diagrams.azure.identity", "ActiveDirectory"),
    "bedrock": ("diagrams.aws.ml", "Bedrock"),
    "apigw": ("diagrams.aws.network", "APIGateway"),
    "lambda": ("diagrams.aws.compute", "Lambda"),
    "snowflake": ("diagrams.saas.analytics", "Snowflake"),
    "memory": ("diagrams.aws.database", "Database"),
    "secrets": ("diagrams.aws.security", "SecretsManager"),
    "guardrail": ("diagrams.aws.security", "Shield"),
    "cwobs": ("diagrams.aws.management", "Cloudwatch"),
}


def _data_uri(key: str) -> str:
    mod, cls = _ICONS[key]
    c = getattr(__import__(mod, fromlist=[cls]), cls)
    raw = Path(os.path.join(_PARENT, c._icon_dir, c._icon)).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


URI = {k: _data_uri(k) for k in _ICONS}

INK = "#232F3E"  # AWS "squid ink" — node titles + cloud boundary
SUB = "#5F5E5A"  # subtitle / edge labels
IC = 52  # icon edge (px)

# ── Nodes: (cx, cy, icon, title, subtitle) — icon centred at (cx,cy), label below ─
NODES = {
    "analyst": (70, 300, "user", "Analyst", "human"),
    "webapp": (200, 300, "client", "Webapp", "Entra sign-in · JWT proxy"),
    "entra": (200, 150, "entra", "Microsoft Entra ID", "user IdP · brokers OBO", "left"),
    "runtime": (430, 300, "bedrock", "AgentCore Runtime", "CUSTOM_JWT · Strands"),
    "gateway": (648, 300, "apigw", "AgentCore Gateway", "Cedar ENFORCE · OBO broker"),
    "sap": (918, 222, "lambda", "SAP credit", "SigV4 · IAM"),
    "orders": (918, 318, "lambda", "Order-actions", "SigV4 · IAM"),
    "snowl": (918, 410, "lambda", "Snowflake-query", "OBO | KEYPAIR_JWT"),
    "snowflake": (1252, 300, "snowflake", "Snowflake", "External OAuth · RLS by region"),
    # model path (supporting row), guardrail stacked directly under the model
    "bedrock": (360, 452, "bedrock", "Amazon Bedrock", "Nova Lite"),
    "guardrail": (360, 576, "guardrail", "Bedrock Guardrail", "prompt-attack filter"),
    "kb": (520, 500, "bedrock", "Knowledge Base", "Titan v2 · S3 Vectors"),
    "memory": (740, 500, "memory", "AgentCore Memory", "facts · prefs · summaries"),
    "secrets": (918, 580, "secrets", "Secrets Manager", "RSA key · Entra secret"),
    # observability / control plane (off the request path)
    "cwobs": (545, 700, "cwobs", "CloudWatch GenAI Observability",
              "EMF tokens · X-Ray traces · invocation log"),
}

# ── Group containers: (x, y, w, h, label, dashed) ────────────────────────────────
GROUPS = [
    (292, 92, 724, 672, "AWS Cloud · us-west-2", False),
    (836, 172, 164, 312, "AWS Lambda · Function URLs", True),
    (316, 652, 540, 108, "Observability · control plane", True),
]

# ── Edges: (x1, y1, x2, y2, kind, label) — kind: req | id | sup ──────────────────
EDGES = [
    (96, 300, 172, 300, "req", ""),
    (226, 300, 404, 300, "req", "user JWT"),
    (456, 300, 622, 300, "req", "MCP (+ user JWT)"),
    (673, 293, 893, 229, "req", "SigV4"),
    (674, 302, 892, 316, "req", ""),
    (672, 310, 894, 400, "req", "OBO Bearer | X-API-Key"),
    (943, 402, 1227, 308, "req", "OAUTH | KEYPAIR_JWT"),
    (200, 178, 200, 274, "id", "issues user JWT"),
    (648, 272, 648, 76, "id", ""),  # gateway up, above the cloud boundary
    (648, 76, 200, 76, "id", "OBO token exchange"),  # across the top
    (200, 76, 200, 124, "id", ""),  # down into entra
    (419, 324, 371, 428, "sup", "ConverseStream"),
    (360, 478, 360, 550, "req", ""),  # model → guardrail (default-on; labelled by the shield node)
    (441, 324, 509, 476, "sup", "Retrieve"),
    (452, 314, 718, 486, "sup", "read / write"),
    (918, 436, 918, 554, "sup", "reads RSA key"),
    (430, 326, 430, 646, "sup", ""),  # runtime → observability band (EMF tokens · traces)
    (648, 326, 648, 646, "sup", ""),  # gateway → observability band (app logs · traces)
]

KIND = {  # stroke, width, dash, marker
    "req": ("#444441", 2.2, "", "ad"),
    "id": ("#185FA5", 1.6, "5 4", "ab"),
    "sup": ("#888780", 1.4, "", "ag"),
}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> None:
    W, H = 1380, 800
    out = [
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'font-family="Helvetica, Arial, sans-serif" role="img" aria-labelledby="t d">',
        '<title id="t">Order-triage AgentCore system architecture</title>',
        '<desc id="d">Left-to-right AWS architecture: an analyst signs into Microsoft '
        "Entra via the webapp and invokes the AgentCore Runtime with the user JWT; the "
        "Runtime streams to Bedrock (Nova Lite) behind a prompt-attack Guardrail and "
        "forwards the JWT to the AgentCore Gateway, which authorizes with Cedar and "
        "brokers per-user OBO, calling the SAP, order-actions and Snowflake Lambdas; "
        "Snowflake then enforces per-user row-level security. Runtime and Gateway also "
        "deliver logs, traces and per-turn token metrics to CloudWatch GenAI "
        "Observability.</desc>",
        "<defs>",
    ]
    for stroke, _w, _d, mid in KIND.values():
        out.append(
            f'<marker id="{mid}" markerUnits="userSpaceOnUse" markerWidth="11" '
            f'markerHeight="9" refX="9" refY="4" orient="auto">'
            f'<path d="M0,0 L10,4 L0,8 Z" fill="{stroke}"/></marker>'
        )
    out.append("</defs>")
    out.append(f'<rect x="8" y="8" width="{W - 16}" height="{H - 16}" rx="16" '
               'fill="#FFFFFF" stroke="#D3D1C7" stroke-width="1.5"/>')
    out.append(f'<text x="28" y="40" font-size="20" font-weight="500" fill="{INK}">'
               "Order-triage AgentCore — system architecture</text>")
    out.append(f'<text x="28" y="60" font-size="12" fill="{SUB}">Live request path, left '
               "to right — Entra-OBO · Cedar · Guardrail on the model path · CloudWatch "
               "telemetry (deployed us-west-2)</text>")

    # edge-type legend (top right)
    leg = [("req", "request"), ("id", "identity / token"), ("sup", "supporting")]
    lx = 1006
    for kind, lbl in leg:
        stroke, _w, dash, _m = KIND[kind]
        da = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<line x1="{lx}" y1="36" x2="{lx + 26}" y2="36" stroke="{stroke}" '
                   f'stroke-width="2"{da}/>')
        out.append(f'<text x="{lx + 32}" y="40" font-size="11" fill="{SUB}">{lbl}</text>')
        lx += 36 + 10 + len(lbl) * 6.2

    # groups
    for x, y, w, h, label, dashed in GROUPS:
        da = ' stroke-dasharray="4 4"' if dashed else ""
        col = "#879196" if dashed else INK
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="none" '
                   f'stroke="{col}" stroke-width="{1.2 if dashed else 1.6}"{da}/>')
        out.append(f'<text x="{x + 14}" y="{y + 22}" font-size="12.5" fill="{col}">'
                   f"{esc(label)}</text>")

    # edges + edge labels
    for x1, y1, x2, y2, kind, label in EDGES:
        stroke, wdt, dash, mid = KIND[kind]
        da = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
                   f'stroke-width="{wdt}"{da} marker-end="url(#{mid})"/>')
        if label:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 4
            col = stroke if kind == "id" else SUB
            wpx = len(label) * 5.4 + 8
            out.append(f'<rect x="{mx - wpx / 2:.0f}" y="{my - 11:.0f}" width="{wpx:.0f}" '
                       'height="15" fill="#FFFFFF" fill-opacity="0.92"/>')
            out.append(f'<text x="{mx:.0f}" y="{my:.0f}" font-size="10" text-anchor="middle" '
                       f'fill="{col}">{esc(label)}</text>')

    # nodes: icon + 2-line label (below by default, or to the left for top nodes
    # that have arrows entering and leaving vertically through their centre)
    for node in NODES.values():
        cx, cy, key, title, sub = node[:5]
        pos = node[5] if len(node) > 5 else "below"
        out.append(f'<image x="{cx - IC / 2:.0f}" y="{cy - IC / 2:.0f}" width="{IC}" '
                   f'height="{IC}" xlink:href="{URI[key]}"/>')
        if pos == "left":
            tx = cx - IC / 2 - 8
            out.append(f'<text x="{tx:.0f}" y="{cy - 3:.0f}" font-size="12.5" '
                       f'font-weight="500" text-anchor="end" fill="{INK}">{esc(title)}</text>')
            out.append(f'<text x="{tx:.0f}" y="{cy + 12:.0f}" font-size="10.5" '
                       f'text-anchor="end" fill="{SUB}">{esc(sub)}</text>')
        else:
            out.append(f'<text x="{cx}" y="{cy + IC / 2 + 16:.0f}" font-size="12.5" '
                       f'font-weight="500" text-anchor="middle" fill="{INK}">{esc(title)}</text>')
            out.append(f'<text x="{cx}" y="{cy + IC / 2 + 30:.0f}" font-size="10.5" '
                       f'text-anchor="middle" fill="{SUB}">{esc(sub)}</text>')

    out.append("</svg>")
    svg = "\n".join(out)

    here = Path(__file__).resolve().parent
    svg_path = here / "system-architecture.svg"
    svg_path.write_text(svg)
    print(f"wrote {svg_path} ({len(svg) // 1024} KB)")

    png_path = here / "system-architecture.png"
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", str(W * 2), "-h", str(H * 2),
                        str(svg_path), "-o", str(png_path)], check=True)
        print(f"wrote {png_path}")
    else:
        print("rsvg-convert not found — SVG written; regenerate the PNG separately.")


if __name__ == "__main__":
    main()

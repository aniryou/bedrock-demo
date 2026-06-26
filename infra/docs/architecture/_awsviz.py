#!/usr/bin/env python3
"""Shared renderer for the AWS-style architecture SVGs.

Ports the visual language of ``docs/architecture_diagram.py`` — left-to-right,
**official AWS icons** (base64-embedded so GitHub renders the SVG inline), rounded-rect
group zones, and the 3-kind edge legend (request / identity / supporting) — but makes
authoring declarative so the six plane diagrams stay consistent:

* a node carries a pixel **centre** ``(x, y)`` + an icon key + a 2-line label;
* an **edge references node KEYS** and a side anchor (``l r t b`` or corners ``tl tr bl br``);
  endpoints are computed from the nodes, so no edge coordinates are hand-typed;
* a **group spans a set of node keys** (auto bounding-box + padding) or an explicit bbox;
* edges may carry a **numbered step badge** (the dark circle from the hand-drawn diagrams).

Only the ``diagrams`` package is needed (for the icon PNGs); no Graphviz. The optional
PNG raster uses ``rsvg-convert`` (``brew install librsvg``) or ``qlmanage`` on macOS.
Edit the per-plane specs in ``generate.py`` and re-run; don't hand-edit the SVG.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import diagrams

# ── Official AWS (+ Azure / SaaS / on-prem) icons from the `diagrams` package ─────
_PARENT = Path(os.path.abspath(os.path.dirname(diagrams.__file__))).parent
_ICONS = {
    "user": ("diagrams.aws.general", "User"),
    "users": ("diagrams.aws.general", "Users"),
    "client": ("diagrams.aws.general", "Client"),
    "entra": ("diagrams.azure.identity", "ActiveDirectory"),
    "bedrock": ("diagrams.aws.ml", "Bedrock"),
    "apigw": ("diagrams.aws.network", "APIGateway"),
    "lambda": ("diagrams.aws.compute", "Lambda"),
    "snowflake": ("diagrams.saas.analytics", "Snowflake"),
    "db": ("diagrams.aws.database", "Database"),
    "secrets": ("diagrams.aws.security", "SecretsManager"),
    "shield": ("diagrams.aws.security", "Shield"),
    "iam": ("diagrams.aws.security", "IdentityAndAccessManagementIam"),
    "cloudwatch": ("diagrams.aws.management", "Cloudwatch"),
    "cwlogs": ("diagrams.aws.management", "CloudwatchLogs"),
    "alarm": ("diagrams.aws.management", "CloudwatchAlarm"),
    "xray": ("diagrams.aws.devtools", "XRay"),
    "sns": ("diagrams.aws.integration", "SimpleNotificationServiceSns"),
    "ses": ("diagrams.aws.engagement", "SimpleEmailServiceSes"),
    "ecr": ("diagrams.aws.compute", "EC2ContainerRegistry"),
    "s3": ("diagrams.aws.storage", "SimpleStorageServiceS3"),
    "ghactions": ("diagrams.onprem.ci", "GithubActions"),
    "python": ("diagrams.programming.language", "Python"),
}


def _data_uri(key: str) -> str:
    mod, cls = _ICONS[key]
    c = getattr(__import__(mod, fromlist=[cls]), cls)
    raw = Path(os.path.join(_PARENT, c._icon_dir, c._icon)).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


# cache the data-URIs lazily so a spec only pays for the icons it uses
_URI: dict[str, str] = {}


def uri(key: str) -> str:
    if key not in _URI:
        _URI[key] = _data_uri(key)
    return _URI[key]


INK = "#232F3E"   # AWS "squid ink" — node titles + cloud boundary
SUB = "#5F5E5A"   # subtitle / edge labels
IC = 52           # icon edge (px)
LBL_DROP = 38     # vertical room a 2-line "below" label needs under an icon
TITLE_DY = 17     # title baseline below the icon
SUB_DY = 33       # sub baseline below the icon (gap from title = SUB_DY - TITLE_DY)

KIND = {  # stroke, width, dash, marker-id
    "req": ("#444441", 2.2, "", "ad"),
    "id": ("#185FA5", 1.6, "5 4", "ab"),
    "sup": ("#888780", 1.4, "", "ag"),
}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _anchor(n: dict, side: str) -> tuple[float, float]:
    x, y, h = n["x"], n["y"], IC / 2
    return {
        "l": (x - h, y), "r": (x + h, y), "t": (x, y - h), "b": (x, y + h),
        "tl": (x - h, y - h), "tr": (x + h, y - h),
        "bl": (x - h, y + h), "br": (x + h, y + h),
        "c": (x, y),
    }[side]


def _auto_sides(s: dict, d: dict) -> tuple[str, str]:
    dx, dy = d["x"] - s["x"], d["y"] - s["y"]
    if abs(dx) >= abs(dy):
        return ("r", "l") if dx > 0 else ("l", "r")
    return ("b", "t") if dy > 0 else ("t", "b")


def _exit_axis(side: str, dx: float, dy: float) -> str:
    """'h' or 'v' — the axis an edge leaves / enters a node on (corners → dominant axis)."""
    if side in ("l", "r"):
        return "h"
    if side in ("t", "b"):
        return "v"
    return "h" if abs(dx) >= abs(dy) else "v"


def _ortho(x1: float, y1: float, ss: str, x2: float, y2: float, ds: str) -> list:
    """Right-angle (elbow) waypoints between two anchors, honouring their exit axes."""
    dx, dy = x2 - x1, y2 - y1
    so, do = _exit_axis(ss, dx, dy), _exit_axis(ds, -dx, -dy)
    if so == "h" and do == "h":      # H · V · H  — leave/enter horizontally, jog at the midpoint
        mx = (x1 + x2) / 2
        return [(mx, y1), (mx, y2)]
    if so == "v" and do == "v":      # V · H · V
        my = (y1 + y2) / 2
        return [(x1, my), (x2, my)]
    if so == "h":                    # H then V (single elbow)
        return [(x2, y1)]
    return [(x1, y2)]                # V then H (single elbow)


def render(spec: dict) -> str:
    W, H = spec["size"]
    nodes = spec["nodes"]
    out = [
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'font-family="Helvetica, Arial, sans-serif" role="img" aria-labelledby="t d">',
        f'<title id="t">{esc(spec["title"])}</title>',
        f'<desc id="d">{esc(spec.get("desc", spec["title"]))}</desc>',
        "<defs>",
    ]
    for stroke, _w, _dash, mid in KIND.values():
        out.append(
            f'<marker id="{mid}" markerUnits="userSpaceOnUse" markerWidth="11" '
            f'markerHeight="9" refX="9" refY="4" orient="auto">'
            f'<path d="M0,0 L10,4 L0,8 Z" fill="{stroke}"/></marker>'
        )
    out.append("</defs>")
    out.append(f'<rect x="8" y="8" width="{W - 16}" height="{H - 16}" rx="16" '
               'fill="#FFFFFF" stroke="#D3D1C7" stroke-width="1.5"/>')
    out.append(f'<text x="28" y="40" font-size="20" font-weight="500" fill="{INK}">'
               f'{esc(spec["title"])}</text>')
    if spec.get("subtitle"):
        out.append(f'<text x="28" y="60" font-size="12" fill="{SUB}">'
                   f'{esc(spec["subtitle"])}</text>')

    # edge-type legend (top right)
    leg = [("req", "request"), ("id", "identity / token"), ("sup", "supporting")]
    lx = W - 374
    for kind, lbl in leg:
        stroke, _w, dash, _m = KIND[kind]
        da = f' stroke-dasharray="{dash}"' if dash else ""
        out.append(f'<line x1="{lx}" y1="36" x2="{lx + 26}" y2="36" stroke="{stroke}" '
                   f'stroke-width="2"{da}/>')
        out.append(f'<text x="{lx + 32}" y="40" font-size="11" fill="{SUB}">{lbl}</text>')
        lx += 36 + 10 + len(lbl) * 6.2

    # ── groups (drawn first, behind everything) ──
    for g in spec.get("groups", []):
        if "bbox" in g:
            x, y, w, h = g["bbox"]
        else:
            keys = g["nodes"]
            xs = [nodes[k]["x"] for k in keys]
            ys = [nodes[k]["y"] for k in keys]
            pad = g.get("pad", 26)
            x = min(xs) - IC / 2 - pad
            y = min(ys) - IC / 2 - pad - 8           # room for the group label
            w = (max(xs) - min(xs)) + IC + 2 * pad
            h = (max(ys) - min(ys)) + IC + 2 * pad + LBL_DROP
        dashed = g.get("dashed", False)
        da = ' stroke-dasharray="4 4"' if dashed else ""
        col = "#879196" if dashed else INK
        out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="12" '
                   f'fill="none" stroke="{col}" stroke-width="{1.2 if dashed else 1.6}"{da}/>')
        out.append(f'<text x="{x + 14:.0f}" y="{y + 22:.0f}" font-size="12.5" fill="{col}">'
                   f'{esc(g["label"])}</text>')

    # ── edges (+ optional numbered badge) ──
    for e in spec.get("edges", []):
        s, d = nodes[e["s"]], nodes[e["d"]]
        ss, ds = e.get("ss"), e.get("ds")
        if not ss or not ds:
            a, b = _auto_sides(s, d)
            ss, ds = ss or a, ds or b
        x1, y1 = _anchor(s, ss)
        x2, y2 = _anchor(d, ds)
        kind = e.get("kind", "req")
        stroke, wdt, dash, mid = KIND[kind]
        da = f' stroke-dasharray="{dash}"' if dash else ""
        via = e.get("via")
        mids = via if via else _ortho(x1, y1, ss, x2, y2, ds)
        pts = [(x1, y1), *mids, (x2, y2)]
        # collapse zero-length legs (a same-row H·V·H elbow degenerates to a straight line)
        pts = [p for i, p in enumerate(pts) if i == 0
               or (round(p[0]), round(p[1])) != (round(pts[i - 1][0]), round(pts[i - 1][1]))]
        path = " ".join(f"{px:.0f},{py:.0f}" for px, py in pts)
        out.append(f'<polyline points="{path}" fill="none" stroke="{stroke}" '
                   f'stroke-width="{wdt}"{da} marker-end="url(#{mid})"/>')

        label = e.get("label", "")
        n = e.get("n")
        if label or n:
            if e.get("lp"):
                lx, ly = e["lp"]
            else:  # midpoint of the longest leg of the elbow route
                j = max(range(len(pts) - 1), key=lambda i:
                        (pts[i + 1][0] - pts[i][0]) ** 2 + (pts[i + 1][1] - pts[i][1]) ** 2)
                (ax, ay), (bx, by) = pts[j], pts[j + 1]
                lx, ly = (ax + bx) / 2, (ay + by) / 2 - 4
            tx = lx
            if label:
                wpx = len(label) * 5.4 + 8
                col = stroke if kind == "id" else SUB
                out.append(f'<rect x="{lx - wpx / 2:.0f}" y="{ly - 11:.0f}" width="{wpx:.0f}" '
                           'height="15" fill="#FFFFFF" fill-opacity="0.92"/>')
                out.append(f'<text x="{lx:.0f}" y="{ly:.0f}" font-size="10" text-anchor="middle" '
                           f'fill="{col}">{esc(label)}</text>')
                tx = lx - wpx / 2          # badge sits just left of the label box
            if n is not None:
                bx, by = tx - 11, ly - 4
                out.append(f'<circle cx="{bx:.0f}" cy="{by:.0f}" r="9" fill="{INK}"/>')
                out.append(f'<text x="{bx:.0f}" y="{by + 3.3:.0f}" font-size="10" '
                           f'font-weight="600" text-anchor="middle" fill="#FFFFFF">{n}</text>')

    # ── nodes: icon + 2-line label (below by default; left / right for stacked nodes) ──
    for n in nodes.values():
        cx, cy, key = n["x"], n["y"], n["icon"]
        title, sub, pos = n.get("title", ""), n.get("sub", ""), n.get("label", "below")
        out.append(f'<image x="{cx - IC / 2:.0f}" y="{cy - IC / 2:.0f}" width="{IC}" '
                   f'height="{IC}" xlink:href="{uri(key)}"/>')
        if pos in ("left", "right"):
            end = "end" if pos == "left" else "start"
            tx = cx - IC / 2 - 8 if pos == "left" else cx + IC / 2 + 8
            out.append(f'<text x="{tx:.0f}" y="{cy - 4:.0f}" font-size="12.5" font-weight="500" '
                       f'text-anchor="{end}" fill="{INK}">{esc(title)}</text>')
            if sub:
                out.append(f'<text x="{tx:.0f}" y="{cy + 13:.0f}" font-size="10.5" '
                           f'text-anchor="{end}" fill="{SUB}">{esc(sub)}</text>')
        else:
            out.append(f'<text x="{cx:.0f}" y="{cy + IC / 2 + TITLE_DY:.0f}" font-size="12.5" '
                       f'font-weight="500" text-anchor="middle" fill="{INK}">{esc(title)}</text>')
            if sub:
                out.append(f'<text x="{cx:.0f}" y="{cy + IC / 2 + SUB_DY:.0f}" font-size="10.5" '
                           f'text-anchor="middle" fill="{SUB}">{esc(sub)}</text>')

    out.append("</svg>")
    return "\n".join(out)


def write(spec: dict, out_dir: Path) -> Path:
    svg_path = out_dir / f'{spec["key"]}-architecture.svg'
    svg_path.write_text(render(spec))
    return svg_path

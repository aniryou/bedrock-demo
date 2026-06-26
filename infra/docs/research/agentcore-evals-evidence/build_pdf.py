#!/usr/bin/env python3
"""Render AGENTCORE-EVALS-STRANDS-INCOMPATIBILITY.md -> self-contained HTML for Chrome print-to-PDF."""
import base64, pathlib, re, markdown

ROOT = pathlib.Path("/Users/anilchoudhary/code/bedrock-demo")
md_path = ROOT / "AGENTCORE-EVALS-STRANDS-INCOMPATIBILITY.md"
img_path = ROOT / "agentcore-evals-evidence" / "failure-flow.png"
out_html = ROOT / "agentcore-evals-evidence" / "AGENTCORE-EVALS-STRANDS-INCOMPATIBILITY.html"

text = md_path.read_text()

html_body = markdown.markdown(
    text,
    extensions=["tables", "fenced_code", "codehilite", "sane_lists", "attr_list"],
    extension_configs={"codehilite": {"guess_lang": False, "noclasses": True}},
)

# Inline the figure as a data URI so the PDF is fully self-contained.
b64 = base64.b64encode(img_path.read_bytes()).decode()
data_uri = f"data:image/png;base64,{b64}"
html_body = re.sub(r'src="[^"]*failure-flow\.png"', f'src="{data_uri}"', html_body)

CSS = """
@page { size: Letter; margin: 0.7in 0.75in; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.5; color: #1a1a1a; max-width: 100%; }
h1 { font-size: 19pt; line-height: 1.25; border-bottom: 3px solid #137333; padding-bottom: 8px;
     margin: 0 0 14px; color: #0b3d12; }
h2 { font-size: 14pt; margin: 22px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #ddd; color: #c5221f; }
h3 { font-size: 11.5pt; margin: 16px 0 6px; color: #5f4100; }
p { margin: 7px 0; }
a { color: #1155cc; text-decoration: none; }
hr { border: none; border-top: 1px solid #ddd; margin: 18px 0; }
strong { color: #111; }
ul, ol { margin: 7px 0 7px 4px; padding-left: 20px; }
li { margin: 3px 0; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9pt; table-layout: fixed; }
th, td { border: 1px solid #cfcfcf; padding: 5px 8px; text-align: left; vertical-align: top;
         overflow-wrap: anywhere; word-break: break-word; }
th { background: #f1f3f4; font-weight: 600; }
tr:nth-child(even) td { background: #fafafa; }
code { font-family: "SF Mono", "Menlo", Consolas, monospace; font-size: 8.6pt;
       background: #f3f3f3; padding: 1px 4px; border-radius: 3px; overflow-wrap: anywhere; }
pre { background: #f7f8fa; border: 1px solid #e1e4e8; border-radius: 5px; padding: 10px 12px;
      font-size: 8.2pt; line-height: 1.42; overflow-x: hidden; white-space: pre-wrap;
      word-break: break-word; overflow-wrap: anywhere; page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: inherit; }
blockquote { margin: 10px 0; padding: 6px 14px; border-left: 4px solid #e8710a;
             background: #fffaf2; color: #4a3a1a; }
blockquote p { margin: 3px 0; }
img { display: block; margin: 14px auto; max-width: 100%; height: auto; page-break-inside: avoid;
      border: 1px solid #eee; }
h2, h3 { page-break-after: avoid; }
"""

html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>AgentCore Evaluations × Strands 1.44 incompatibility</title>
<style>{CSS}</style></head><body>{html_body}</body></html>"""

out_html.write_text(html)
print("wrote", out_html, f"({len(html)} bytes)")

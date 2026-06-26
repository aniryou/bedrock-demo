"""CloudWatch custom-widget Lambda: resolve the opaque Entra directory id (oid) to a display
name via Microsoft Graph AT RENDER TIME, so the dashboards read as human identities while stored
telemetry stays opaque (oid only — a PII-free GUID; the name lives only in this render path).

Two modes, chosen by the widget's `params.mode`:
- "leaderboard" (default): a top-N "Top actors by tokens" table from the actor_oid Contributor
  Insights rule (FinOps board).
- "audit": the per-turn model-invocation table with its actor column resolved (Governance board).

Custom-widget contract: CloudWatch invokes with the widget context and expects an HTML string.
A {"describe": true} event returns markdown docs. stdlib only (urllib) — no dependency layer.
"""

import html
import json
import os
import time
import urllib.parse
import urllib.request

import boto3

_GRAPH = "https://graph.microsoft.com/v1.0"
_RULE = os.environ["INSIGHT_RULE_NAME"]  # actor-oid Contributor Insights rule (leaderboard)
_SECRET = os.environ["GRAPH_SECRET_NAME"]  # SM secret JSON: {tenant_id, client_id, client_secret}
_LOGS_GROUP = os.environ.get("MODELINVOCATIONS_LOG_GROUP", "")  # model-invocation log (audit)
_MAX = int(os.environ.get("MAX_ACTORS", "10"))  # leaderboard cap — top-N only, never the long tail
_ANON = "order-triage"  # shared anonymous actor sentinel — excluded from the leaderboard
_HTTP_TIMEOUT = 8

_cw = boto3.client("cloudwatch")
_sm = boto3.client("secretsmanager")
_logs = boto3.client("logs")

_token = {"value": None, "exp": 0.0}  # module-scoped Graph token cache (one mint per ~hour)

DOCS = (
    "## Actor resolution\n"
    "Resolves the Entra directory id (`oid`) to a display name via Microsoft Graph at render "
    "time. `params.mode=leaderboard` ranks the top-10 actors by tokens; `params.mode=audit` "
    "resolves the per-turn model-invocation table's actor column. Stored telemetry stays opaque."
)

_TABLE_CSS = "width:100%;border-collapse:collapse;font-family:sans-serif;font-size:12px"


def _graph_token() -> str:
    now = time.time()
    if _token["value"] and _token["exp"] - 60 > now:
        return _token["value"]
    cfg = json.loads(_sm.get_secret_value(SecretId=_SECRET)["SecretString"])
    data = urllib.parse.urlencode(
        {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
    ).encode()
    url = f"https://login.microsoftonline.com/{cfg['tenant_id']}/oauth2/v2.0/token"
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=_HTTP_TIMEOUT) as r:
        tok = json.loads(r.read())
    _token["value"] = tok["access_token"]
    _token["exp"] = now + int(tok.get("expires_in", 3600))
    return _token["value"]


def _resolve(oids: list[str], token: str) -> dict[str, str]:
    """oid -> displayName via one Graph $batch (<=20/call). Unresolved oids are absent (the caller
    falls back to a short id), so a guest/service principal/deleted user never breaks the widget."""
    out: dict[str, str] = {}
    for i in range(0, len(oids), 20):
        chunk = oids[i : i + 20]
        reqs = [
            {"id": str(j), "method": "GET", "url": f"/users/{o}?$select=displayName,userPrincipalName"}
            for j, o in enumerate(chunk)
        ]
        req = urllib.request.Request(
            f"{_GRAPH}/$batch",
            data=json.dumps({"requests": reqs}).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as r:
            for resp in json.loads(r.read()).get("responses", []):
                if resp.get("status") == 200:
                    b = resp.get("body", {})
                    name = b.get("displayName") or b.get("userPrincipalName")
                    if name:
                        out[chunk[int(resp["id"])]] = name
    return out


def _window(ctx: dict) -> tuple[int, int]:
    tr = ctx.get("timeRange") or {}
    end_ms = tr.get("end") or int(time.time() * 1000)
    start_ms = tr.get("start") or (end_ms - 7 * 86400 * 1000)
    return int(start_ms / 1000), int(end_ms / 1000)


def _safe_resolve(oids: list[str], tag: str) -> dict[str, str]:
    try:
        return _resolve([o for o in oids if o], _graph_token())
    except Exception as exc:  # Graph/secret failure must not blank the widget — show raw ids
        print(f"actor-resolver({tag}): Graph resolution failed ({type(exc).__name__}); raw ids")
        return {}


# --- leaderboard mode --------------------------------------------------------
def _top_actors(ctx: dict) -> list[tuple[str, float]]:
    start, end = _window(ctx)
    report = _cw.get_insight_rule_report(
        RuleName=_RULE, StartTime=start, EndTime=end, Period=3600,
        MaxContributorCount=_MAX, Metrics=["Sum"],
    )
    rows = [(c["Keys"][0], c.get("ApproximateAggregateValue", 0)) for c in report.get("Contributors", [])]
    rows = [(oid, val) for oid, val in rows if oid and oid != _ANON]  # drop blank/anonymous
    return rows[:_MAX]  # top-N only — never the long tail


def _render_leaderboard(ctx: dict) -> str:
    rows = _top_actors(ctx)
    names = _safe_resolve([oid for oid, _ in rows], "leaderboard")
    if not rows:
        return (
            "<p style='font-family:sans-serif'>No actor token usage in range. "
            "Populates once the runtime emits <code>actor_oid</code> (redeploy the agent).</p>"
        )
    body = "".join(
        f"<tr><td>{rank}</td><td>{html.escape(names.get(oid) or f'oid:{oid[:8]}…')}</td>"
        f"<td style='text-align:right'>{int(val):,}</td></tr>"
        for rank, (oid, val) in enumerate(rows, 1)
    )
    return (
        f"<table style='{_TABLE_CSS}'><thead><tr><th style='text-align:left'>#</th>"
        "<th style='text-align:left'>Actor</th><th style='text-align:right'>Tokens</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


# --- audit mode --------------------------------------------------------------
_AUDIT_QUERY = (
    "fields @timestamp, modelId, requestMetadata.actor, requestMetadata.actor_oid, "
    "input.inputTokenCount as in_tok, output.outputTokenCount as out_tok, requestMetadata.turn as turn "
    "| sort @timestamp desc | limit 200"
)


def _logs_query(start: int, end: int) -> list[dict]:
    qid = _logs.start_query(
        logGroupName=_LOGS_GROUP, startTime=start, endTime=end, queryString=_AUDIT_QUERY, limit=200
    )["queryId"]
    res: dict = {"status": "Running", "results": []}
    for _ in range(24):  # ~12s poll budget
        res = _logs.get_query_results(queryId=qid)
        if res["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        time.sleep(0.5)
    return [{f["field"]: f["value"] for f in row} for row in res.get("results", [])]


def _audit_actor(row: dict, names: dict[str, str]) -> str:
    oid, sub = row.get("requestMetadata.actor_oid", ""), row.get("requestMetadata.actor", "")
    if oid and names.get(oid):
        return names[oid]
    if oid:
        return f"oid:{oid[:8]}…"
    return f"sub:{sub[:8]}…" if sub else "—"


def _render_audit(ctx: dict) -> str:
    if not _LOGS_GROUP:
        return "<p style='font-family:sans-serif'>audit mode: MODELINVOCATIONS_LOG_GROUP unset.</p>"
    rows = _logs_query(*_window(ctx))
    names = _safe_resolve(list({r.get("requestMetadata.actor_oid", "") for r in rows}), "audit")
    if not rows:
        return "<p style='font-family:sans-serif'>No model invocations in range.</p>"
    body = "".join(
        f"<tr><td>{html.escape((r.get('@timestamp') or '')[:19])}</td>"
        f"<td>{html.escape(_audit_actor(r, names))}</td>"
        f"<td>{html.escape((r.get('modelId') or '').split('/')[-1])}</td>"
        f"<td style='text-align:right'>{html.escape(r.get('in_tok', ''))}</td>"
        f"<td style='text-align:right'>{html.escape(r.get('out_tok', ''))}</td>"
        f"<td>{html.escape((r.get('turn') or '')[:8])}</td></tr>"
        for r in rows
    )
    return (
        f"<table style='{_TABLE_CSS}'><thead><tr><th style='text-align:left'>Time (UTC)</th>"
        "<th style='text-align:left'>Actor</th><th style='text-align:left'>Model</th>"
        "<th style='text-align:right'>In</th><th style='text-align:right'>Out</th>"
        "<th style='text-align:left'>Turn</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def handler(event, _context=None):
    if isinstance(event, dict) and event.get("describe"):
        return DOCS
    ctx = (event or {}).get("widgetContext", {}) if isinstance(event, dict) else {}
    mode = (ctx.get("params") or {}).get("mode", "leaderboard")
    return _render_audit(ctx) if mode == "audit" else _render_leaderboard(ctx)

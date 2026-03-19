#!/usr/bin/env python3
"""OpenCure Labs — Dashboard Server

Localhost web dashboard for monitoring agent runs, findings, and critiques.

Usage:
    python scripts/dashboard.py              # → http://localhost:8787
    python scripts/dashboard.py --port 9000  # custom port
"""

import argparse
import asyncio
import csv
import io
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

import psycopg2
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

DB_URL = os.environ.get("POSTGRES_URL", "dbname=opencurelabs port=5433")
logger = logging.getLogger("opencurelabs.dashboard")


@asynccontextmanager
async def lifespan(app):
    """Start background WebSocket broadcast task on startup."""
    asyncio.create_task(_broadcast_updates())
    yield


app = FastAPI(title="OpenCure Labs Dashboard", lifespan=lifespan)


def get_conn():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn


def table_exists(cur, table_name):
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        (table_name,),
    )
    return cur.fetchone()[0]


def query_stats(cur):
    stats = {}
    for tbl in ("agent_runs", "experiment_results", "critique_log", "discovered_sources", "pipeline_runs"):
        if table_exists(cur, tbl):
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")  # noqa: S608 — table name from hardcoded list
            stats[tbl] = cur.fetchone()[0]
        else:
            stats[tbl] = 0

    if table_exists(cur, "experiment_results"):
        cur.execute("SELECT COUNT(*) FROM experiment_results WHERE novel = TRUE")
        stats["novel_count"] = cur.fetchone()[0]
    else:
        stats["novel_count"] = 0

    if table_exists(cur, "agent_runs"):
        cur.execute("SELECT COUNT(*) FROM agent_runs WHERE status = 'running'")
        stats["running_agents"] = cur.fetchone()[0]
    else:
        stats["running_agents"] = 0

    return stats


def query_recent_runs(cur, limit=15):
    if not table_exists(cur, "agent_runs"):
        return []
    cur.execute(
        "SELECT id, agent_name, started_at, completed_at, status"
        " FROM agent_runs ORDER BY started_at DESC LIMIT %s",
        (limit,),
    )
    rows = cur.fetchall()
    results = []
    for rid, name, started, completed, status in rows:
        dur = ""
        if started and completed:
            delta = completed - started
            dur = f"{int(delta.total_seconds())}s"
        results.append({
            "id": rid,
            "agent": name,
            "started": started.strftime("%Y-%m-%d %H:%M:%S") if started else "—",
            "duration": dur or "—",
            "status": status or "unknown",
        })
    return results


def query_findings(cur, novel_only=False, limit=20):
    if not table_exists(cur, "experiment_results"):
        return []
    where = "WHERE e.novel = TRUE" if novel_only else ""
    cur.execute(
        f"SELECT e.id, e.result_type, e.result_data, e.novel, e.timestamp, p.pipeline_name"  # noqa: S608
        f" FROM experiment_results e"
        f" LEFT JOIN pipeline_runs p ON e.pipeline_run_id = p.id"
        f" {where}"
        f" ORDER BY e.timestamp DESC LIMIT %s",
        (limit,),
    )
    rows = cur.fetchall()
    results = []
    for rid, rtype, rdata, novel, ts, pipeline in rows:
        data_preview = ""
        if isinstance(rdata, dict):
            data_preview = json.dumps(rdata, default=str)[:200]
        elif isinstance(rdata, str):
            data_preview = rdata[:200]
        results.append({
            "id": rid,
            "type": rtype,
            "novel": novel,
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "—",
            "pipeline": pipeline or "—",
            "preview": data_preview,
        })
    return results


def query_critiques(cur, limit=10):
    if not table_exists(cur, "critique_log"):
        return []
    cur.execute(
        "SELECT c.id, c.reviewer, c.critique_json, c.timestamp, p.pipeline_name"
        " FROM critique_log c"
        " LEFT JOIN pipeline_runs p ON c.run_id = p.id"
        " ORDER BY c.timestamp DESC LIMIT %s",
        (limit,),
    )
    rows = cur.fetchall()
    results = []
    for cid, reviewer, crit, ts, pipeline in rows:
        scores = {}
        recommendation = "—"
        if isinstance(crit, str):
            try:
                crit = json.loads(crit)
            except json.JSONDecodeError:
                crit = {}
        if isinstance(crit, dict):
            for dim in ("scientific_logic", "statistical_validity", "interpretive_accuracy", "reproducibility"):
                if dim in crit:
                    scores[dim] = crit[dim]
            recommendation = crit.get("recommendation", "—")
        results.append({
            "id": cid,
            "reviewer": reviewer,
            "pipeline": pipeline or "—",
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "—",
            "scores": scores,
            "recommendation": recommendation,
        })
    return results


def query_sources(cur, limit=15):
    if not table_exists(cur, "discovered_sources"):
        return []
    cur.execute(
        "SELECT id, url, domain, discovered_by, discovered_at, validated, notes"
        " FROM discovered_sources ORDER BY discovered_at DESC LIMIT %s",
        (limit,),
    )
    rows = cur.fetchall()
    results = []
    for sid, url, domain, by, at, validated, notes in rows:
        results.append({
            "id": sid,
            "url": url or "—",
            "domain": domain or "—",
            "discovered_by": by or "—",
            "discovered_at": at.strftime("%Y-%m-%d %H:%M") if at else "—",
            "validated": validated,
            "notes": notes or "",
        })
    return results


def render_dashboard(stats, runs, findings, critiques, sources):
    """Generate the full HTML dashboard page."""

    def stat_card(label, value, color="#7aa2f7", subtitle=""):
        sub_html = f'<div class="stat-sub">{subtitle}</div>' if subtitle else ""
        return f"""
        <div class="stat-card">
            <div class="stat-value" style="color:{color}">{value}</div>
            <div class="stat-label">{label}</div>
            {sub_html}
        </div>"""

    def status_badge(status):
        colors = {"completed": "#57F287", "running": "#FEE75C", "failed": "#ED4245", "unknown": "#5865F2"}
        c = colors.get(status, "#5865F2")
        return f'<span class="badge" style="background:{c}20;color:{c};border:1px solid {c}40">{status}</span>'

    def novel_badge(is_novel):
        if is_novel:
            return '<span class="badge" style="background:#57F28720;color:#57F287;border:1px solid #57F28740">🆕 NOVEL</span>'
        return '<span class="badge" style="background:#5865F220;color:#5865F2;border:1px solid #5865F240">📊 replication</span>'

    def rec_badge(rec):
        colors = {"publish": "#57F287", "revise": "#FEE75C", "reject": "#ED4245"}
        c = colors.get(rec, "#5865F2")
        return f'<span class="badge" style="background:{c}20;color:{c};border:1px solid {c}40">{rec}</span>'

    def score_bar(score, max_score=10):
        pct = int((score / max_score) * 100)
        c = "#57F287" if score >= 7 else "#FEE75C" if score >= 4 else "#ED4245"
        return f'<div class="score-bar"><div class="score-fill" style="width:{pct}%;background:{c}"></div></div><span class="score-num">{score}/{max_score}</span>'

    # Build runs table rows
    run_rows = ""
    for r in runs:
        run_rows += f"""
        <tr>
            <td>{r['id']}</td>
            <td><strong>{r['agent']}</strong></td>
            <td>{status_badge(r['status'])}</td>
            <td>{r['started']}</td>
            <td>{r['duration']}</td>
        </tr>"""

    # Build findings rows
    finding_rows = ""
    for f in findings:
        finding_rows += f"""
        <tr>
            <td>{f['id']}</td>
            <td><strong>{f['type']}</strong></td>
            <td>{novel_badge(f['novel'])}</td>
            <td>{f['pipeline']}</td>
            <td>{f['timestamp']}</td>
            <td class="preview">{f['preview']}</td>
        </tr>"""

    # Build critique rows
    critique_rows = ""
    for c in critiques:
        scores_html = ""
        for dim, score in c["scores"].items():
            label = dim.replace("_", " ").title()
            scores_html += f'<div class="score-row"><span class="score-label">{label}</span>{score_bar(score)}</div>'
        critique_rows += f"""
        <tr>
            <td>{c['id']}</td>
            <td>{c['reviewer']}</td>
            <td>{c['pipeline']}</td>
            <td>{rec_badge(c['recommendation'])}</td>
            <td class="scores-cell">{scores_html}</td>
            <td>{c['timestamp']}</td>
        </tr>"""

    # Build sources rows
    source_rows = ""
    for s in sources:
        v_badge = '<span class="badge" style="background:#57F28720;color:#57F287">✓</span>' if s["validated"] else '<span class="badge" style="background:#FEE75C20;color:#FEE75C">○</span>'
        url_display = s["url"][:60] + "…" if len(s["url"]) > 60 else s["url"]
        source_rows += f"""
        <tr>
            <td>{s['id']}</td>
            <td>{v_badge}</td>
            <td>{s['domain']}</td>
            <td>{s['discovered_by']}</td>
            <td class="preview">{url_display}</td>
            <td>{s['discovered_at']}</td>
        </tr>"""

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Finding/source empty state
    no_findings = '<tr><td colspan="6" class="empty">No findings recorded yet. Run a pipeline to generate results.</td></tr>' if not findings else ""
    no_runs = '<tr><td colspan="5" class="empty">No agent runs recorded yet.</td></tr>' if not runs else ""
    no_critiques = '<tr><td colspan="6" class="empty">No critiques recorded yet.</td></tr>' if not critiques else ""
    no_sources = '<tr><td colspan="6" class="empty">No sources discovered yet.</td></tr>' if not sources else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<!-- WebSocket handles live updates — no meta-refresh needed -->
<title>OpenCure Labs — Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', -apple-system, system-ui, sans-serif;
    background: #0d1117; color: #c9d1d9;
    line-height: 1.5; padding: 24px;
  }}
  .header {{
    display: flex; align-items: center; gap: 16px;
    margin-bottom: 24px; padding-bottom: 16px;
    border-bottom: 1px solid #21262d;
  }}
  .header h1 {{ color: #7aa2f7; font-size: 24px; }}
  .header .ts {{ color: #484f58; font-size: 13px; margin-left: auto; }}
  .header .refresh {{ color: #484f58; font-size: 12px; }}
  .stats {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px; margin-bottom: 32px;
  }}
  .stat-card {{
    background: #161b22; border: 1px solid #21262d; border-radius: 8px;
    padding: 20px; text-align: center;
  }}
  .stat-value {{ font-size: 32px; font-weight: 700; }}
  .stat-label {{ font-size: 13px; color: #8b949e; margin-top: 4px; }}
  .stat-sub {{ font-size: 12px; color: #484f58; margin-top: 2px; }}
  .section {{ margin-bottom: 32px; }}
  .section h2 {{
    color: #c9d1d9; font-size: 16px; margin-bottom: 12px;
    padding-bottom: 8px; border-bottom: 1px solid #21262d;
  }}
  table {{
    width: 100%; border-collapse: collapse;
    background: #161b22; border-radius: 8px; overflow: hidden;
  }}
  th {{
    background: #1c2128; color: #8b949e; font-weight: 600;
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
    padding: 10px 16px; text-align: left;
  }}
  td {{ padding: 10px 16px; border-top: 1px solid #21262d; font-size: 14px; }}
  tr:hover {{ background: #1c2128; }}
  .badge {{
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 12px; font-weight: 600;
  }}
  .preview {{
    max-width: 300px; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; font-size: 12px; color: #8b949e;
    font-family: monospace;
  }}
  .empty {{ text-align: center; color: #484f58; padding: 32px; font-style: italic; }}
  .score-row {{ display: flex; align-items: center; gap: 8px; margin: 2px 0; }}
  .score-label {{ font-size: 11px; color: #8b949e; width: 120px; }}
  .score-bar {{
    width: 80px; height: 6px; background: #21262d; border-radius: 3px; overflow: hidden;
  }}
  .score-fill {{ height: 100%; border-radius: 3px; }}
  .score-num {{ font-size: 11px; color: #8b949e; width: 40px; }}
  .scores-cell {{ min-width: 260px; }}
  .toolbar {{
    display: flex; align-items: center; gap: 12px; margin-bottom: 12px;
    flex-wrap: wrap;
  }}
  .toolbar select, .toolbar button {{
    background: #161b22; border: 1px solid #30363d; color: #c9d1d9;
    border-radius: 6px; padding: 6px 12px; font-size: 13px; cursor: pointer;
  }}
  .toolbar button:hover {{ border-color: #7aa2f7; }}
  .ws-dot {{
    width: 8px; height: 8px; border-radius: 50%; display: inline-block;
    margin-right: 4px; background: #484f58;
  }}
  .ws-dot.connected {{ background: #57F287; }}
</style>
</head>
<body>

<div class="header">
  <h1>🧬 OpenCure Labs</h1>
  <span class="ts">Dashboard · {now}</span>
  <span class="refresh"><span class="ws-dot" id="ws-dot"></span>live</span>
</div>

<div class="stats">
  {stat_card("Agent Runs", stats["agent_runs"], "#7aa2f7", f'{stats["running_agents"]} running')}
  {stat_card("Pipeline Runs", stats["pipeline_runs"], "#bb9af7")}
  {stat_card("Results", stats["experiment_results"], "#5865F2")}
  {stat_card("Novel Findings", stats["novel_count"], "#57F287")}
  {stat_card("Critiques", stats["critique_log"], "#FEE75C")}
  {stat_card("Sources", stats["discovered_sources"], "#c0caf5")}
</div>

<div class="section">
  <h2>🔬 Experiment Results</h2>
  <div class="toolbar">
    <select id="novelFilter" onchange="filterFindings()">
      <option value="all">All results</option>
      <option value="novel">Novel only</option>
      <option value="replication">Replications only</option>
    </select>
    <button onclick="window.location='/api/export/findings?fmt=csv'">⬇ CSV</button>
    <button onclick="window.location='/api/export/findings?fmt=json'">⬇ JSON</button>
  </div>
  <table id="findings-table">
    <thead><tr><th>ID</th><th>Type</th><th>Status</th><th>Pipeline</th><th>Time</th><th>Data</th></tr></thead>
    <tbody>{finding_rows or no_findings}</tbody>
  </table>
</div>

<div class="section">
  <h2>🤖 Agent Runs</h2>
  <table>
    <thead><tr><th>ID</th><th>Agent</th><th>Status</th><th>Started</th><th>Duration</th></tr></thead>
    <tbody>{run_rows or no_runs}</tbody>
  </table>
</div>

<div class="section">
  <h2>📋 Critiques</h2>
  <div class="toolbar">
    <button onclick="window.location='/api/export/critiques?fmt=csv'">⬇ CSV</button>
    <button onclick="window.location='/api/export/critiques?fmt=json'">⬇ JSON</button>
  </div>
  <table>
    <thead><tr><th>ID</th><th>Reviewer</th><th>Pipeline</th><th>Recommendation</th><th>Scores</th><th>Time</th></tr></thead>
    <tbody>{critique_rows or no_critiques}</tbody>
  </table>
</div>

<div class="section">
  <h2>📡 Discovered Sources</h2>
  <table>
    <thead><tr><th>ID</th><th>Valid</th><th>Domain</th><th>Found By</th><th>URL</th><th>Date</th></tr></thead>
    <tbody>{source_rows or no_sources}</tbody>
  </table>
</div>

<script>
// ── WebSocket live updates ──
(function() {{
  const dot = document.getElementById('ws-dot');
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  let ws;
  function connect() {{
    ws = new WebSocket(proto + '//' + location.host + '/ws');
    ws.onopen = () => {{ dot.classList.add('connected'); }};
    ws.onclose = () => {{ dot.classList.remove('connected'); setTimeout(connect, 3000); }};
    ws.onmessage = (e) => {{
      const msg = JSON.parse(e.data);
      if (msg.type === 'stats') {{
        // Update stat cards with new values
        const cards = document.querySelectorAll('.stat-card');
        const keys = ['agent_runs', 'pipeline_runs', 'experiment_results', 'novel_count', 'critique_log', 'discovered_sources'];
        keys.forEach((k, i) => {{
          if (cards[i]) cards[i].querySelector('.stat-value').textContent = msg.data[k] ?? 0;
        }});
      }}
    }};
  }}
  connect();
}})();

// ── Filter findings table ──
function filterFindings() {{
  const filter = document.getElementById('novelFilter').value;
  const rows = document.querySelectorAll('#findings-table tbody tr');
  rows.forEach(row => {{
    if (row.classList.contains('empty')) return;
    const badges = row.querySelectorAll('.badge');
    if (filter === 'all') {{ row.style.display = ''; return; }}
    const isNovel = Array.from(badges).some(b => b.textContent.includes('NOVEL'));
    row.style.display = (filter === 'novel') === isNovel ? '' : 'none';
  }});
}}
</script>

</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    conn = get_conn()
    cur = conn.cursor()
    stats = query_stats(cur)
    runs = query_recent_runs(cur)
    findings = query_findings(cur)
    critiques = query_critiques(cur)
    sources = query_sources(cur)
    cur.close()
    conn.close()
    return render_dashboard(stats, runs, findings, critiques, sources)


@app.get("/api/stats")
async def api_stats():
    conn = get_conn()
    cur = conn.cursor()
    stats = query_stats(cur)
    cur.close()
    conn.close()
    return stats


@app.get("/api/findings")
async def api_findings(novel_only: bool = False, limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    data = query_findings(cur, novel_only=novel_only, limit=min(limit, 200))
    cur.close()
    conn.close()
    return data


@app.get("/api/runs")
async def api_runs(limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    data = query_recent_runs(cur, limit=min(limit, 200))
    cur.close()
    conn.close()
    return data


@app.get("/api/critiques")
async def api_critiques(limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    data = query_critiques(cur, limit=min(limit, 200))
    cur.close()
    conn.close()
    return data


@app.get("/api/sources")
async def api_sources(limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    data = query_sources(cur, limit=min(limit, 200))
    cur.close()
    conn.close()
    return data


@app.get("/api/export/findings")
async def export_findings(
    fmt: str = Query("json", pattern="^(json|csv)$"),
    novel_only: bool = False,
    limit: int = 500,
):
    conn = get_conn()
    cur = conn.cursor()
    data = query_findings(cur, novel_only=novel_only, limit=min(limit, 10000))
    cur.close()
    conn.close()
    if fmt == "csv":
        buf = io.StringIO()
        if data:
            writer = csv.DictWriter(buf, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        return StreamingResponse(
            io.BytesIO(buf.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=findings.csv"},
        )
    return data


@app.get("/api/export/critiques")
async def export_critiques(fmt: str = Query("json", pattern="^(json|csv)$"), limit: int = 500):
    conn = get_conn()
    cur = conn.cursor()
    data = query_critiques(cur, limit=min(limit, 10000))
    cur.close()
    conn.close()
    if fmt == "csv":
        buf = io.StringIO()
        rows = []
        for c in data:
            row = {k: v for k, v in c.items() if k != "scores"}
            for dim, score in c.get("scores", {}).items():
                row[dim] = score
            rows.append(row)
        if rows:
            writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return StreamingResponse(
            io.BytesIO(buf.getvalue().encode()),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=critiques.csv"},
        )
    return data


# ── WebSocket for real-time updates ──────────────────────────────────────────

_ws_clients: set[WebSocket] = set()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global _ws_clients
    await ws.accept()
    _ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # keep connection alive
    except WebSocketDisconnect:
        _ws_clients.discard(ws)


async def _broadcast_updates():
    """Background task: poll DB every 5s and push changes to WebSocket clients."""
    global _ws_clients
    prev_stats = None
    while True:
        await asyncio.sleep(5)
        if not _ws_clients:
            continue
        try:
            conn = get_conn()
            cur = conn.cursor()
            stats = query_stats(cur)
            cur.close()
            conn.close()
            if stats != prev_stats:
                prev_stats = stats
                payload = json.dumps({"type": "stats", "data": stats})
                dead = set()
                for ws in _ws_clients:
                    try:
                        await ws.send_text(payload)
                    except Exception:
                        dead.add(ws)
                _ws_clients -= dead
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="OpenCure Labs Dashboard")
    parser.add_argument("--port", type=int, default=8787, help="Port (default: 8787)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    args = parser.parse_args()
    print(f"🧬 OpenCure Labs Dashboard → http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

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
from pathlib import Path

import psycopg2
import psycopg2.pool
from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
import uvicorn

DB_URL = os.environ.get("POSTGRES_URL", "dbname=opencurelabs port=5433")
logger = logging.getLogger("opencurelabs.dashboard")

# Connection pool — lazily initialized
_pool = None


def _get_pool():
    """Return a threaded connection pool, creating it on first call."""
    global _pool
    if _pool is None or _pool.closed:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, DB_URL)
    return _pool


def get_conn():
    """Get a connection from the pool with autocommit enabled."""
    conn = _get_pool().getconn()
    conn.autocommit = True
    return conn


def put_conn(conn):
    """Return a connection to the pool."""
    try:
        _get_pool().putconn(conn)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app):
    """Start background WebSocket broadcast task on startup; close pool on shutdown."""
    asyncio.create_task(_broadcast_updates())
    yield
    if _pool and not _pool.closed:
        _pool.closeall()


app = FastAPI(title="OpenCure Labs Dashboard", lifespan=lifespan)

# Rate limiting — 60 requests/minute per IP
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"error": "Rate limit exceeded. Try again later."})


# CORS — allow any origin for public dashboard
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@app.get("/logo-v3.png")
async def serve_logo():
    logo_path = os.path.join(PROJECT_ROOT, "OpenCureLabs.png")
    if os.path.exists(logo_path):
        return FileResponse(logo_path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    return HTMLResponse(status_code=404)


@app.get("/health")
async def health():
    """Health check for load balancers and uptime monitors."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        put_conn(conn)
        return {"status": "healthy", "database": "connected"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "database": "disconnected"})


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
        f"SELECT e.id, e.result_type, e.result_data, e.novel, e.timestamp, p.pipeline_name,"  # noqa: S608
        f" COALESCE(e.status, 'published') as status"
        f" FROM experiment_results e"
        f" LEFT JOIN pipeline_runs p ON e.pipeline_run_id = p.id"
        f" {where}"
        f" ORDER BY e.timestamp DESC LIMIT %s",
        (limit,),
    )
    rows = cur.fetchall()
    results = []
    for rid, rtype, rdata, novel, ts, pipeline, status in rows:
        data_preview = ""
        if isinstance(rdata, dict):
            data_preview = json.dumps(rdata, default=str)[:200]
        elif isinstance(rdata, str):
            data_preview = rdata[:200]
        results.append({
            "id": rid,
            "type": rtype,
            "novel": novel,
            "status": status,
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
                    raw = crit[dim]
                    if isinstance(raw, dict):
                        scores[dim] = raw.get("score", 0)
                    else:
                        try:
                            scores[dim] = float(raw)
                        except (TypeError, ValueError):
                            scores[dim] = 0
            recommendation = crit.get("recommendation", "—")
            # Grok literature reviews use 'summary' instead of scored dimensions
            if "summary" in crit and not scores:
                overall = crit.get("overall_score", crit.get("score"))
                if overall is not None:
                    scores["overall"] = overall
                recommendation = crit.get("recommendation", "literature")
        results.append({
            "id": cid,
            "reviewer": reviewer,
            "pipeline": pipeline or "—",
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "—",
            "scores": scores,
            "recommendation": recommendation,
            "summary": crit.get("summary", "") if isinstance(crit, dict) else "",
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


def query_activity_log(cur, limit=30):
    """Unified timeline of all events across tables."""
    events = []
    if table_exists(cur, "agent_runs"):
        cur.execute(
            "SELECT 'agent' as kind, agent_name as label, status as detail, started_at as ts"
            " FROM agent_runs ORDER BY started_at DESC LIMIT %s",
            (limit,),
        )
        for kind, label, detail, ts in cur.fetchall():
            icon = {"completed": "✅", "running": "⏳", "failed": "❌"}.get(detail, "🤖")
            events.append({"ts": ts, "icon": icon, "text": f"{label} — {detail}"})

    if table_exists(cur, "critique_log"):
        cur.execute(
            "SELECT 'critique' as kind, reviewer as label, critique_json as detail, timestamp as ts"
            " FROM critique_log ORDER BY timestamp DESC LIMIT %s",
            (limit,),
        )
        for kind, label, crit, ts in cur.fetchall():
            rec = ""
            if isinstance(crit, dict):
                rec = crit.get("recommendation", "")
            elif isinstance(crit, str):
                try:
                    rec = json.loads(crit).get("recommendation", "")
                except (json.JSONDecodeError, AttributeError):
                    pass
            icon = {"publish": "📗", "revise": "📙", "reject": "📕"}.get(rec, "📋")
            events.append({"ts": ts, "icon": icon, "text": f"{label} → {rec or 'review'}"})

    if table_exists(cur, "experiment_results"):
        cur.execute(
            "SELECT result_type, novel, COALESCE(status, 'published'), timestamp"
            " FROM experiment_results ORDER BY timestamp DESC LIMIT %s",
            (limit,),
        )
        for rtype, novel, status, ts in cur.fetchall():
            icon = "🚫" if status == "blocked" else ("🆕" if novel else "🔬")
            events.append({"ts": ts, "icon": icon, "text": f"{rtype} — {status}" + (" (novel)" if novel else "")})

    events.sort(key=lambda e: e["ts"] or datetime.min, reverse=True)
    return events[:limit]


def query_vast_instances():
    """Query Vast.ai API for active instances."""
    vast_key = os.environ.get("VAST_AI_KEY", "")
    if not vast_key:
        return {"count": 0, "instances": [], "cost_per_hour": 0}
    try:
        import requests as _req
        resp = _req.get(
            "https://console.vast.ai/api/v0/instances/",
            headers={"Authorization": f"Bearer {vast_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        instances = data.get("instances", data) if isinstance(data, dict) else data
        if not isinstance(instances, list):
            instances = []
        active = [i for i in instances if i.get("actual_status") in ("running", "loading")]
        total_cost = sum(i.get("dph_total", 0) for i in active)
        return {
            "count": len(active),
            "instances": [
                {
                    "id": i.get("id"),
                    "gpu": i.get("gpu_name", "?"),
                    "num_gpus": i.get("num_gpus", 1),
                    "status": i.get("actual_status", "?"),
                    "cost_hr": round(i.get("dph_total", 0), 3),
                }
                for i in active
            ],
            "cost_per_hour": round(total_cost, 3),
        }
    except Exception:
        return {"count": 0, "instances": [], "cost_per_hour": 0, "spent": 0, "budget": 0}


def query_vast_spend():
    """Get total Vast.ai spend and budget from DB."""
    budget = float(os.environ.get("VAST_AI_BUDGET", "0"))
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend")
        spent = float(cur.fetchone()[0])
        cur.close()
        put_conn(conn)
        return {"spent": round(spent, 2), "budget": budget, "remaining": round(max(0, budget - spent), 2) if budget else None}
    except Exception:
        return {"spent": 0, "budget": budget, "remaining": None}


def render_dashboard(stats, runs, findings, critiques, sources, activity=None, vast_info=None):
    """Generate the full HTML dashboard page."""

    def stat_card(label, value, color="#7aa2f7", subtitle=""):
        pulse_class = ' running' if 'running' in subtitle and not subtitle.startswith('0') else ''
        sub_html = f'<div class="stat-sub{pulse_class}">{subtitle}</div>' if subtitle else ""
        return f"""
        <div class="stat-card">
            <div class="stat-value" style="color:{color}">{value}</div>
            <div class="stat-label">{label}</div>
            {sub_html}
        </div>"""

    def status_badge(status):
        colors = {"completed": "#2ea043", "running": "#FEE75C", "failed": "#ED4245", "unknown": "#5865F2", "blocked": "#ED4245", "published": "#2ea043"}
        c = colors.get(status, "#5865F2")
        icon = {"blocked": "🚫 ", "published": "✅ ", "running": "⏳ "}.get(status, "")
        return f'<span class="badge" style="background:{c}20;color:{c};border:1px solid {c}40">{icon}{status}</span>'

    def novel_badge(is_novel):
        if is_novel:
            return '<span class="badge" style="background:#2ea04320;color:#2ea043;border:1px solid #2ea04340">🆕 NOVEL</span>'
        return '<span class="badge" style="background:#5865F220;color:#5865F2;border:1px solid #5865F240">📊 replication</span>'

    def rec_badge(rec):
        colors = {"publish": "#2ea043", "revise": "#FEE75C", "reject": "#ED4245"}
        c = colors.get(rec, "#5865F2")
        return f'<span class="badge" style="background:{c}20;color:{c};border:1px solid {c}40">{rec}</span>'

    def score_bar(score, max_score=10):
        if isinstance(score, dict):
            score = score.get("score", 0)
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0
        pct = int((score / max_score) * 100)
        c = "#2ea043" if score >= 7 else "#FEE75C" if score >= 4 else "#ED4245"
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
            <td>{status_badge(f.get('status', 'published'))}</td>
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
            if isinstance(score, dict):
                score = score.get("score", 0)
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0
            label = dim.replace("_", " ").title()
            scores_html += f'<div class="score-row"><span class="score-label">{label}</span>{score_bar(score)}</div>'
        # Show summary snippet for Grok reviews that have no scored dimensions
        if not c["scores"] and c.get("summary"):
            snippet = c["summary"][:120] + "…" if len(c.get("summary", "")) > 120 else c.get("summary", "")
            scores_html = f'<div class="score-label" style="font-style:italic;max-width:260px">{snippet}</div>'
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
        v_badge = '<span class="badge" style="background:#2ea04320;color:#2ea043">✓</span>' if s["validated"] else '<span class="badge" style="background:#FEE75C20;color:#FEE75C">○</span>'
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

    # Activity log entries
    activity_items = activity or []
    if activity_items:
        activity_html = ""
        for evt in activity_items:
            ts_str = evt["ts"].strftime("%H:%M:%S") if evt["ts"] else "—"
            activity_html += f'<div class="activity-item"><span class="activity-ts">{ts_str}</span><span class="activity-icon">{evt["icon"]}</span><span class="activity-text">{evt["text"]}</span></div>'
    else:
        activity_html = '<div class="empty">No activity recorded yet.</div>'

    # Finding/source empty state
    no_findings = '<tr><td colspan="7" class="empty">No findings recorded yet. Run a pipeline to generate results.</td></tr>' if not findings else ""
    no_runs = '<tr><td colspan="5" class="empty">No agent runs recorded yet.</td></tr>' if not runs else ""
    no_critiques = '<tr><td colspan="6" class="empty">No critiques recorded yet.</td></tr>' if not critiques else ""
    no_sources = '<tr><td colspan="6" class="empty">No sources discovered yet.</td></tr>' if not sources else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
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
  .header-logo {{ width: 96px; height: 96px; border-radius: 50%; }}
  .header .ts {{ color: #484f58; font-size: 13px; margin-left: auto; }}
  .header .refresh {{ color: #484f58; font-size: 12px; }}
  .discord-link {{
    background: #5865F220; color: #5865F2; border: 1px solid #5865F240;
    padding: 4px 12px; border-radius: 2px; font-size: 13px; font-weight: 600;
    text-decoration: none; transition: background 0.2s;
  }}
  .discord-link:hover {{ background: #5865F240; }}
  .stats {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px; margin-bottom: 32px;
  }}
  .stat-card {{
    background: #161b22; border: 1px solid #21262d; border-radius: 2px;
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
    background: #161b22; border-radius: 2px; overflow: hidden;
  }}
  th {{
    background: #1c2128; color: #8b949e; font-weight: 600;
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
    padding: 10px 16px; text-align: left;
  }}
  td {{ padding: 10px 16px; border-top: 1px solid #21262d; font-size: 14px; }}
  tr:hover {{ background: #1c2128; }}
  .badge {{
    display: inline-block; padding: 2px 10px; border-radius: 2px;
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
    width: 100px; height: 8px; background: #21262d; border-radius: 2px; overflow: hidden;
  }}
  .score-fill {{ height: 100%; border-radius: 2px; transition: width 0.3s ease; }}
  .score-num {{ font-size: 11px; color: #8b949e; width: 40px; }}
  .scores-cell {{ min-width: 260px; }}
  .toolbar {{
    display: flex; align-items: center; gap: 12px; margin-bottom: 12px;
    flex-wrap: wrap;
  }}
  .toolbar select, .toolbar button {{
    background: #161b22; border: 1px solid #30363d; color: #c9d1d9;
    border-radius: 2px; padding: 6px 12px; font-size: 13px; cursor: pointer;
  }}
  .toolbar button:hover {{ border-color: #7aa2f7; }}
  .ws-dot {{
    width: 8px; height: 8px; border-radius: 50%; display: inline-block;
    margin-right: 4px; background: #484f58;
  }}
  .ws-dot.connected {{ background: #2ea043; }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
  .stat-sub.running {{ color: #FEE75C !important; animation: pulse 2s ease-in-out infinite; }}
  .activity-log {{
    background: #161b22; border: 1px solid #21262d; border-radius: 2px;
    padding: 12px; max-height: 320px; overflow-y: auto;
  }}
  .activity-item {{
    display: flex; align-items: center; gap: 10px; padding: 6px 8px;
    border-bottom: 1px solid #21262d; font-size: 13px;
  }}
  .activity-item:last-child {{ border-bottom: none; }}
  .activity-ts {{ color: #484f58; font-family: monospace; font-size: 12px; width: 70px; flex-shrink: 0; }}
  .activity-icon {{ font-size: 14px; width: 20px; text-align: center; flex-shrink: 0; }}
  .activity-text {{ color: #c9d1d9; }}
  /* ── D3 Chart Styles ── */
  .charts-row {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px;
  }}
  @media (max-width: 900px) {{ .charts-row {{ grid-template-columns: 1fr; }} }}
  .chart-card {{
    background: #161b22; border: 1px solid #21262d; border-radius: 2px;
    padding: 16px; min-height: 280px; position: relative;
  }}
  .chart-card h3 {{
    color: #8b949e; font-size: 13px; text-transform: uppercase;
    letter-spacing: 0.5px; margin-bottom: 12px; font-weight: 600;
  }}
  .chart-card svg {{ display: block; margin: 0 auto; }}
  .d3-tooltip {{
    position: fixed; pointer-events: none; z-index: 1000;
    background: #1c2128ee; border: 1px solid #30363d; border-radius: 2px;
    padding: 8px 12px; font-size: 12px; color: #c9d1d9;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4); opacity: 0; transition: opacity 0.15s;
    max-width: 260px;
  }}
  .d3-tooltip.visible {{ opacity: 1; }}
  .chart-legend {{
    display: flex; gap: 16px; justify-content: center;
    flex-wrap: wrap; margin-top: 8px; font-size: 11px; color: #8b949e;
  }}
  .chart-legend span {{ display: flex; align-items: center; gap: 4px; }}
  .legend-dot {{
    width: 10px; height: 10px; border-radius: 2px; display: inline-block;
  }}
  .chart-empty {{
    display: flex; align-items: center; justify-content: center;
    height: 200px; color: #484f58; font-style: italic; font-size: 14px;
  }}
</style>
</head>
<body>

<div class="header">
  <img src="/logo-v3.png" alt="OpenCure Labs" class="header-logo">
  <h1>OpenCure Labs</h1>
  <a href="https://discord.com/channels/1484240467477659941/1484241124104081680" target="_blank" class="discord-link" title="Discord Server">💬 Discord</a>
  <span class="ts">Dashboard · {now}</span>
  <span class="refresh"><span class="ws-dot" id="ws-dot"></span>live</span>
</div>

<div class="stats">
  {stat_card("Agent Runs", stats["agent_runs"], "#7aa2f7", f'{stats["running_agents"]} running')}
  {stat_card("Pipeline Runs", stats["pipeline_runs"], "#bb9af7")}
  {stat_card("Results", stats["experiment_results"], "#5865F2")}
  {stat_card("Novel Findings", stats["novel_count"], "#2ea043")}
  {stat_card("Critiques", stats["critique_log"], "#FEE75C")}
  {stat_card("Sources", stats["discovered_sources"], "#c0caf5")}
  {stat_card("Vast.ai", (vast_info or {{}}).get('count', 0), '#ff9e64', f'${(vast_info or {{}}).get("cost_per_hour", 0):.3f}/hr' if (vast_info or {{}}).get('count', 0) else 'idle')}
</div>

<!-- Charts Row 1: Agent Donut + Results by Type -->
<div class="charts-row">
  <div class="chart-card">
    <h3>Agent Activity</h3>
    <div id="donut-chart"></div>
  </div>
  <div class="chart-card">
    <h3>Results by Type</h3>
    <div id="results-chart"></div>
  </div>
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
    <thead><tr><th>ID</th><th>Type</th><th>Status</th><th>Novelty</th><th>Pipeline</th><th>Time</th><th>Data</th></tr></thead>
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

<!-- Charts Row 2: Pipeline Timeline + Critique Radar -->
<div class="charts-row">
  <div class="chart-card">
    <h3>Pipeline Timeline</h3>
    <div id="timeline-chart"></div>
  </div>
  <div class="chart-card">
    <h3>Critique Scores</h3>
    <div id="radar-chart"></div>
    <div class="chart-legend" id="radar-legend"></div>
  </div>
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

<!-- Chart Row 3: Score Trend Line (full width) -->
<div class="charts-row" style="grid-template-columns:1fr">
  <div class="chart-card">
    <h3>Score Trends Over Time</h3>
    <div id="trend-chart"></div>
    <div class="chart-legend" id="trend-legend"></div>
  </div>
</div>

<div class="section">
  <h2>📜 Activity Log</h2>
  <div class="activity-log">
    {activity_html}
  </div>
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
        // Update running count subtitle
        const sub = cards[0]?.querySelector('.stat-sub');
        if (sub) {{
          const running = msg.data.running_agents ?? 0;
          sub.textContent = running + ' running';
          sub.style.color = running > 0 ? '#FEE75C' : '#484f58';
        }}
        // If counts changed, reload tables after a short delay
        if (msg.data._changed) {{
          setTimeout(() => location.reload(), 1000);
        }}
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

// ── D3 Charts ──
const COLORS = {{
  blue: '#7aa2f7', green: '#2ea043', yellow: '#FEE75C', red: '#ED4245',
  purple: '#bb9af7', indigo: '#5865F2', cyan: '#7dcfff', orange: '#ff9e64',
  bg: '#161b22', border: '#21262d', text: '#8b949e', faint: '#484f58'
}};

const tooltip = d3.select('body').append('div').attr('class', 'd3-tooltip');
function showTip(e, html) {{
  tooltip.html(html).classed('visible', true)
    .style('left', (e.clientX + 12) + 'px').style('top', (e.clientY - 10) + 'px');
}}
function hideTip() {{ tooltip.classed('visible', false); }}

// ── 1. Agent Activity Donut ──
function drawDonut(data) {{
  const el = document.getElementById('donut-chart');
  el.innerHTML = '';
  if (!data.length) {{ el.innerHTML = '<div class="chart-empty">No agent runs yet</div>'; return; }}
  const counts = d3.rollup(data, v => v.length, d => d.status);
  const entries = Array.from(counts, ([k, v]) => ({{ status: k, count: v }}));
  const statusColors = {{ completed: COLORS.green, running: COLORS.yellow, failed: COLORS.red, unknown: COLORS.indigo }};
  const w = 240, h = 240, r = Math.min(w, h) / 2 - 10;
  const svg = d3.select(el).append('svg').attr('width', w).attr('height', h)
    .append('g').attr('transform', `translate(${{w/2}},${{h/2}})`);
  const pie = d3.pie().value(d => d.count).sort(null);
  const arc = d3.arc().innerRadius(r * 0.55).outerRadius(r);
  const total = d3.sum(entries, d => d.count);
  svg.selectAll('path').data(pie(entries)).join('path')
    .attr('d', arc)
    .attr('fill', d => statusColors[d.data.status] || COLORS.indigo)
    .attr('stroke', COLORS.bg).attr('stroke-width', 2)
    .on('mouseover', (e, d) => showTip(e, `<strong>${{d.data.status}}</strong><br>${{d.data.count}} runs (${{Math.round(d.data.count/total*100)}}%)`))
    .on('mousemove', (e) => showTip(e, tooltip.html()))
    .on('mouseout', hideTip)
    .transition().duration(600).attrTween('d', function(d) {{
      const i = d3.interpolate({{ startAngle: 0, endAngle: 0 }}, d);
      return t => arc(i(t));
    }});
  svg.append('text').attr('text-anchor', 'middle').attr('dy', '-0.1em')
    .attr('fill', COLORS.blue).attr('font-size', '28px').attr('font-weight', '700').text(total);
  svg.append('text').attr('text-anchor', 'middle').attr('dy', '1.3em')
    .attr('fill', COLORS.text).attr('font-size', '11px').text('total runs');
  // legend
  const leg = d3.select(el).append('div').attr('class', 'chart-legend');
  entries.forEach(e => {{
    leg.append('span').html(`<span class="legend-dot" style="background:${{statusColors[e.status] || COLORS.indigo}}"></span>${{e.status}} (${{e.count}})`);
  }});
}}

// ── 2. Results by Type (horizontal bars) ──
function drawResultsBars(data) {{
  const el = document.getElementById('results-chart');
  el.innerHTML = '';
  if (!data.length) {{ el.innerHTML = '<div class="chart-empty">No results yet</div>'; return; }}
  const groups = d3.rollups(data, v => ({{
    novel: v.filter(d => d.novel).length,
    replication: v.filter(d => !d.novel).length,
    total: v.length
  }}), d => d.type).map(([k, v]) => ({{ type: k, ...v }})).sort((a, b) => b.total - a.total).slice(0, 8);
  const m = {{ top: 8, right: 16, bottom: 24, left: 100 }};
  const w = 360, h = Math.max(180, groups.length * 32 + m.top + m.bottom);
  const innerW = w - m.left - m.right, innerH = h - m.top - m.bottom;
  const svg = d3.select(el).append('svg').attr('width', w).attr('height', h)
    .append('g').attr('transform', `translate(${{m.left}},${{m.top}})`);
  const y = d3.scaleBand().domain(groups.map(d => d.type)).range([0, innerH]).padding(0.25);
  const x = d3.scaleLinear().domain([0, d3.max(groups, d => d.total)]).range([0, innerW]);
  // novel bars
  svg.selectAll('.bar-novel').data(groups).join('rect').attr('class', 'bar-novel')
    .attr('y', d => y(d.type)).attr('height', y.bandwidth())
    .attr('x', 0).attr('fill', COLORS.green).attr('rx', 0)
    .on('mouseover', (e, d) => showTip(e, `<strong>${{d.type}}</strong><br>Novel: ${{d.novel}}<br>Replication: ${{d.replication}}`))
    .on('mousemove', (e) => showTip(e, tooltip.html()))
    .on('mouseout', hideTip)
    .transition().duration(500).attr('width', d => x(d.novel));
  // replication bars (stacked)
  svg.selectAll('.bar-rep').data(groups).join('rect').attr('class', 'bar-rep')
    .attr('y', d => y(d.type)).attr('height', y.bandwidth())
    .attr('fill', COLORS.indigo).attr('rx', 0)
    .on('mouseover', (e, d) => showTip(e, `<strong>${{d.type}}</strong><br>Novel: ${{d.novel}}<br>Replication: ${{d.replication}}`))
    .on('mousemove', (e) => showTip(e, tooltip.html()))
    .on('mouseout', hideTip)
    .transition().duration(500).attr('x', d => x(d.novel)).attr('width', d => x(d.replication));
  // labels
  svg.append('g').call(d3.axisLeft(y).tickSize(0)).select('.domain').remove();
  svg.selectAll('.tick text').attr('fill', COLORS.text).attr('font-size', '11px');
  svg.selectAll('.count-label').data(groups).join('text').attr('class', 'count-label')
    .attr('x', d => x(d.total) + 4).attr('y', d => y(d.type) + y.bandwidth() / 2)
    .attr('dy', '0.35em').attr('fill', COLORS.faint).attr('font-size', '11px').text(d => d.total);
  // legend
  const leg = d3.select(el).append('div').attr('class', 'chart-legend');
  leg.append('span').html(`<span class="legend-dot" style="background:${{COLORS.green}}"></span>Novel`);
  leg.append('span').html(`<span class="legend-dot" style="background:${{COLORS.indigo}}"></span>Replication`);
}}

// ── 3. Pipeline Timeline ──
function drawTimeline(data) {{
  const el = document.getElementById('timeline-chart');
  el.innerHTML = '';
  const runs = data.filter(d => d.started !== '—');
  if (!runs.length) {{ el.innerHTML = '<div class="chart-empty">No pipeline data yet</div>'; return; }}
  runs.forEach(d => {{ d._start = new Date(d.started); d._dur = parseInt(d.duration) || 30; }});
  runs.sort((a, b) => a._start - b._start);
  const agents = [...new Set(runs.map(d => d.agent))];
  const agentColor = d3.scaleOrdinal().domain(agents).range([COLORS.blue, COLORS.green, COLORS.purple, COLORS.yellow, COLORS.cyan, COLORS.orange, COLORS.red, COLORS.indigo]);
  const m = {{ top: 8, right: 16, bottom: 28, left: 110 }};
  const w = 360, h = Math.max(160, agents.length * 28 + m.top + m.bottom);
  const innerW = w - m.left - m.right, innerH = h - m.top - m.bottom;
  const svg = d3.select(el).append('svg').attr('width', w).attr('height', h)
    .append('g').attr('transform', `translate(${{m.left}},${{m.top}})`);
  const extent = d3.extent(runs, d => d._start);
  const xMax = new Date(extent[1].getTime() + d3.max(runs, d => d._dur) * 1000);
  const x = d3.scaleTime().domain([extent[0], xMax]).range([0, innerW]);
  const y = d3.scaleBand().domain(agents).range([0, innerH]).padding(0.3);
  svg.selectAll('.tl-bar').data(runs).join('rect').attr('class', 'tl-bar')
    .attr('y', d => y(d.agent)).attr('height', y.bandwidth())
    .attr('x', d => x(d._start)).attr('rx', 0)
    .attr('fill', d => agentColor(d.agent)).attr('opacity', 0.8)
    .on('mouseover', (e, d) => showTip(e, `<strong>${{d.agent}}</strong><br>${{d.started}}<br>Duration: ${{d.duration}}<br>Status: ${{d.status}}`))
    .on('mousemove', (e) => showTip(e, tooltip.html()))
    .on('mouseout', hideTip)
    .transition().duration(500).attr('width', d => Math.max(3, x(new Date(d._start.getTime() + d._dur * 1000)) - x(d._start)));
  svg.append('g').attr('transform', `translate(0,${{innerH}})`).call(d3.axisBottom(x).ticks(4).tickFormat(d3.timeFormat('%m/%d %H:%M'))).select('.domain').remove();
  svg.selectAll('.tick text').attr('fill', COLORS.faint).attr('font-size', '10px');
  svg.selectAll('.tick line').attr('stroke', COLORS.border);
  svg.append('g').call(d3.axisLeft(y).tickSize(0)).select('.domain').remove();
  svg.selectAll('.tick text').attr('fill', COLORS.text).attr('font-size', '11px');
}}

// ── 4. Critique Radar Chart ──
function drawRadar(data) {{
  const el = document.getElementById('radar-chart');
  const legendEl = document.getElementById('radar-legend');
  el.innerHTML = ''; legendEl.innerHTML = '';
  const scored = data.filter(d => d.scores && Object.keys(d.scores).length >= 2);
  if (!scored.length) {{ el.innerHTML = '<div class="chart-empty">No scored critiques yet</div>'; return; }}
  const dims = ['scientific_logic', 'statistical_validity', 'interpretive_accuracy', 'reproducibility'];
  const dimLabels = ['Logic', 'Statistics', 'Interpretation', 'Reproducibility'];
  const w = 260, h = 260, cx = w / 2, cy = h / 2, maxR = 100;
  const svg = d3.select(el).append('svg').attr('width', w).attr('height', h);
  const g = svg.append('g').attr('transform', `translate(${{cx}},${{cy}})`);
  const angleSlice = (Math.PI * 2) / dims.length;
  // Grid circles
  [2, 4, 6, 8, 10].forEach(lev => {{
    const r = (lev / 10) * maxR;
    g.append('circle').attr('r', r).attr('fill', 'none').attr('stroke', COLORS.border).attr('stroke-dasharray', lev === 10 ? 'none' : '2,3');
    if (lev % 4 === 0 || lev === 10) g.append('text').attr('x', 4).attr('y', -r).attr('fill', COLORS.faint).attr('font-size', '9px').text(lev);
  }});
  // Axes
  dims.forEach((d, i) => {{
    const a = angleSlice * i - Math.PI / 2;
    g.append('line').attr('x1', 0).attr('y1', 0)
      .attr('x2', maxR * Math.cos(a)).attr('y2', maxR * Math.sin(a))
      .attr('stroke', COLORS.border);
    g.append('text').attr('x', (maxR + 14) * Math.cos(a)).attr('y', (maxR + 14) * Math.sin(a))
      .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
      .attr('fill', COLORS.text).attr('font-size', '10px').text(dimLabels[i]);
  }});
  // Plot up to 5 most recent critiques
  const reviewerColors = [COLORS.blue, COLORS.green, COLORS.yellow, COLORS.purple, COLORS.cyan];
  const recent = scored.slice(0, 5);
  recent.forEach((crit, ci) => {{
    const pts = dims.map((d, i) => {{
      const val = crit.scores[d] || 0;
      const a = angleSlice * i - Math.PI / 2;
      return [((val / 10) * maxR) * Math.cos(a), ((val / 10) * maxR) * Math.sin(a)];
    }});
    const color = reviewerColors[ci % reviewerColors.length];
    g.append('polygon')
      .attr('points', pts.map(p => p.join(',')).join(' '))
      .attr('fill', color).attr('fill-opacity', 0.15)
      .attr('stroke', color).attr('stroke-width', 1.5);
    pts.forEach((p, pi) => {{
      g.append('circle').attr('cx', p[0]).attr('cy', p[1]).attr('r', 3).attr('fill', color)
        .on('mouseover', (e) => showTip(e, `<strong>${{crit.reviewer}}</strong><br>${{dimLabels[pi]}}: ${{crit.scores[dims[pi]] || 0}}/10`))
        .on('mouseout', hideTip);
    }});
    // legend
    d3.select(legendEl).append('span')
      .html(`<span class="legend-dot" style="background:${{color}}"></span>${{crit.reviewer}} (#${{crit.id}})`);
  }});
}}

// ── 5. Score Trend Line ──
function drawTrend(data) {{
  const el = document.getElementById('trend-chart');
  const legendEl = document.getElementById('trend-legend');
  el.innerHTML = ''; legendEl.innerHTML = '';
  const dims = ['scientific_logic', 'statistical_validity', 'interpretive_accuracy', 'reproducibility'];
  const dimLabels = ['Logic', 'Statistics', 'Interpretation', 'Reproducibility'];
  const dimColors = [COLORS.blue, COLORS.green, COLORS.yellow, COLORS.purple];
  const scored = data.filter(d => d.scores && Object.keys(d.scores).length >= 2 && d.timestamp !== '—');
  if (scored.length < 2) {{ el.innerHTML = '<div class="chart-empty">Need 2+ scored critiques for trends</div>'; return; }}
  scored.forEach(d => {{ d._ts = new Date(d.timestamp); }});
  scored.sort((a, b) => a._ts - b._ts);
  const m = {{ top: 12, right: 24, bottom: 28, left: 36 }};
  const w = el.parentElement.clientWidth - 32 || 700;
  const h = 220;
  const innerW = w - m.left - m.right, innerH = h - m.top - m.bottom;
  const svg = d3.select(el).append('svg').attr('width', w).attr('height', h)
    .append('g').attr('transform', `translate(${{m.left}},${{m.top}})`);
  const x = d3.scaleTime().domain(d3.extent(scored, d => d._ts)).range([0, innerW]);
  const y = d3.scaleLinear().domain([0, 10]).range([innerH, 0]);
  svg.append('g').attr('transform', `translate(0,${{innerH}})`).call(d3.axisBottom(x).ticks(5).tickFormat(d3.timeFormat('%m/%d'))).select('.domain').remove();
  svg.selectAll('.tick text').attr('fill', COLORS.faint).attr('font-size', '10px');
  svg.selectAll('.tick line').attr('stroke', COLORS.border);
  svg.append('g').call(d3.axisLeft(y).ticks(5).tickSize(-innerW)).select('.domain').remove();
  svg.selectAll('.tick text').attr('fill', COLORS.faint).attr('font-size', '10px');
  svg.selectAll('.tick line').attr('stroke', COLORS.border).attr('stroke-dasharray', '2,3');
  dims.forEach((dim, di) => {{
    const pts = scored.filter(d => d.scores[dim] != null).map(d => ({{ x: d._ts, y: d.scores[dim] }}));
    if (pts.length < 2) return;
    const line = d3.line().x(d => x(d.x)).y(d => y(d.y)).curve(d3.curveMonotoneX);
    svg.append('path').datum(pts).attr('fill', 'none')
      .attr('stroke', dimColors[di]).attr('stroke-width', 2).attr('d', line);
    svg.selectAll(`.dot-${{di}}`).data(pts).join('circle').attr('class', `dot-${{di}}`)
      .attr('cx', d => x(d.x)).attr('cy', d => y(d.y)).attr('r', 3.5).attr('fill', dimColors[di])
      .on('mouseover', (e, d) => showTip(e, `<strong>${{dimLabels[di]}}</strong><br>${{d.y}}/10<br>${{d3.timeFormat('%Y-%m-%d %H:%M')(d.x)}}`))
      .on('mouseout', hideTip);
    d3.select(legendEl).append('span')
      .html(`<span class="legend-dot" style="background:${{dimColors[di]}}"></span>${{dimLabels[di]}}`);
  }});
}}

// ── Fetch data and render charts ──
async function initCharts() {{
  try {{
    const [runs, findings, critiques] = await Promise.all([
      fetch('/api/runs').then(r => r.json()),
      fetch('/api/findings').then(r => r.json()),
      fetch('/api/critiques').then(r => r.json())
    ]);
    drawDonut(runs);
    drawResultsBars(findings);
    drawTimeline(runs);
    drawRadar(critiques);
    drawTrend(critiques);
  }} catch (err) {{
    console.error('Chart init error:', err);
  }}
}}
initCharts();
</script>

</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def dashboard(request: Request):
    conn = get_conn()
    cur = conn.cursor()
    stats = query_stats(cur)
    runs = query_recent_runs(cur)
    findings = query_findings(cur)
    critiques = query_critiques(cur)
    sources = query_sources(cur)
    activity = query_activity_log(cur)
    cur.close()
    put_conn(conn)
    vast_info = query_vast_instances()
    return render_dashboard(stats, runs, findings, critiques, sources, activity, vast_info)


@app.get("/api/stats")
@limiter.limit("60/minute")
async def api_stats(request: Request):
    conn = get_conn()
    cur = conn.cursor()
    stats = query_stats(cur)
    cur.close()
    put_conn(conn)
    return stats


@app.get("/api/findings")
@limiter.limit("30/minute")
async def api_findings(request: Request, novel_only: bool = False, limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    data = query_findings(cur, novel_only=novel_only, limit=min(limit, 200))
    cur.close()
    put_conn(conn)
    return data


@app.get("/api/runs")
@limiter.limit("30/minute")
async def api_runs(request: Request, limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    data = query_recent_runs(cur, limit=min(limit, 200))
    cur.close()
    put_conn(conn)
    return data


@app.get("/api/critiques")
@limiter.limit("30/minute")
async def api_critiques(request: Request, limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    data = query_critiques(cur, limit=min(limit, 200))
    cur.close()
    put_conn(conn)
    return data


@app.get("/api/sources")
@limiter.limit("30/minute")
async def api_sources(request: Request, limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    data = query_sources(cur, limit=min(limit, 200))
    cur.close()
    put_conn(conn)
    return data


@app.get("/api/vast")
@limiter.limit("30/minute")
async def api_vast(request: Request):
    return query_vast_instances()


@app.get("/api/budget")
@limiter.limit("30/minute")
async def api_budget(request: Request):
    """Aggregated budget view across all AI providers."""
    result = {"vast": {}, "llm": {}, "total": 0}

    # Vast.ai
    vast_key = os.environ.get("VAST_AI_KEY", "")
    if vast_key:
        try:
            import requests as _req
            resp = _req.get(
                "https://console.vast.ai/api/v0/users/current/",
                headers={"Authorization": f"Bearer {vast_key}"},
                timeout=10,
            )
            resp.raise_for_status()
            result["vast"]["balance"] = float(resp.json().get("credit", 0))
        except Exception:
            result["vast"]["balance"] = None

    spend_info = query_vast_spend()
    result["vast"]["spent"] = spend_info["spent"]
    result["total"] += spend_info["spent"]

    # LLM spend
    try:
        conn = get_conn()
        cur = conn.cursor()
        if table_exists(cur, "llm_spend"):
            cur.execute(
                "SELECT provider, SUM(input_tokens), SUM(output_tokens),"
                " SUM(estimated_cost), COUNT(*)"
                " FROM llm_spend GROUP BY provider ORDER BY SUM(estimated_cost) DESC"
            )
            providers = []
            llm_total = 0
            for provider, in_tok, out_tok, cost, calls in cur.fetchall():
                providers.append({
                    "provider": provider,
                    "input_tokens": int(in_tok or 0),
                    "output_tokens": int(out_tok or 0),
                    "cost": round(float(cost or 0), 6),
                    "calls": int(calls or 0),
                })
                llm_total += float(cost or 0)
            result["llm"] = {"providers": providers, "total": round(llm_total, 6)}
            result["total"] += llm_total
        cur.close()
        put_conn(conn)
    except Exception:
        result["llm"] = {"providers": [], "total": 0}

    result["total"] = round(result["total"], 2)
    return result


@app.get("/api/batch")
@limiter.limit("30/minute")
async def batch_status(request: Request):
    """Get batch dispatch status — active batches, pool, and job counts."""
    result = {"batches": [], "pool": [], "totals": {"pending": 0, "running": 0, "done": 0, "failed": 0}}
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Active batches
        cur.execute("""
            SELECT batch_id,
                   COUNT(*) FILTER (WHERE status = 'pending')  AS pending,
                   COUNT(*) FILTER (WHERE status = 'running')  AS running,
                   COUNT(*) FILTER (WHERE status = 'done')     AS done,
                   COUNT(*) FILTER (WHERE status = 'failed')   AS failed,
                   COUNT(*)                                    AS total,
                   MIN(created_at)                             AS started
            FROM batch_jobs
            GROUP BY batch_id
            ORDER BY MIN(created_at) DESC
            LIMIT 10
        """)
        for r in cur.fetchall():
            result["batches"].append({
                "batch_id": r[0], "pending": r[1], "running": r[2],
                "done": r[3], "failed": r[4], "total": r[5],
                "started": str(r[6]) if r[6] else None,
                "progress_pct": round(r[3] / max(r[5], 1) * 100, 1),
            })
            result["totals"]["pending"] += r[1]
            result["totals"]["running"] += r[2]
            result["totals"]["done"] += r[3]
            result["totals"]["failed"] += r[4]
        # Instance pool
        cur.execute("""
            SELECT instance_id, ssh_host, gpu_name, cost_per_hr, status, jobs_done,
                   created_at, ready_at
            FROM vast_pool
            WHERE status != 'destroyed'
            ORDER BY created_at
        """)
        for r in cur.fetchall():
            result["pool"].append({
                "instance_id": r[0], "ssh_host": r[1], "gpu_name": r[2],
                "cost_per_hr": r[3], "status": r[4], "jobs_done": r[5],
                "created_at": str(r[6]) if r[6] else None,
                "ready_at": str(r[7]) if r[7] else None,
            })
        cur.close()
        put_conn(conn)
    except Exception:
        pass
    return result


@app.get("/api/export/findings")
@limiter.limit("10/minute")
async def export_findings(
    request: Request,
    fmt: str = Query("json", pattern="^(json|csv)$"),
    novel_only: bool = False,
    limit: int = 500,
):
    conn = get_conn()
    cur = conn.cursor()
    data = query_findings(cur, novel_only=novel_only, limit=min(limit, 10000))
    cur.close()
    put_conn(conn)
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
@limiter.limit("10/minute")
async def export_critiques(request: Request, fmt: str = Query("json", pattern="^(json|csv)$"), limit: int = 500):
    conn = get_conn()
    cur = conn.cursor()
    data = query_critiques(cur, limit=min(limit, 10000))
    cur.close()
    put_conn(conn)
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
            put_conn(conn)
            if stats != prev_stats:
                changed = prev_stats is not None
                prev_stats = stats
                broadcast_data = {**stats, "_changed": changed}
                payload = json.dumps({"type": "stats", "data": broadcast_data})
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
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    args = parser.parse_args()
    print(f"🧬 OpenCure Labs Dashboard → http://{args.host}:{args.port}")
    if args.reload:
        uvicorn.run("dashboard:app", host=args.host, port=args.port, log_level="warning",
                     reload=True, reload_dirs=[str(Path(__file__).parent)])
    else:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

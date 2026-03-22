#!/usr/bin/env python3
"""OpenCure Labs — Findings CLI

Query the PostgreSQL database for experiment results, agent runs, and critiques.

Usage:
    python scripts/findings.py                  # Summary dashboard
    python scripts/findings.py --novel          # Novel findings only
    python scripts/findings.py --agents         # Agent run history
    python scripts/findings.py --critiques      # Critique log
    python scripts/findings.py --sources        # Discovered data sources
    python scripts/findings.py --watch          # Auto-refresh every 10s
"""

import argparse
import json
import os
import sys
import time

import psycopg2

DB_URL = os.environ.get("POSTGRES_URL", "dbname=opencurelabs port=5433")

# ── ANSI colors ──────────────────────────────────────────────────────────────
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

SPECIES_EMOJI = {"human": "🧬", "dog": "🐕", "cat": "🐈"}


def get_conn():
    try:
        conn = psycopg2.connect(DB_URL)
        conn.autocommit = True
        return conn
    except psycopg2.OperationalError as e:
        print(f"{RED}Cannot connect to PostgreSQL at {DB_URL}{RESET}")
        print(f"{DIM}{e}{RESET}")
        sys.exit(1)


def table_exists(cur, table_name):
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        (table_name,),
    )
    return cur.fetchone()[0]


def print_header(title):
    w = 72
    print(f"\n{BOLD}{CYAN}{'─' * w}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * w}{RESET}")


def print_summary(cur, species=None):
    """Print a one-screen summary dashboard."""
    sp_label = f" ({SPECIES_EMOJI.get(species, '')} {species})" if species else ""
    print_header(f"OpenCure Labs — Findings Dashboard{sp_label}")

    # Agent runs
    if table_exists(cur, "agent_runs"):
        cur.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE status = 'running') FROM agent_runs")
        total, running = cur.fetchone()
        print(f"\n  {BOLD}Agent Runs:{RESET}  {total} total, {GREEN}{running} running{RESET}")

        cur.execute(
            "SELECT agent_name, status, started_at FROM agent_runs ORDER BY started_at DESC LIMIT 5"
        )
        rows = cur.fetchall()
        if rows:
            for name, status, started in rows:
                color = GREEN if status == "completed" else YELLOW if status == "running" else RED
                ts = started.strftime("%Y-%m-%d %H:%M") if started else "—"
                print(f"    {color}●{RESET} {name:<20} {color}{status:<12}{RESET} {DIM}{ts}{RESET}")
    else:
        print(f"\n  {DIM}No agent_runs table{RESET}")

    # Experiment results
    if table_exists(cur, "experiment_results"):
        species_filter = ""
        params = []
        if species:
            species_filter = "WHERE species = %s"
            params = [species]
        cur.execute(
            f"SELECT COUNT(*), COUNT(*) FILTER (WHERE novel = TRUE) FROM experiment_results {species_filter}",
            params,
        )
        total, novel = cur.fetchone()
        sp_label = f" ({SPECIES_EMOJI.get(species, '')} {species})" if species else ""
        print(f"\n  {BOLD}Results:{RESET}     {total} total, {GREEN}{novel} novel{RESET}{sp_label}")

        cur.execute(
            f"SELECT id, result_type, novel, timestamp, COALESCE(species, 'human') as species FROM experiment_results"
            f" {species_filter}"
            f" ORDER BY timestamp DESC LIMIT 5",
            params,
        )
        rows = cur.fetchall()
        if rows:
            for rid, rtype, novel, ts, sp in rows:
                marker = f"{GREEN}🆕 NOVEL{RESET}" if novel else f"{BLUE}📊 repl{RESET}"
                ts_str = ts.strftime("%Y-%m-%d %H:%M") if ts else "—"
                sp_icon = SPECIES_EMOJI.get(sp, "🧬")
                print(f"    #{rid:<4} {sp_icon} {rtype:<28} {marker}  {DIM}{ts_str}{RESET}")
    else:
        print(f"\n  {DIM}No experiment_results table{RESET}")

    # Reviews
    if table_exists(cur, "critique_log"):
        cur.execute("SELECT COUNT(*) FROM critique_log")
        total = cur.fetchone()[0]
        print(f"\n  {BOLD}Reviews:{RESET}    {total} total (Grok)")

        cur.execute(
            "SELECT id, reviewer, critique_json, timestamp FROM critique_log"
            " ORDER BY timestamp DESC LIMIT 3"
        )
        rows = cur.fetchall()
        for cid, reviewer, crit, ts in rows:
            ts_str = ts.strftime("%Y-%m-%d %H:%M") if ts else "—"
            rec = "—"
            if isinstance(crit, dict):
                rec = crit.get("recommendation", "—")
            elif isinstance(crit, str):
                try:
                    rec = json.loads(crit).get("recommendation", "—")
                except (json.JSONDecodeError, AttributeError):
                    pass
            color = GREEN if rec == "publish" else YELLOW if rec == "revise" else RED
            print(f"    #{cid:<4} {reviewer:<16} → {color}{rec}{RESET}  {DIM}{ts_str}{RESET}")
    else:
        print(f"\n  {DIM}No critique_log table{RESET}")

    # Discovered sources
    if table_exists(cur, "discovered_sources"):
        cur.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE validated = TRUE) FROM discovered_sources"
        )
        total, validated = cur.fetchone()
        print(f"\n  {BOLD}Sources:{RESET}     {total} discovered, {GREEN}{validated} validated{RESET}")
    else:
        print(f"\n  {DIM}No discovered_sources table{RESET}")

    print()


def print_novel(cur, species=None):
    """Print novel findings in detail."""
    print_header("Novel Findings")

    if not table_exists(cur, "experiment_results"):
        print(f"  {DIM}No experiment_results table{RESET}\n")
        return

    species_filter = ""
    params = []
    if species:
        species_filter = "AND e.species = %s"
        params = [species]
    cur.execute(
        f"SELECT e.id, e.result_type, e.result_data, e.timestamp, p.pipeline_name, COALESCE(e.species, 'human') as species"
        f" FROM experiment_results e"
        f" LEFT JOIN pipeline_runs p ON e.pipeline_run_id = p.id"
        f" WHERE e.novel = TRUE {species_filter}"
        f" ORDER BY e.timestamp DESC",
        params,
    )
    rows = cur.fetchall()
    if not rows:
        print(f"  {DIM}No novel findings yet.{RESET}\n")
        return

    for rid, rtype, rdata, ts, pipeline, sp in rows:
        ts_str = ts.strftime("%Y-%m-%d %H:%M") if ts else "—"
        sp_icon = SPECIES_EMOJI.get(sp, "🧬")
        print(f"\n  {GREEN}🆕 #{rid}{RESET}  {sp_icon} {BOLD}{rtype}{RESET}  {DIM}({pipeline or 'unknown pipeline'}) {ts_str}{RESET}")
        if isinstance(rdata, dict):
            data = rdata
        elif isinstance(rdata, str):
            try:
                data = json.loads(rdata)
            except json.JSONDecodeError:
                data = {"raw": rdata}
        else:
            data = {}
        for k, v in list(data.items())[:8]:
            val = str(v)[:80]
            print(f"    {CYAN}{k}:{RESET} {val}")
    print()


def print_agents(cur):
    """Print agent run history."""
    print_header("Agent Runs")

    if not table_exists(cur, "agent_runs"):
        print(f"  {DIM}No agent_runs table{RESET}\n")
        return

    cur.execute(
        "SELECT id, agent_name, started_at, completed_at, status"
        " FROM agent_runs ORDER BY started_at DESC LIMIT 20"
    )
    rows = cur.fetchall()
    if not rows:
        print(f"  {DIM}No agent runs recorded.{RESET}\n")
        return

    print(f"  {'ID':<6} {'AGENT':<22} {'STATUS':<12} {'STARTED':<18} {'DURATION'}")
    print(f"  {'─'*6} {'─'*22} {'─'*12} {'─'*18} {'─'*12}")
    for rid, name, started, completed, status in rows:
        color = GREEN if status == "completed" else YELLOW if status == "running" else RED
        ts = started.strftime("%Y-%m-%d %H:%M") if started else "—"
        dur = "—"
        if started and completed:
            delta = completed - started
            dur = f"{int(delta.total_seconds())}s"
        print(f"  {rid:<6} {name:<22} {color}{status:<12}{RESET} {ts:<18} {dur}")
    print()


def print_critiques(cur):
    """Print critique log."""
    print_header("Grok Review Log")

    if not table_exists(cur, "critique_log"):
        print(f"  {DIM}No critique_log table{RESET}\n")
        return

    cur.execute(
        "SELECT c.id, c.reviewer, c.critique_json, c.timestamp, p.pipeline_name"
        " FROM critique_log c"
        " LEFT JOIN pipeline_runs p ON c.run_id = p.id"
        " ORDER BY c.timestamp DESC LIMIT 10"
    )
    rows = cur.fetchall()
    if not rows:
        print(f"  {DIM}No reviews recorded.{RESET}\n")
        return

    for cid, reviewer, crit, ts, pipeline in rows:
        ts_str = ts.strftime("%Y-%m-%d %H:%M") if ts else "—"
        print(f"\n  {BOLD}#{cid}{RESET}  {reviewer}  {DIM}{pipeline or '—'} · {ts_str}{RESET}")
        if isinstance(crit, str):
            try:
                crit = json.loads(crit)
            except json.JSONDecodeError:
                print(f"    {crit[:120]}")
                continue
        if isinstance(crit, dict):
            for dim in ("scientific_logic", "statistical_validity", "interpretive_accuracy", "reproducibility"):
                if dim in crit:
                    raw = crit[dim]
                    score = raw["score"] if isinstance(raw, dict) else raw
                    score = max(0, min(10, int(score)))
                    bar = "█" * score + "░" * (10 - score)
                    print(f"    {dim:<24} {bar} {score}/10")
            # Grok literature reviews: show summary snippet
            if "summary" in crit:
                summary = crit["summary"][:200]
                print(f"    {'summary':<24} {DIM}{summary}{RESET}")
            rec = crit.get("recommendation", "—")
            color = GREEN if rec == "publish" else YELLOW if rec == "revise" else RED
            print(f"    {'recommendation':<24} → {color}{BOLD}{rec}{RESET}")
    print()


def print_sources(cur):
    """Print discovered data sources."""
    print_header("Discovered Sources")

    if not table_exists(cur, "discovered_sources"):
        print(f"  {DIM}No discovered_sources table{RESET}\n")
        return

    cur.execute(
        "SELECT id, url, domain, discovered_by, discovered_at, validated, notes"
        " FROM discovered_sources ORDER BY discovered_at DESC LIMIT 20"
    )
    rows = cur.fetchall()
    if not rows:
        print(f"  {DIM}No sources discovered yet.{RESET}\n")
        return

    for sid, url, domain, by, at, validated, notes in rows:
        ts = at.strftime("%Y-%m-%d %H:%M") if at else "—"
        status = f"{GREEN}✓ validated{RESET}" if validated else f"{YELLOW}○ pending{RESET}"
        print(f"  #{sid:<4} {status}  {domain or '—':<16} {ts}  {DIM}{by or '—'}{RESET}")
        if url:
            print(f"         {CYAN}{url[:70]}{RESET}")
        if notes:
            print(f"         {DIM}{notes[:70]}{RESET}")
    print()


def main():
    parser = argparse.ArgumentParser(description="OpenCure Labs — Findings CLI")
    parser.add_argument("--novel", action="store_true", help="Show novel findings only")
    parser.add_argument("--agents", action="store_true", help="Show agent run history")
    parser.add_argument("--critiques", action="store_true", help="Show critique log")
    parser.add_argument("--sources", action="store_true", help="Show discovered sources")
    parser.add_argument("--species", choices=["human", "dog", "cat"], help="Filter by species")
    parser.add_argument("--all", action="store_true", help="Show everything")
    parser.add_argument("--watch", action="store_true", help="Auto-refresh every 10s")
    args = parser.parse_args()

    show_all = args.all or not (args.novel or args.agents or args.critiques or args.sources)
    species = args.species

    while True:
        conn = get_conn()
        cur = conn.cursor()

        if args.watch:
            os.system("clear")

        if show_all and not (args.novel or args.agents or args.critiques or args.sources):
            print_summary(cur, species=species)
        if args.novel or args.all:
            print_novel(cur, species=species)
        if args.agents or args.all:
            print_agents(cur)
        if args.critiques or args.all:
            print_critiques(cur)
        if args.sources or args.all:
            print_sources(cur)

        cur.close()
        conn.close()

        if not args.watch:
            break
        time.sleep(10)


if __name__ == "__main__":
    main()

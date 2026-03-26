#!/usr/bin/env python3
"""LLM Health Check — DB diagnostics and API connectivity for Grok & Gemini.

Queries the critique_log and experiment_results tables to show:
  - Recent critique score distribution
  - Parse error rate
  - Block rate (blocked/total results)
  - Flagged critiques (score=None)
  - API connectivity status for Grok and Gemini

Usage:
    python3 scripts/llm_health_check.py [--days 7] [--json]
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, PROJECT_ROOT)

DB_URL = os.environ.get("POSTGRES_URL", "dbname=opencurelabs port=5433")


def _get_db_connection():
    import psycopg2

    return psycopg2.connect(DB_URL)


def critique_score_distribution(days: int = 7) -> dict:
    """Query critique_log for score distribution over the last N days."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(*) FROM critique_log WHERE timestamp >= NOW() - INTERVAL '%s days'",
            (days,),
        )
        total = cur.fetchone()[0]

        cur.execute(
            """
            SELECT
                CASE
                    WHEN (critique_json->>'overall_score') IS NULL THEN 'null'
                    WHEN (critique_json->>'overall_score')::float >= 7.0 THEN 'high (7-10)'
                    WHEN (critique_json->>'overall_score')::float >= 5.0 THEN 'mid (5-7)'
                    ELSE 'low (0-5)'
                END AS bucket,
                COUNT(*) AS cnt
            FROM critique_log
            WHERE timestamp >= NOW() - INTERVAL '%s days'
              AND reviewer = 'grok'
            GROUP BY bucket
            ORDER BY bucket
            """,
            (days,),
        )
        buckets = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute(
            """
            SELECT AVG((critique_json->>'overall_score')::float)
            FROM critique_log
            WHERE timestamp >= NOW() - INTERVAL '%s days'
              AND reviewer = 'grok'
              AND critique_json->>'overall_score' IS NOT NULL
              AND critique_json->>'parse_error' IS NULL
            """,
            (days,),
        )
        avg_row = cur.fetchone()
        avg_score = round(float(avg_row[0]), 2) if avg_row and avg_row[0] is not None else None

        cur.close()
        conn.close()
        return {"total_critiques": total, "buckets": buckets, "average_score": avg_score}
    except Exception as e:
        return {"error": str(e)}


def parse_error_rate(days: int = 7) -> dict:
    """Calculate how often Grok returns unparseable responses."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE critique_json->>'parse_error' IS NOT NULL) AS parse_errors,
                COUNT(*) AS total
            FROM critique_log
            WHERE timestamp >= NOW() - INTERVAL '%s days'
              AND reviewer = 'grok'
            """,
            (days,),
        )
        row = cur.fetchone()
        errors, total = row[0], row[1]
        rate = round(errors / total * 100, 1) if total > 0 else 0.0

        cur.close()
        conn.close()
        return {"parse_errors": errors, "total": total, "rate_pct": rate}
    except Exception as e:
        return {"error": str(e)}


def block_rate(days: int = 7) -> dict:
    """How many results were blocked vs published."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT status, COUNT(*)
            FROM experiment_results
            WHERE timestamp >= NOW() - INTERVAL '%s days'
            GROUP BY status
            """,
            (days,),
        )
        statuses = {row[0]: row[1] for row in cur.fetchall()}

        total = sum(statuses.values())
        blocked = statuses.get("blocked", 0)
        rate = round(blocked / total * 100, 1) if total > 0 else 0.0

        cur.close()
        conn.close()
        return {"statuses": statuses, "total": total, "blocked": blocked, "block_rate_pct": rate}
    except Exception as e:
        return {"error": str(e)}


def flagged_critiques(days: int = 7) -> list:
    """Critiques where overall_score is null (parse failures)."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, run_id, reviewer,
                   critique_json->>'parse_error' AS parse_error,
                   timestamp
            FROM critique_log
            WHERE timestamp >= NOW() - INTERVAL '%s days'
              AND (critique_json->>'overall_score' IS NULL
                   OR critique_json->>'parse_error' IS NOT NULL)
            ORDER BY timestamp DESC
            LIMIT 20
            """,
            (days,),
        )
        rows = cur.fetchall()
        result = [
            {
                "id": r[0],
                "run_id": r[1],
                "reviewer": r[2],
                "parse_error": r[3],
                "created_at": str(r[4]),
            }
            for r in rows
        ]
        cur.close()
        conn.close()
        return result
    except Exception as e:
        return [{"error": str(e)}]


def recommendation_distribution(days: int = 7) -> dict:
    """Distribution of publish/revise/reject recommendations."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT critique_json->>'recommendation' AS rec, COUNT(*)
            FROM critique_log
            WHERE timestamp >= NOW() - INTERVAL '%s days'
              AND reviewer = 'grok'
              AND critique_json->>'recommendation' IS NOT NULL
            GROUP BY rec
            ORDER BY rec
            """,
            (days,),
        )
        recs = {row[0]: row[1] for row in cur.fetchall()}
        cur.close()
        conn.close()
        return recs
    except Exception as e:
        return {"error": str(e)}


def check_grok_api() -> dict:
    """Test Grok API connectivity with a minimal request."""
    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        return {"status": "skipped", "reason": "XAI_API_KEY not set"}
    try:
        import openai

        client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        response = client.chat.completions.create(
            model="grok-4-1-fast-non-reasoning",
            messages=[{"role": "user", "content": "Reply with 'ok'"}],
            max_tokens=5,
        )
        content = response.choices[0].message.content.strip()
        return {"status": "ok", "response": content}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def check_gemini_api() -> dict:
    """Test Gemini API connectivity with a minimal request."""
    api_key = os.environ.get("GENAI_API_KEY", "")
    if not api_key:
        return {"status": "skipped", "reason": "GENAI_API_KEY not set"}
    try:
        import openai

        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        response = client.chat.completions.create(
            model="gemini-2.5-flash-lite",
            messages=[{"role": "user", "content": "Reply with 'ok'"}],
            max_tokens=5,
        )
        content = response.choices[0].message.content.strip()
        return {"status": "ok", "response": content}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="LLM Health Check — DB diagnostics and API status")
    parser.add_argument("--days", type=int, default=7, help="Look back N days (default: 7)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--skip-api", action="store_true", help="Skip API connectivity checks")
    args = parser.parse_args()

    report = {}

    # DB checks
    print("=" * 60) if not args.json else None
    print("LLM Health Check Report") if not args.json else None
    print(f"  Period: last {args.days} days") if not args.json else None
    print("=" * 60) if not args.json else None

    # 1. Score distribution
    scores = critique_score_distribution(args.days)
    report["score_distribution"] = scores
    if not args.json:
        print("\n── Grok Critique Score Distribution ──")
        if "error" in scores:
            print(f"  Error: {scores['error']}")
        else:
            print(f"  Total critiques: {scores['total_critiques']}")
            print(f"  Average score: {scores['average_score']}")
            for bucket, count in scores.get("buckets", {}).items():
                print(f"    {bucket}: {count}")

    # 2. Recommendation distribution
    recs = recommendation_distribution(args.days)
    report["recommendations"] = recs
    if not args.json:
        print("\n── Recommendation Distribution ──")
        if "error" in recs:
            print(f"  Error: {recs['error']}")
        else:
            for rec, count in recs.items():
                print(f"    {rec}: {count}")

    # 3. Parse error rate
    errors = parse_error_rate(args.days)
    report["parse_errors"] = errors
    if not args.json:
        print("\n── Parse Error Rate ──")
        if "error" in errors:
            print(f"  Error: {errors['error']}")
        else:
            print(f"  Parse errors: {errors['parse_errors']} / {errors['total']} ({errors['rate_pct']}%)")

    # 4. Block rate
    blocks = block_rate(args.days)
    report["block_rate"] = blocks
    if not args.json:
        print("\n── Result Block Rate ──")
        if "error" in blocks:
            print(f"  Error: {blocks['error']}")
        else:
            print(f"  Blocked: {blocks['blocked']} / {blocks['total']} ({blocks['block_rate_pct']}%)")
            for status, count in blocks.get("statuses", {}).items():
                print(f"    {status}: {count}")

    # 5. Flagged critiques
    flagged = flagged_critiques(args.days)
    report["flagged_critiques"] = flagged
    if not args.json:
        print(f"\n── Flagged Critiques (score=None or parse_error) ──")
        if flagged and "error" in flagged[0]:
            print(f"  Error: {flagged[0]['error']}")
        elif flagged:
            for f in flagged:
                print(f"  [{f['created_at']}] run={f['run_id']} reviewer={f['reviewer']} error={f['parse_error']}")
        else:
            print("  None")

    # 6. API connectivity
    if not args.skip_api:
        print("\n── API Connectivity ──") if not args.json else None

        grok_status = check_grok_api()
        report["grok_api"] = grok_status
        if not args.json:
            print(f"  Grok:   {grok_status['status']}" +
                  (f" — {grok_status.get('error', '')}" if grok_status['status'] == 'error' else ""))

        gemini_status = check_gemini_api()
        report["gemini_api"] = gemini_status
        if not args.json:
            print(f"  Gemini: {gemini_status['status']}" +
                  (f" — {gemini_status.get('error', '')}" if gemini_status['status'] == 'error' else ""))

    if not args.json:
        print("\n" + "=" * 60)
    else:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()

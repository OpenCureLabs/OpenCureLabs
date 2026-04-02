#!/usr/bin/env python3
"""Re-score existing experiment results through the updated Grok reviewer.

Reads results from experiment_results that have existing grok critiques,
re-submits them to GrokReviewer.critique() with the updated 4-tier prompt
(publish/revise/archive/reject), and inserts new critique_log entries tagged
with reviewer='grok_rescore'.

The original critiques (reviewer='grok') are NOT deleted — both old and new
scores remain queryable for comparison.

Usage:
    # Dry-run — show what would be re-scored, no API calls
    python scripts/backfill_rescore.py --dry-run

    # Re-score all results from the last 3 days
    python scripts/backfill_rescore.py --days 3

    # Re-score only results that were 'reject' under the old scale
    python scripts/backfill_rescore.py --days 3 --old-rec reject

    # Re-score a specific batch size with delay between calls
    python scripts/backfill_rescore.py --days 3 --batch 100 --delay 0.2

    # Also re-run literature review for novel results
    python scripts/backfill_rescore.py --days 3 --include-literature
"""
import argparse
import json
import logging
import os
import sys
import time

import psycopg2

# Add project root to path so we can import reviewer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reviewer.grok_reviewer import GrokReviewer  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_rescore")

DB_URL = os.environ.get("POSTGRES_URL", "dbname=opencurelabs port=5433")
REVIEWER_TAG = "grok_rescore"
LIT_REVIEWER_TAG = "grok_literature_rescore"


def get_connection():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn


def fetch_results_to_rescore(conn, days: int, old_rec: str | None, limit: int):
    """Fetch experiment results that have an existing grok critique."""
    cur = conn.cursor()

    query = """
        SELECT DISTINCT ON (e.id)
            e.id,
            e.pipeline_run_id,
            e.result_type,
            e.result_data,
            e.novel,
            cl.critique_json->>'overall_score' AS old_score,
            cl.critique_json->>'recommendation' AS old_rec
        FROM experiment_results e
        JOIN critique_log cl ON cl.run_id = e.pipeline_run_id
        WHERE cl.reviewer = 'grok'
          AND e.timestamp >= NOW() - INTERVAL '%s days'
    """
    params = [days]

    if old_rec:
        query += " AND cl.critique_json->>'recommendation' = %s"
        params.append(old_rec)

    # Skip results that already have a rescore
    query += f"""
        AND NOT EXISTS (
            SELECT 1 FROM critique_log cl2
            WHERE cl2.run_id = e.pipeline_run_id
              AND cl2.reviewer = '{REVIEWER_TAG}'
        )
    """

    query += " ORDER BY e.id, cl.timestamp DESC LIMIT %s"
    params.append(limit)

    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def store_critique(conn, run_id: int, reviewer: str, critique_json: dict):
    """Insert a new critique_log entry."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO critique_log (run_id, reviewer, critique_json) "
        "VALUES (%s, %s, %s) RETURNING id",
        (run_id, reviewer, json.dumps(critique_json)),
    )
    critique_id = cur.fetchone()[0]
    cur.close()
    return critique_id


def main():
    parser = argparse.ArgumentParser(description="Re-score experiment results with updated Grok reviewer")
    parser.add_argument("--days", type=int, default=3, help="How many days back to look (default: 3)")
    parser.add_argument("--batch", type=int, default=5000, help="Max results to process (default: 5000)")
    parser.add_argument("--delay", type=float, default=0.05, help="Seconds between API calls (default: 0.05)")
    parser.add_argument("--old-rec", choices=["publish", "revise", "reject"], help="Only re-score results with this old recommendation")
    parser.add_argument("--include-literature", action="store_true", help="Also re-run literature review for novel results")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without calling API")
    args = parser.parse_args()

    if not args.dry_run and not os.environ.get("XAI_API_KEY"):
        logger.error("XAI_API_KEY not set. Use --dry-run or export the key.")
        sys.exit(1)

    conn = get_connection()

    logger.info("Fetching results to re-score (last %d days, limit %d)...", args.days, args.batch)
    rows = fetch_results_to_rescore(conn, args.days, args.old_rec, args.batch)
    logger.info("Found %d results to re-score", len(rows))

    if not rows:
        return

    if args.dry_run:
        # Show distribution of old scores
        from collections import Counter
        old_recs = Counter(row[6] for row in rows)
        old_scores = Counter(row[5] for row in rows)
        print(f"\n{'='*60}")
        print(f"DRY RUN — {len(rows)} results would be re-scored")
        print(f"{'='*60}")
        print(f"\nOld recommendation distribution:")
        for rec, cnt in old_recs.most_common():
            print(f"  {rec}: {cnt}")
        print(f"\nOld score distribution:")
        for score, cnt in sorted(old_scores.items(), key=lambda x: str(x[0])):
            print(f"  score={score}: {cnt}")

        # Estimate cost
        # Average ~500 input tokens + ~800 output tokens per critique call
        est_input = len(rows) * 500
        est_output = len(rows) * 800
        est_cost = (est_input * 0.2e-6) + (est_output * 0.5e-6)
        print(f"\nEstimated cost: ${est_cost:.2f} ({len(rows)} API calls)")
        print(f"Estimated time: ~{len(rows) * max(args.delay, 0.3) / 60:.1f} minutes")
        return

    grok = GrokReviewer()

    counts = {"rescored": 0, "errors": 0, "literature": 0}
    start_time = time.time()

    for i, (eid, run_id, result_type, result_data, novel, old_score, old_rec_val) in enumerate(rows):
        try:
            critique = grok.critique(pipeline_name=result_type, result_data=result_data)

            new_score = critique.get("overall_score")
            new_rec = critique.get("recommendation")

            store_critique(conn, run_id, REVIEWER_TAG, critique)
            counts["rescored"] += 1

            if i < 20 or i % 100 == 0:
                logger.info(
                    "[%d/%d] ID=%d: %s→%s (score %s→%s)",
                    i + 1, len(rows), eid, old_rec_val, new_rec, old_score, new_score,
                )

            # Re-run literature review for novel results if requested
            if args.include_literature and novel:
                lit_review = grok.review_literature(pipeline_name=result_type, result_data=result_data)
                store_critique(conn, run_id, LIT_REVIEWER_TAG, lit_review)
                counts["literature"] += 1

        except Exception as e:
            logger.error("[%d/%d] ID=%d failed: %s", i + 1, len(rows), eid, e)
            counts["errors"] += 1

        if args.delay > 0:
            time.sleep(args.delay)

    elapsed = time.time() - start_time
    logger.info(
        "Done in %.1fs — re-scored: %d, literature: %d, errors: %d",
        elapsed, counts["rescored"], counts["literature"], counts["errors"],
    )

    # Show new distribution
    cur = conn.cursor()
    cur.execute("""
        SELECT critique_json->>'recommendation' AS rec, COUNT(*)
        FROM critique_log
        WHERE reviewer = %s
        GROUP BY rec ORDER BY count DESC
    """, (REVIEWER_TAG,))
    print(f"\n{'='*60}")
    print("New recommendation distribution:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")
    cur.close()

    conn.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Backfill missing results from local PostgreSQL into the D1 ingest Worker.

Usage:
    # Dry run — count what would be synced
    python scripts/backfill_d1.py --dry-run

    # Run the backfill (rate-limited, auto-retries 409 duplicates are skipped)
    python scripts/backfill_d1.py

    # Resume from a specific PG id
    python scripts/backfill_d1.py --start-id 5000

    # Limit batch size
    python scripts/backfill_d1.py --batch-size 500
"""

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import psycopg2.extras
import requests

from agentiq_labclaw.publishers.signing import get_or_create_keypair, sign_payload
from agentiq_labclaw.publishers.r2_publisher import _get_contributor_id, _extract_summary, _extract_species

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill_d1")

INGEST_URL = "https://ingest.opencurelabs.ai"
PG_DSN = "dbname=opencurelabs port=5433"

# Map PG result_type to D1 skill names (they match, but just in case)
SKILL_MAP = {
    "structure_prediction": "structure_prediction",
    "variant_pathogenicity": "variant_pathogenicity",
    "neoantigen_prediction": "neoantigen_prediction",
    "molecular_docking": "molecular_docking",
    "qsar": "qsar",
    "sequencing_qc": "sequencing_qc",
    "grok_research": "grok_research",
    "report_generator": "report_generator",
}


def fetch_published_results(conn, start_id=0, batch_size=1000):
    """Yield batches of published, non-synthetic results from PG."""
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    offset_id = start_id
    while True:
        cursor.execute(
            """SELECT id, result_type, result_data, novel, species, timestamp
               FROM experiment_results
               WHERE status = 'published'
                 AND synthetic = false
                 AND result_type != 'test_skill'
                 AND id > %s
               ORDER BY id ASC
               LIMIT %s""",
            (offset_id, batch_size),
        )
        rows = cursor.fetchall()
        if not rows:
            break
        yield rows
        offset_id = rows[-1]["id"]
    cursor.close()


def post_result(session, signing_key, verify_key_hex, contributor_id, row):
    """POST a single result to the ingest Worker. Returns (status_code, response)."""
    result_data = row["result_data"] if isinstance(row["result_data"], dict) else json.loads(row["result_data"])
    skill = SKILL_MAP.get(row["result_type"])
    if not skill:
        return -1, f"unknown skill: {row['result_type']}"

    payload = {
        "skill": skill,
        "result_data": result_data,
        "novel": bool(row["novel"]),
        "status": "pending",
        "contributor_id": contributor_id,
        "species": row["species"] or "human",
        "summary": _extract_summary(result_data),
    }

    canonical_body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = sign_payload(signing_key, payload)

    headers = {
        "X-Contributor-Key": verify_key_hex,
        "X-Signature": signature,
        "Content-Type": "application/json",
    }

    resp = session.post(f"{INGEST_URL}/results", data=canonical_body, headers=headers, timeout=20)
    return resp.status_code, resp.text


def main():
    parser = argparse.ArgumentParser(description="Backfill PG results to D1")
    parser.add_argument("--dry-run", action="store_true", help="Count results without posting")
    parser.add_argument("--start-id", type=int, default=0, help="Resume from this PG id")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per PG query batch")
    parser.add_argument("--workers", type=int, default=10, help="Concurrent POST threads")
    args = parser.parse_args()

    conn = psycopg2.connect(PG_DSN)
    log.info("Connected to PostgreSQL")

    if args.dry_run:
        cur = conn.cursor()
        cur.execute(
            """SELECT COUNT(*) FROM experiment_results
               WHERE status='published' AND synthetic=false
                 AND result_type != 'test_skill' AND id > %s""",
            (args.start_id,),
        )
        total = cur.fetchone()[0]
        cur.close()
        conn.close()
        log.info("Dry run: %d results would be posted (duplicates auto-skipped by D1)", total)
        return

    signing_key, verify_key_hex = get_or_create_keypair()
    contributor_id = _get_contributor_id()
    log.info("Contributor: %s  Key: %s…", contributor_id, verify_key_hex[:12])

    # Ensure contributor is registered
    try:
        resp = requests.post(
            f"{INGEST_URL}/contributors",
            json={"contributor_id": contributor_id, "public_key": verify_key_hex},
            timeout=15,
        )
        if resp.status_code == 409:
            log.info("Contributor already registered")
        elif resp.ok:
            log.info("Registered contributor")
        else:
            log.warning("Registration response: %d %s", resp.status_code, resp.text)
    except Exception as e:
        log.warning("Could not register contributor: %s", e)

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=args.workers, pool_maxsize=args.workers)
    session.mount("https://", adapter)
    posted = 0
    skipped_dup = 0
    skipped_err = 0
    total = 0
    last_id = args.start_id

    def process_row(row):
        """POST a single row, returns (pg_id, status_code, resp_text)."""
        try:
            sc, txt = post_result(session, signing_key, verify_key_hex, contributor_id, row)
            return row["id"], sc, txt
        except Exception as e:
            return row["id"], -1, str(e)

    for batch in fetch_published_results(conn, start_id=args.start_id, batch_size=args.batch_size):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(process_row, row): row for row in batch}
            for future in as_completed(futures):
                pg_id, status_code, resp_text = future.result()
                total += 1
                last_id = max(last_id, pg_id)

                if status_code in (200, 201):
                    posted += 1
                elif status_code == 409:
                    skipped_dup += 1
                elif status_code == 429:
                    skipped_err += 1
                    log.warning("Rate limited at PG id %d — consider reducing --workers", pg_id)
                else:
                    skipped_err += 1
                    if skipped_err <= 20:
                        log.warning("PG id %d: %d %s", pg_id, status_code, str(resp_text)[:200])

        log.info(
            "Progress: %d processed | %d posted | %d dup | %d err | last PG id: %d",
            total, posted, skipped_dup, skipped_err, last_id,
        )

    conn.close()
    log.info("Done: %d total | %d posted | %d duplicates skipped | %d errors", total, posted, skipped_dup, skipped_err)


if __name__ == "__main__":
    main()

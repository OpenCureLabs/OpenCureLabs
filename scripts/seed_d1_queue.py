#!/usr/bin/env python3
"""Seed the D1 task queue by calling /tasks/generate in chunks.

The worker endpoint accepts {offset, limit} to avoid CPU timeout.
This script iterates through all ~402K tasks in chunks of 5000.

Usage:
    python scripts/seed_d1_queue.py
    python scripts/seed_d1_queue.py --chunk-size 3000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

INGEST_URL = "https://ingest.opencurelabs.ai"
TOTAL_TASKS = 402_000  # approximate — will stop when 0 inserted


def seed_chunk(offset: int, limit: int, admin_key: str) -> dict:
    """Call /tasks/generate with offset/limit. Returns response JSON."""
    data = json.dumps({"offset": offset, "limit": limit}).encode()
    req = urllib.request.Request(
        f"{INGEST_URL}/tasks/generate",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Admin-Key": admin_key,
            "User-Agent": "OpenCureLabs-Agent/1.0",
        },
        data=data,
    )
    resp = urllib.request.urlopen(req, timeout=120)
    return json.loads(resp.read().decode())


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed D1 task queue in chunks")
    parser.add_argument("--chunk-size", type=int, default=5000)
    parser.add_argument("--start-offset", type=int, default=0)
    parser.add_argument("--total", type=int, default=TOTAL_TASKS)
    args = parser.parse_args()

    # Load .env (standard pattern used across the codebase)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    except ImportError:
        pass  # python-dotenv not installed; fall back to plain environment

    admin_key = os.environ.get("OPENCURELABS_ADMIN_KEY", "")
    if not admin_key:
        print("Error: OPENCURELABS_ADMIN_KEY not found in environment or .env")
        sys.exit(1)

    total_inserted = 0
    consecutive_empty = 0
    offset = args.start_offset
    chunk_num = 0

    print(f"Seeding D1 queue: chunks of {args.chunk_size}, starting at offset {offset}")
    print(f"Estimated total tasks: ~{args.total:,}")
    print()

    while offset < args.total + args.chunk_size * 5:
        chunk_num += 1
        try:
            result = seed_chunk(offset, args.chunk_size, admin_key)
            inserted = result.get("inserted", 0)
            total_inserted += inserted
            pct = min(100, (offset + args.chunk_size) / args.total * 100)
            print(f"  chunk {chunk_num}: offset={offset:>7,} inserted={inserted:>5,} total={total_inserted:>7,} ({pct:.0f}%)")

            if inserted == 0:
                consecutive_empty += 1
                # Stop after 5 consecutive empty chunks past the expected total
                if consecutive_empty >= 5 and offset >= args.total:
                    print("\n  5 consecutive empty chunks past total — queue fully seeded.")
                    break
            else:
                consecutive_empty = 0

        except Exception as e:
            print(f"  chunk {chunk_num}: ERROR at offset={offset} — {e}")
            print("  Retrying in 5s...")
            time.sleep(5)
            continue

        offset += args.chunk_size
        # Brief pause to avoid hammering the worker
        time.sleep(0.5)

    print(f"\nDone: {total_inserted:,} tasks inserted across {chunk_num} chunks")


if __name__ == "__main__":
    main()

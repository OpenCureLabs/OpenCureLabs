#!/usr/bin/env python3
"""Backfill critiques table for published results that have batch_critique in R2."""
import json
import os
import sys
import urllib.request

BASE = "https://ingest.opencurelabs.ai"


def main():
    req = urllib.request.Request(
        f"{BASE}/results?status=published&limit=100",
        headers={"User-Agent": "OpenCureSweep/1.0"},
    )
    data = json.loads(urllib.request.urlopen(req).read())
    results = data.get("results", [])
    print(f"Found {len(results)} published results")

    count = 0
    skip = 0
    fail = 0

    for r in results:
        rid = r["id"]
        r2_url = r.get("r2_url", "")
        if not r2_url:
            skip += 1
            continue

        try:
            req2 = urllib.request.Request(r2_url, headers={"User-Agent": "OpenCureSweep/1.0"})
            obj = json.loads(urllib.request.urlopen(req2).read())
        except Exception as e:
            print(f"  Skip {rid} - R2 fetch: {e}")
            skip += 1
            continue

        bc = obj.get("batch_critique")
        if not bc:
            print(f"  Skip {rid} - no batch_critique")
            skip += 1
            continue

        payload = json.dumps({
            "result_id": rid,
            "reviewer": "grok_sweep",
            "overall_score": bc.get("verification_score"),
            "recommendation": bc.get("recommendation"),
            "critique_data": bc,
        }).encode()

        req3 = urllib.request.Request(
            f"{BASE}/critiques",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "OpenCureSweep/1.0"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req3)
            count += 1
            print(f"  OK {rid}")
        except Exception as e:
            print(f"  FAIL {rid}: {e}")
            fail += 1

    print(f"\nBackfilled: {count} / Skipped: {skip} / Failed: {fail}")


if __name__ == "__main__":
    main()

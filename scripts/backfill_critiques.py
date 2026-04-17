#!/usr/bin/env python3
"""Backfill critiques table for published results that have batch_critique in R2."""
import json
import time
import urllib.error
import urllib.request

BASE = "https://ingest.opencurelabs.ai"
USER_AGENT = "OpenCureSweep/1.0"

MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0


def _urlopen_retry(req: urllib.request.Request, *, timeout: float = 30.0) -> bytes:
    """urlopen with exponential backoff. Raises the final exception if all retries fail."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout).read()  # noqa: S310 — trusted endpoints
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_exc = exc
            if attempt < MAX_ATTEMPTS:
                sleep_s = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                print(f"    retry {attempt}/{MAX_ATTEMPTS} in {sleep_s:.1f}s — {exc}")
                time.sleep(sleep_s)
    assert last_exc is not None
    raise last_exc


def main():
    req = urllib.request.Request(
        f"{BASE}/results?status=published&limit=100",
        headers={"User-Agent": USER_AGENT},
    )
    data = json.loads(_urlopen_retry(req))
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
            req2 = urllib.request.Request(r2_url, headers={"User-Agent": USER_AGENT})
            obj = json.loads(_urlopen_retry(req2))
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
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        try:
            _urlopen_retry(req3)
            count += 1
            print(f"  OK {rid}")
        except Exception as e:
            print(f"  FAIL {rid}: {e}")
            fail += 1

    print(f"\nBackfilled: {count} / Skipped: {skip} / Failed: {fail}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""OpenCure Labs — Reviewer Sweep

Polls the public R2/D1 results feed for unreviewed results,
runs Claude Opus (scientific critic) and Grok (literature reviewer),
then publishes critiques back to R2/D1 via the ingest worker.

Usage:
    python reviewer/sweep.py                  # One-shot: review all pending
    python reviewer/sweep.py --watch          # Continuous: poll every 60s
    python reviewer/sweep.py --limit 5        # Review at most 5 results
    python reviewer/sweep.py --reviewer claude  # Only run Claude
    python reviewer/sweep.py --reviewer grok    # Only run Grok
"""

import argparse
import json
import logging
import os
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError

# Allow import from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("labclaw.reviewer.sweep")

INGEST_URL = os.environ.get("INGEST_URL", "https://ingest.opencurelabs.ai")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://pub.opencurelabs.ai")


def api_get(path: str, params: dict | None = None) -> dict:
    """GET request to the ingest worker API."""
    url = f"{INGEST_URL}{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        url = f"{url}?{qs}"

    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:  # noqa: S310 — trusted internal URL
        return json.loads(resp.read())


def api_post(path: str, data: dict) -> dict:
    """POST request to the ingest worker API."""
    url = f"{INGEST_URL}{path}"
    body = json.dumps(data).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=60) as resp:  # noqa: S310 — trusted internal URL
        return json.loads(resp.read())


def fetch_r2_result(r2_url: str) -> dict | None:
    """Fetch full result JSON from R2 public CDN."""
    req = Request(r2_url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310 — trusted CDN URL
            return json.loads(resp.read())
    except (URLError, json.JSONDecodeError) as e:
        logger.warning("Failed to fetch %s: %s", r2_url, e)
        return None


def get_unreviewed_results(limit: int = 50) -> list[dict]:
    """Fetch results from D1 that have not been reviewed yet."""
    data = api_get("/results", {"limit": str(limit)})
    all_results = data.get("results", [])

    # Filter to those without reviewed_at
    return [r for r in all_results if not r.get("reviewed_at")]


def run_claude_critique(skill: str, result_data: dict) -> dict | None:
    """Run Claude Opus scientific critique."""
    try:
        from reviewer.claude_reviewer import ClaudeReviewer
        reviewer = ClaudeReviewer()
        return reviewer.critique(pipeline_name=skill, result_data=result_data)
    except Exception as e:
        logger.error("Claude critique failed: %s", e)
        return None


def run_grok_review(skill: str, result_data: dict) -> dict | None:
    """Run Grok literature review."""
    try:
        from reviewer.grok_reviewer import GrokReviewer
        reviewer = GrokReviewer()
        return reviewer.review_literature(pipeline_name=skill, result_data=result_data)
    except Exception as e:
        logger.error("Grok review failed: %s", e)
        return None


def publish_critique(result_id: str, reviewer_name: str, critique: dict) -> str | None:
    """Publish a critique to the ingest worker (R2 + D1)."""
    overall_score = critique.get("overall_score")
    if overall_score is None:
        overall_score = critique.get("literature_score")

    recommendation = critique.get("recommendation")
    if recommendation is None:
        confidence = critique.get("confidence_in_finding", "low")
        recommendation = {"high": "publish", "medium": "revise", "low": "reject"}.get(
            confidence, "revise"
        )

    payload = {
        "result_id": result_id,
        "reviewer": reviewer_name,
        "overall_score": overall_score,
        "recommendation": recommendation,
        "critique_data": critique,
    }

    try:
        resp = api_post("/critiques", payload)
        return resp.get("id")
    except Exception as e:
        logger.error("Failed to publish critique for %s: %s", result_id, e)
        return None


def sweep_once(limit: int = 50, reviewer_filter: str | None = None) -> int:
    """Run one sweep pass. Returns number of critiques published."""
    logger.info("Fetching unreviewed results (limit=%d)...", limit)
    unreviewed = get_unreviewed_results(limit=limit)

    if not unreviewed:
        logger.info("No unreviewed results found.")
        return 0

    logger.info("Found %d unreviewed result(s)", len(unreviewed))
    published = 0

    for result in unreviewed:
        result_id = result["id"]
        skill = result.get("skill", "unknown")
        r2_url = result.get("r2_url", "")
        species = result.get("species", "human")

        logger.info("Reviewing %s (skill=%s, species=%s)", result_id, skill, species)

        # Fetch full result from R2
        full_result = fetch_r2_result(r2_url) if r2_url else None
        result_data = full_result.get("result_data", {}) if full_result else {}

        if not result_data:
            logger.warning("Skipping %s — empty result_data", result_id)
            continue

        # Run Claude critique
        if reviewer_filter in (None, "claude"):
            claude_crit = run_claude_critique(skill, result_data)
            if claude_crit:
                cid = publish_critique(result_id, "claude_opus", claude_crit)
                if cid:
                    logger.info("  Claude critique published: %s (score=%s, rec=%s)",
                                cid, claude_crit.get("overall_score"), claude_crit.get("recommendation"))
                    published += 1

        # Run Grok literature review
        if reviewer_filter in (None, "grok"):
            grok_rev = run_grok_review(skill, result_data)
            if grok_rev:
                cid = publish_critique(result_id, "grok_literature", grok_rev)
                if cid:
                    logger.info("  Grok review published: %s (score=%s, confidence=%s)",
                                cid, grok_rev.get("literature_score"), grok_rev.get("confidence_in_finding"))
                    published += 1

    return published


def main():
    parser = argparse.ArgumentParser(description="OpenCure Labs — Reviewer Sweep")
    parser.add_argument("--watch", action="store_true", help="Continuous mode: poll every 60s")
    parser.add_argument("--limit", type=int, default=50, help="Max results to review per sweep")
    parser.add_argument("--reviewer", choices=["claude", "grok"], help="Only run one reviewer")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds (watch mode)")
    args = parser.parse_args()

    while True:
        try:
            count = sweep_once(limit=args.limit, reviewer_filter=args.reviewer)
            logger.info("Sweep complete: %d critique(s) published", count)
        except Exception as e:
            logger.error("Sweep error: %s", e)

        if not args.watch:
            break

        logger.info("Waiting %ds before next sweep...", args.interval)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()

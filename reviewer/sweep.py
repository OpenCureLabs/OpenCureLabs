#!/usr/bin/env python3
"""OpenCure Labs — Batch Verification Sweep

Polls the ingest worker for pending results (status=pending), runs Grok
verification (shorter than full critique — validates local_critique), then
PATCHes results to published or blocked.

Uses admin key for PATCH operations. Only runs on the central VM.

Usage:
    python reviewer/sweep.py                  # One-shot: verify all pending
    python reviewer/sweep.py --watch          # Continuous: poll every 60s
    python reviewer/sweep.py --limit 20       # Verify at most 20 results
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

# Load .env for API keys
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("labclaw.reviewer.sweep")

INGEST_URL = os.environ.get("INGEST_URL", "https://ingest.opencurelabs.ai")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://pub.opencurelabs.ai")
ADMIN_KEY = os.environ.get("OPENCURELABS_ADMIN_KEY", "")
UA = "OpenCureLabs-Sweep/2.0"

# Verification thresholds
PUBLISH_THRESHOLD = 7.0
REJECT_THRESHOLD = 5.0


def api_get(path: str, params: dict | None = None) -> dict:
    """GET request to the ingest worker API."""
    url = f"{INGEST_URL}{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        url = f"{url}?{qs}"

    req = Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    with urlopen(req, timeout=30) as resp:  # noqa: S310 — trusted internal URL
        return json.loads(resp.read())


def api_patch(path: str, data: dict) -> dict:
    """PATCH request to the ingest worker API (admin-authenticated)."""
    url = f"{INGEST_URL}{path}"
    body = json.dumps(data).encode()
    req = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": UA,
            "X-Admin-Key": ADMIN_KEY,
        },
        method="PATCH",
    )
    with urlopen(req, timeout=60) as resp:  # noqa: S310 — trusted internal URL
        return json.loads(resp.read())


def fetch_r2_result(r2_url: str) -> dict | None:
    """Fetch full result JSON from R2 public CDN."""
    req = Request(r2_url, headers={"Accept": "application/json", "User-Agent": UA})
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310 — trusted CDN URL
            return json.loads(resp.read())
    except (URLError, json.JSONDecodeError) as e:
        logger.warning("Failed to fetch %s: %s", r2_url, e)
        return None


def get_pending_results(limit: int = 50) -> list[dict]:
    """Fetch pending results from D1 awaiting batch verification."""
    data = api_get("/results", {"status": "pending", "limit": str(limit)})
    return data.get("results", [])


def run_grok_verification(skill: str, result_data: dict, local_critique: dict) -> dict | None:
    """Run Grok batch verification — validates local_critique against result_data."""
    try:
        from reviewer.grok_reviewer import GrokReviewer
        grok = GrokReviewer()

        has_critique = bool(local_critique)

        # Adjust prompt based on whether a local critique exists
        if has_critique:
            verification_prompt = (
                f"A contributor submitted a {skill} result with a local Grok review.\n"
                f"Verify the local review is honest and the data supports the conclusions.\n\n"
                f"Result:\n```json\n{json.dumps(result_data, indent=2, default=str)}\n```\n\n"
                f"Local Grok Review:\n```json\n{json.dumps(local_critique, indent=2, default=str)}\n```\n\n"
                "Return JSON:\n"
                '{"verification_score": 0-10, "recommendation": "publish"|"revise"|"reject", '
                '"flags": ["list of concerns if any"], "summary": "brief assessment"}'
            )
            system_msg = (
                "You are a verification reviewer. A contributor ran a local Grok critique "
                "on their own result. Your job is to verify: (1) the local critique appears "
                "genuine and not fabricated, (2) the result data supports the stated conclusions, "
                "(3) there are no red flags. Return a concise JSON verification."
            )
        else:
            # Solo contribution — no local critique to validate.
            # Evaluate result data directly on scientific quality.
            verification_prompt = (
                f"A solo contributor submitted a {skill} result without a local review.\n"
                f"Evaluate whether the data is scientifically sound and suitable for publication.\n\n"
                f"Result:\n```json\n{json.dumps(result_data, indent=2, default=str)}\n```\n\n"
                "Return JSON:\n"
                '{"verification_score": 0-10, "recommendation": "publish"|"revise"|"reject", '
                '"flags": ["list of concerns if any"], "summary": "brief assessment"}'
            )
            system_msg = (
                "You are a scientific reviewer for the OpenCure Labs public dataset. "
                "This result was submitted by a solo contributor without a local critique — "
                "that is normal and expected. Evaluate the result data directly: "
                "(1) is it scientifically plausible, (2) does the data look internally consistent, "
                "(3) are there any red flags. If the data quality is acceptable, recommend 'publish'. "
                "Return a concise JSON verification."
            )

        response = grok.client.chat.completions.create(
            model=grok.model,
            temperature=0.0,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": verification_prompt},
            ],
        )

        response_text = response.choices[0].message.content

        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0]
        else:
            json_str = response_text

        return json.loads(json_str)
    except Exception as e:
        logger.error("Grok verification failed: %s", e)
        return None


def sweep_once(limit: int = 50) -> dict:
    """Run one verification sweep. Returns counts of actions taken."""
    logger.info("Fetching pending results (limit=%d)...", limit)
    pending = get_pending_results(limit=limit)

    if not pending:
        logger.info("No pending results found.")
        return {"published": 0, "blocked": 0, "deferred": 0, "errors": 0}

    logger.info("Found %d pending result(s)", len(pending))
    counts = {"published": 0, "blocked": 0, "deferred": 0, "errors": 0}

    for result in pending:
        result_id = result["id"]
        skill = result.get("skill", "unknown")
        r2_url = result.get("r2_url", "")

        logger.info("Verifying %s (skill=%s)", result_id, skill)

        # Fetch full result from R2
        full_result = fetch_r2_result(r2_url) if r2_url else None
        if not full_result:
            logger.warning("Skipping %s — could not fetch R2 object", result_id)
            counts["errors"] += 1
            continue

        result_data = full_result.get("result_data", {})
        local_critique = full_result.get("local_critique", {})

        if not result_data:
            logger.warning("Skipping %s — empty result_data", result_id)
            counts["errors"] += 1
            continue

        # Run verification
        verification = run_grok_verification(skill, result_data, local_critique)
        if not verification:
            counts["errors"] += 1
            continue

        score = verification.get("verification_score", 0)
        rec = verification.get("recommendation", "revise")

        # Decide action based on thresholds
        if score >= PUBLISH_THRESHOLD and rec in ("publish", "revise"):
            action = "published"
        elif score < REJECT_THRESHOLD or rec == "reject":
            action = "blocked"
        else:
            # Borderline — leave as pending for manual review
            logger.info("  Deferred %s (score=%.1f, rec=%s) — borderline", result_id, score, rec)
            counts["deferred"] += 1
            continue

        # PATCH the result status
        try:
            api_patch(f"/results/{result_id}", {
                "status": action,
                "batch_critique": verification,
            })
            logger.info("  %s %s (score=%.1f, rec=%s)", action.upper(), result_id, score, rec)
            counts[action] += 1
        except Exception as e:
            logger.error("  PATCH failed for %s: %s", result_id, e)
            counts["errors"] += 1

    return counts


def main():
    if not ADMIN_KEY:
        logger.error("OPENCURELABS_ADMIN_KEY not set — cannot PATCH results")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="OpenCure Labs — Batch Verification Sweep")
    parser.add_argument("--watch", action="store_true", help="Continuous mode: poll every 60s")
    parser.add_argument("--limit", type=int, default=50, help="Max results to verify per sweep")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds (watch mode)")
    args = parser.parse_args()

    while True:
        try:
            counts = sweep_once(limit=args.limit)
            logger.info(
                "Sweep complete: %d published, %d blocked, %d deferred, %d errors",
                counts["published"], counts["blocked"], counts["deferred"], counts["errors"],
            )
        except Exception as e:
            logger.error("Sweep error: %s", e)

        if not args.watch:
            break

        logger.info("Waiting %ds before next sweep...", args.interval)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Parameter-bank drift check — Python ↔ TypeScript.

The TypeScript module ``workers/ingest/tasks.ts`` is the source of truth for the
**central D1 task queue** (BOINC-style work distribution). The Python module
``packages/agentiq_labclaw/agentiq_labclaw/task_generator.py`` holds a smaller
"local batch" subset used by the on-prem dispatcher when running outside
contribute mode.

The two banks are intentionally different sizes (TS ≈ 150 cancer genes, Python
≈ 15 driver genes). But every gene/variant/target listed in the **Python** bank
should also exist in the **TS** bank — otherwise local batch jobs reference
parameters the central queue has never heard of, breaking dedup and result
cross-correlation.

This script asserts that one-way invariant. It exits non-zero when the Python
bank contains anything the TS bank doesn't.

Usage:
    python scripts/check_param_bank_drift.py            # human-readable
    python scripts/check_param_bank_drift.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS_FILE = ROOT / "workers" / "ingest" / "tasks.ts"


def extract_first_column(ts_text: str, const_name: str) -> set[str]:
    """Extract the first string element of each row inside ``export const NAME = [...]``.

    Handles both ``["X", "y", ...]`` tuple rows and ``{"protein_id": "X", ...}``
    object rows. Returns an empty set when the constant is not found.
    """
    pattern = re.compile(
        rf"export\s+const\s+{re.escape(const_name)}\s*(?::[^=]*)?=\s*\[(.*?)^\];",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern.search(ts_text)
    if not m:
        return set()
    body = m.group(1)
    # First quoted string on each significant line.
    items: set[str] = set()
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        # Match the first "..." literal on the line.
        sm = re.search(r'"([^"]+)"', line)
        if sm:
            items.add(sm.group(1))
    return items


def extract_flat_strings(ts_text: str, const_name: str) -> set[str]:
    """Extract *every* string literal inside a flat ``export const NAME = [...]``.

    Use this for one-dimensional string arrays like ``TUMOR_TYPES`` where
    multiple values share a line.
    """
    pattern = re.compile(
        rf"export\s+const\s+{re.escape(const_name)}\s*(?::[^=]*)?=\s*\[(.*?)^\];",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern.search(ts_text)
    if not m:
        return set()
    # Strip line comments so we don't capture string-like text inside them.
    body = re.sub(r"//.*?$", "", m.group(1), flags=re.MULTILINE)
    return set(re.findall(r'"([^"]+)"', body))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args()

    # Import the Python bank.
    sys.path.insert(0, str(ROOT / "packages" / "agentiq_labclaw"))
    from agentiq_labclaw import task_generator as tg  # type: ignore  # noqa: E402

    ts_text = TS_FILE.read_text(encoding="utf-8")

    # (python set, ts set, label)
    checks: list[tuple[set[str], set[str], str]] = [
        (
            {g[0] for g in tg.CANCER_GENES},
            extract_first_column(ts_text, "CANCER_GENES"),
            "CANCER_GENES (gene symbol)",
        ),
        (
            set(tg.TUMOR_TYPES),
            extract_flat_strings(ts_text, "TUMOR_TYPES"),
            "TUMOR_TYPES",
        ),
        (
            {t["protein_id"] for t in tg.DRUG_TARGETS},
            extract_first_column(ts_text, "DRUG_TARGETS"),
            "DRUG_TARGETS (protein_id)",
        ),
        (
            {d["name"] for d in tg.CHEMBL_DATASETS},
            extract_first_column(ts_text, "CHEMBL_DATASETS"),
            "CHEMBL_DATASETS (name)",
        ),
        (
            {v["variant_id"] for v in tg.RARE_DISEASE_VARIANTS},
            extract_first_column(ts_text, "RARE_DISEASE_VARIANTS"),
            "RARE_DISEASE_VARIANTS (variant_id)",
        ),
    ]

    report: dict[str, dict] = {}
    failed = False
    for py_set, ts_set, label in checks:
        missing_in_ts = sorted(py_set - ts_set)
        report[label] = {
            "python_count": len(py_set),
            "ts_count": len(ts_set),
            "missing_from_ts": missing_in_ts,
        }
        if missing_in_ts:
            failed = True

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Parameter-bank drift check")
        print("=" * 60)
        for label, data in report.items():
            status = "FAIL" if data["missing_from_ts"] else "OK  "
            print(
                f"  [{status}] {label}: python={data['python_count']} "
                f"ts={data['ts_count']}"
            )
            for item in data["missing_from_ts"]:
                print(f"          missing from TS: {item!r}")
        print("=" * 60)
        if failed:
            print(
                "DRIFT DETECTED. Add the missing entries to "
                "workers/ingest/tasks.ts so the central queue can dedup and "
                "cross-correlate results from local batches."
            )
        else:
            print("No drift — Python bank is a subset of TS bank.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

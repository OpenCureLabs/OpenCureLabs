"""Auto-download helpers for public biological data.

Each function checks for a local cached copy first; if absent, downloads from a
public API and caches under a deterministic directory.  All network calls use
explicit timeouts and raise on HTTP errors.

Public data sources:
    - PDB files: RCSB Protein Data Bank (https://files.rcsb.org)
    - ChEMBL bioactivity: ChEMBL REST API (https://www.ebi.ac.uk/chembl/api)
"""

from __future__ import annotations

import logging
import math
import tempfile
from pathlib import Path

import requests

logger = logging.getLogger("labclaw.data.fetch")

CACHE_DIR = Path(tempfile.gettempdir()) / "labclaw_data"

# ── PDB ──────────────────────────────────────────────────────────────────────

RCSB_URL = "https://files.rcsb.org/download"


def fetch_pdb(pdb_id: str) -> Path:
    """Download a PDB file from RCSB if not already cached.

    Args:
        pdb_id: 4-character PDB identifier (e.g. ``1M17``).

    Returns:
        Path to the downloaded ``.pdb`` file.
    """
    pdb_id = pdb_id.strip().upper()
    dest = CACHE_DIR / "pdb" / f"{pdb_id}.pdb"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    url = f"{RCSB_URL}/{pdb_id}.pdb"
    logger.info("Downloading PDB %s from RCSB …", pdb_id)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(resp.text)
    logger.info("Cached PDB %s → %s (%d bytes)", pdb_id, dest, dest.stat().st_size)
    return dest


# ── ChEMBL CSV ───────────────────────────────────────────────────────────────

CHEMBL_API = "https://www.ebi.ac.uk/chembl/api/data/activity.json"


def fetch_chembl_csv(
    target_chembl_id: str,
    target_col: str = "pIC50",
    limit: int = 500,
) -> Path:
    """Download bioactivity data for a ChEMBL target as CSV.

    The result CSV contains columns: ``smiles``, ``molecule_chembl_id``, and
    the requested *target_col* (e.g. ``pIC50``).

    Args:
        target_chembl_id: ChEMBL target ID (e.g. ``CHEMBL203``).
        target_col:       Name for the activity column.
        limit:            Max rows to fetch (API caps at 1000).

    Returns:
        Path to the cached CSV file.
    """
    import pandas as pd

    safe = target_chembl_id.replace("/", "_")
    dest = CACHE_DIR / "chembl" / f"{safe}.csv"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    logger.info("Fetching ChEMBL bioactivity for %s …", target_chembl_id)

    rows: list[dict] = []
    params = {
        "target_chembl_id": target_chembl_id,
        "type": "IC50",
        "limit": min(limit, 1000),
        "format": "json",
    }
    resp = requests.get(CHEMBL_API, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    for act in data.get("activities", []):
        smi = act.get("canonical_smiles")
        val = act.get("value")
        mol_id = act.get("molecule_chembl_id")
        if smi and val:
            try:
                val_f = float(val)
                pval = -math.log10(val_f * 1e-9) if val_f > 0 else 0.0
            except (ValueError, TypeError):
                continue
            rows.append({
                "smiles": smi,
                "molecule_chembl_id": mol_id,
                target_col: round(pval, 4),
            })

    if not rows:
        raise ValueError(
            f"No bioactivity data found for ChEMBL target '{target_chembl_id}'. "
            "Verify the target ID is correct or provide a local CSV with bioactivity data."
        )

    df = pd.DataFrame(rows)
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest, index=False)
    logger.info("Cached ChEMBL CSV → %s (%d rows)", dest, len(df))
    return dest




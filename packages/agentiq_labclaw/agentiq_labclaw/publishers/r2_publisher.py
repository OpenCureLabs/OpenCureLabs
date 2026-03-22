"""Cloudflare R2 universal result publisher.

Posts signed results to the OpenCure Labs ingest Worker, which verifies the
Ed25519 signature, writes the full object to R2, and indexes a row in D1.

Users need OPENCURELABS_INGEST_URL in their .env — no cloud credentials are
required or distributed. An Ed25519 keypair is generated on first use and
stored at ~/.opencurelabs/signing_key.

Contributor ID:
    Generated on first use as a UUID4 and stored in ~/.opencurelabs/contributor_id.
    Included in every POST so bad-actor submissions can be removed by contributor_id
    in D1 without affecting other contributors. Never returned in public GET responses.
"""

import json
import logging
import os
import uuid
from pathlib import Path

import requests

from agentiq_labclaw.publishers.signing import get_or_create_keypair, sign_payload

logger = logging.getLogger("labclaw.publishers.r2")

_ENV_INGEST_URL = "OPENCURELABS_INGEST_URL"
_CONTRIBUTOR_ID_PATH = Path.home() / ".opencurelabs" / "contributor_id"


def _get_contributor_id() -> str:
    """Return a stable machine contributor ID, generating one on first call."""
    try:
        _CONTRIBUTOR_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _CONTRIBUTOR_ID_PATH.exists():
            return _CONTRIBUTOR_ID_PATH.read_text().strip()
        contributor_id = str(uuid.uuid4())
        _CONTRIBUTOR_ID_PATH.write_text(contributor_id)
        logger.info("Generated contributor ID: %s", contributor_id)
        return contributor_id
    except Exception as e:
        logger.debug("Could not persist contributor ID: %s", e)
        return str(uuid.uuid4())


def _extract_summary(result_data: dict) -> dict:
    """Extract lightweight summary fields for the D1 index."""
    summary: dict = {}
    for field in ("confidence_score", "gene", "best_affinity", "auc_roc"):
        if field in result_data:
            summary[field] = result_data[field]
    return summary


def _extract_species(result_data: dict) -> str:
    """Return the species string embedded in result_data, defaulting to 'human'."""
    species = result_data.get("species", "human")
    return species if isinstance(species, str) and species else "human"


class R2Publisher:
    """Publishes signed results to OpenCure Labs' global R2 dataset via the ingest Worker.

    Silently no-ops when OPENCURELABS_INGEST_URL is not set, so Postgres-only
    deployments are unaffected.
    """

    def __init__(self) -> None:
        self.ingest_url = os.environ.get(_ENV_INGEST_URL, "").rstrip("/")
        self._contributor_id: str | None = None
        self._signing_key = None
        self._verify_key_hex: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.ingest_url)

    @property
    def contributor_id(self) -> str:
        if self._contributor_id is None:
            self._contributor_id = _get_contributor_id()
        return self._contributor_id

    def _ensure_keypair(self) -> None:
        if self._signing_key is None:
            self._signing_key, self._verify_key_hex = get_or_create_keypair()

    def publish_result(
        self,
        skill_name: str,
        result_data: dict,
        novel: bool = False,
        status: str = "pending",
        local_critique: dict | None = None,
    ) -> dict | None:
        """POST a signed result to the ingest Worker.

        Returns {id, url} on success, None if disabled or on error.
        """
        if not self.ingest_url:
            return None

        self._ensure_keypair()

        payload = {
            "skill": skill_name,
            "result_data": result_data,
            "novel": novel,
            "status": status,
            "contributor_id": self.contributor_id,
            "species": _extract_species(result_data),
            "summary": _extract_summary(result_data),
        }
        if local_critique:
            payload["local_critique"] = local_critique

        signature = sign_payload(self._signing_key, payload)
        headers = {
            "X-Contributor-Key": self._verify_key_hex,
            "X-Signature": signature,
            "Content-Type": "application/json",
        }

        # Send the canonical JSON (sorted keys, no whitespace) as the body.
        # This is the exact byte string that was signed, avoiding any
        # parse/re-serialize mismatch between Python and JS (e.g. 42.0 vs 42).
        canonical_body = json.dumps(payload, sort_keys=True, separators=(",", ":"))

        url = f"{self.ingest_url}/results" if not self.ingest_url.endswith("/results") else self.ingest_url

        try:
            resp = requests.post(url, data=canonical_body, headers=headers, timeout=15)

            # Auto-register on first contribution (401 = unknown contributor)
            if resp.status_code == 401:
                self._register_contributor()
                resp = requests.post(url, data=canonical_body, headers=headers, timeout=15)

            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("R2 publish failed (result not lost — still stored locally): %s", e)
            return None

    def _register_contributor(self) -> None:
        """Register this contributor's public key with the ingest Worker."""
        try:
            resp = requests.post(
                f"{self.ingest_url}/contributors",
                json={
                    "contributor_id": self.contributor_id,
                    "public_key": self._verify_key_hex,
                },
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("Registered new contributor key. Results will appear after review.")
        except requests.RequestException as e:
            logger.warning("Contributor registration failed: %s", e)

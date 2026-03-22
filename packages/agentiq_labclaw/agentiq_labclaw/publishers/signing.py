"""Ed25519 result signing for OpenCure Labs contributions.

Every contributor has a local keypair stored at ~/.opencurelabs/signing_key.
Results are signed before POST to the ingest Worker, which verifies the
signature using the contributor's registered public key.
"""

import base64
import json
import logging
from pathlib import Path

import nacl.signing

logger = logging.getLogger("labclaw.publishers.signing")

_KEY_PATH = Path.home() / ".opencurelabs" / "signing_key"


def get_or_create_keypair() -> tuple[nacl.signing.SigningKey, str]:
    """Load or generate an Ed25519 keypair.

    Returns:
        Tuple of (SigningKey object, hex-encoded verify/public key).
    """
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)

    if _KEY_PATH.exists():
        seed = _KEY_PATH.read_bytes()
        signing_key = nacl.signing.SigningKey(seed)
    else:
        signing_key = nacl.signing.SigningKey.generate()
        _KEY_PATH.write_bytes(bytes(signing_key))
        _KEY_PATH.chmod(0o600)
        logger.info("Generated new Ed25519 signing key at %s", _KEY_PATH)

    verify_key_hex = signing_key.verify_key.encode().hex()
    return signing_key, verify_key_hex


def sign_payload(signing_key: nacl.signing.SigningKey, payload: dict) -> str:
    """Sign a payload dict and return a base64-encoded signature.

    The payload is serialised to canonical JSON (sorted keys, no whitespace)
    before signing, ensuring deterministic signatures.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signed = signing_key.sign(canonical)
    # signed.signature is the detached 64-byte Ed25519 signature
    return base64.b64encode(signed.signature).decode()

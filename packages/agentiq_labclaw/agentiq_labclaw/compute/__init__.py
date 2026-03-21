"""Compute module — Vast.ai dispatcher, batch queue, and instance pool for GPU workloads."""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger("labclaw.compute")

GITHUB_API = "https://api.github.com"
VAST_API = "https://console.vast.ai/api/v0"
DEFAULT_REPO = "OpenCureLabs/OpenCureLabs"
SSH_KEY_PATH = os.path.expanduser("~/.ssh/xpclabs")


def resolve_wheel_url() -> str | None:
    """Resolve the latest agentiq_labclaw wheel URL from GitHub Releases.

    Uses the GitHub API to find the latest release and return the download URL
    for the first .whl asset.  Returns None if no wheel is found.

    Respects GITHUB_REPOSITORY env var so forks resolve their own releases.
    Uses GITHUB_TOKEN for private repos — returns the API asset URL (which
    requires Accept: application/octet-stream + auth to download).
    """
    repo = os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO)
    url = f"{GITHUB_API}/repos/{repo}/releases/latest"
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {}
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        for asset in resp.json().get("assets", []):
            if asset["name"].endswith(".whl"):
                if token:
                    # Private repo: use API URL (requires auth + Accept header)
                    return asset["url"]
                # Public repo: browser URL works directly
                return asset["browser_download_url"]
    except Exception as exc:
        logger.warning("Failed to resolve wheel URL from %s: %s", url, exc)
    return None


def build_onstart_script(wheel_url: str | None = None) -> str:
    """Build the Vast.ai onstart bash script for instance setup.

    If a wheel_url is provided, installs from the pre-built wheel (~seconds).
    Otherwise falls back to cloning the full repo via git+https (~minutes).

    For private repos, injects a GITHUB_TOKEN header so the instance can
    download the release asset.
    """
    gh_token = os.environ.get("GITHUB_TOKEN", "")

    if wheel_url:
        if gh_token and "api.github.com" in wheel_url:
            # Private repo: download via GitHub API with auth + octet-stream
            # Use proper wheel filename so pip accepts it
            install_cmd = (
                f"curl -sL -H 'Authorization: token {gh_token}' "
                f"-H 'Accept: application/octet-stream' "
                f"'{wheel_url}' -o /tmp/agentiq_labclaw-latest-py3-none-any.whl && "
                "pip install --no-deps /tmp/agentiq_labclaw-latest-py3-none-any.whl"
            )
        else:
            # Public repo: direct URL works
            install_cmd = f"pip install --no-deps '{wheel_url}'"
    else:
        # Fallback: full repo clone (slow but always works)
        repo = os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO)
        if gh_token:
            pip_url = f"git+https://{gh_token}@github.com/{repo}.git#subdirectory=packages/agentiq_labclaw"
        else:
            pip_url = f"git+https://github.com/{repo}.git#subdirectory=packages/agentiq_labclaw"
        install_cmd = f"GIT_CLONE_PROTECTION_ACTIVE=false pip install --no-deps '{pip_url}'"

    # Core deps not present in pytorch/pytorch:latest image
    core_deps = "pydantic>=2.0 psycopg2-binary>=2.9 requests>=2.28"

    return (
        "#!/bin/bash\n"
        "set -e\n"
        "exec > /tmp/labclaw_setup.log 2>&1\n"
        "echo '[labclaw] Starting setup...'\n"
        f"pip install --quiet {core_deps} && "
        "echo '[labclaw] deps OK' || "
        "{ echo '[labclaw] deps FAILED'; exit 1; }\n"
        f"{install_cmd} && "
        "echo '[labclaw] pip install OK' || "
        "{ echo '[labclaw] pip install FAILED'; exit 1; }\n"
        "touch /tmp/labclaw_ready\n"
        "echo '[labclaw] Setup complete'\n"
    )


def attach_ssh_key(instance_id: int) -> bool:
    """Attach the local SSH public key to a Vast.ai instance.

    Reads the public key from SSH_KEY_PATH (.pub) and POSTs it to the
    Vast.ai instance SSH endpoint.  Returns True on success.

    This is required because registering a key on the Vast.ai *account*
    does not automatically authorize it on new instances.
    """
    pub_path = f"{SSH_KEY_PATH}.pub"
    try:
        with open(pub_path) as f:
            pub_key = f.read().strip()
    except FileNotFoundError:
        logger.warning("SSH public key not found at %s — skipping attach", pub_path)
        return False

    api_key = os.environ.get("VAST_AI_KEY", "")
    try:
        resp = requests.post(
            f"{VAST_API}/instances/{instance_id}/ssh/",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"ssh_key": pub_key},
            timeout=15,
        )
        if resp.status_code == 200 and resp.json().get("success"):
            logger.debug("SSH key attached to instance %d", instance_id)
            return True
        logger.warning("SSH attach to %d: %s", instance_id, resp.text[:200])
    except Exception as exc:
        logger.warning("SSH attach to %d failed: %s", instance_id, exc)
    return False

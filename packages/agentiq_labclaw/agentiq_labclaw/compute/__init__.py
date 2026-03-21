"""Compute module — Vast.ai dispatcher, batch queue, and instance pool for GPU workloads."""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger("labclaw.compute")

GITHUB_API = "https://api.github.com"
DEFAULT_REPO = "OpenCureLabs/OpenCureLabs"


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
            install_cmd = (
                f"curl -sL -H 'Authorization: token {gh_token}' "
                f"-H 'Accept: application/octet-stream' "
                f"'{wheel_url}' -o /tmp/labclaw.whl && "
                "pip install --no-deps /tmp/labclaw.whl"
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

    return (
        "#!/bin/bash\n"
        "set -e\n"
        "exec > /tmp/labclaw_setup.log 2>&1\n"
        "echo '[labclaw] Starting setup...'\n"
        f"{install_cmd} && "
        "echo '[labclaw] pip install OK' || "
        "{ echo '[labclaw] pip install FAILED'; exit 1; }\n"
        "touch /tmp/labclaw_ready\n"
        "echo '[labclaw] Setup complete'\n"
    )

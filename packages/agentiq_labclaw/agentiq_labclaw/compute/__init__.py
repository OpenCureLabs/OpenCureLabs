"""Compute module — Vast.ai dispatcher, batch queue, and instance pool for GPU workloads."""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger("labclaw.compute")

GITHUB_API = "https://api.github.com"
VAST_API = "https://console.vast.ai/api/v0"
DEFAULT_REPO = "OpenCureLabs/OpenCureLabs"
SSH_KEY_PATH = os.path.expanduser(os.environ.get("SSH_KEY_NAME", "~/.ssh/opencurelabs"))


def resolve_wheel_url() -> str | None:
    """Resolve the latest agentiq_labclaw wheel URL from GitHub Releases.

    Uses the GitHub API to find the latest release and return the download URL
    for the first .whl asset.  Returns None if no wheel is found.

    Respects GITHUB_REPOSITORY env var so forks resolve their own releases.
    """
    repo = os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO)
    url = f"{GITHUB_API}/repos/{repo}/releases/latest"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        for asset in resp.json().get("assets", []):
            if asset["name"].endswith(".whl"):
                return asset["browser_download_url"]
    except Exception as exc:
        logger.warning("Failed to resolve wheel URL from %s: %s", url, exc)
    return None


def build_onstart_script(wheel_url: str | None = None) -> str:
    """Build the Vast.ai onstart bash script for instance setup.

    If a wheel_url is provided, installs from the pre-built wheel (~seconds).
    Otherwise falls back to cloning the full repo via git+https (~minutes).

    Also injects the orchestrator SSH public key directly into authorized_keys
    so SSH access is guaranteed regardless of whether the Vast.ai API key
    attachment endpoint succeeds.
    """
    if wheel_url:
        install_cmd = f"pip install --no-deps '{wheel_url}'"
    else:
        # Fallback: full repo clone (slow but always works)
        repo = os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO)
        pip_url = f"git+https://github.com/{repo}.git#subdirectory=packages/agentiq_labclaw"
        install_cmd = f"GIT_CLONE_PROTECTION_ACTIVE=false pip install --no-deps '{pip_url}'"

    # Core deps — only needed when running on base pytorch image (not labclaw-gpu)
    # The custom Docker image already has these pre-installed.
    core_deps = "pydantic>=2.0 psycopg2-binary>=2.9 requests>=2.28"

    # Heartbeat-based self-destruct: instance shuts itself down if no
    # heartbeat file is touched within TTL seconds.  Workers touch the file
    # after each completed job, so long-running workloads stay alive while
    # orphaned instances (crashed orchestrator) still get cleaned up.
    ttl = os.environ.get("LABCLAW_INSTANCE_TTL", "3600")  # default 60 min

    # Inject orchestrator SSH public key directly into authorized_keys.
    # This guarantees SSH access even if the Vast.ai API key-attach call fails.
    ssh_key_inject = ""
    pub_path = f"{SSH_KEY_PATH}.pub"
    try:
        with open(pub_path) as _f:
            pub_key = _f.read().strip()
        ssh_key_inject = (
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh\n"
            f"echo '{pub_key}' >> ~/.ssh/authorized_keys\n"
            "chmod 600 ~/.ssh/authorized_keys\n"
            "echo '[labclaw] SSH key injected'\n"
        )
    except FileNotFoundError:
        logger.debug("SSH public key not found at %s — skipping injection", pub_path)

    return (
        "#!/bin/bash\n"
        "set -e\n"
        "exec > /tmp/labclaw_setup.log 2>&1\n"
        "echo '[labclaw] Starting setup...'\n"
        f"{ssh_key_inject}"
        "# Heartbeat-based self-destruct: shuts down if heartbeat stale for TTL\n"
        "touch /tmp/labclaw_heartbeat\n"
        f"(while true; do sleep 60; "
        f"age=$(($(date +%s) - $(stat -c %Y /tmp/labclaw_heartbeat))); "
        f"if [ \"$age\" -gt {ttl} ]; then "
        "echo '[labclaw] Heartbeat stale — self-destructing' "
        ">> /tmp/labclaw_setup.log; shutdown -h now; fi; done) &\n"
        "echo \"[labclaw] Heartbeat self-destruct armed (" + ttl + "s idle TTL)\"\n"
        "# Install core deps only if not already present (custom image skips this)\n"
        "python -c 'import pydantic; import psycopg2; import requests' 2>/dev/null || "
        f"{{ pip install --quiet {core_deps} && "
        "echo '[labclaw] deps OK'; } || "
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

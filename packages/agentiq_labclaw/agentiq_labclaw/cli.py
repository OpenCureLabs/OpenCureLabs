"""
opencure CLI — management commands for OpenCure Labs.

Usage:
    opencure burst on [--max-cost N]   Enable Vast.ai burst compute
    opencure burst off                 Disable burst + destroy orphan instances
    opencure burst status              Show current mode and active instances
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

VAST_API = "https://console.vast.ai/api/v0"
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

# ── Colors ───────────────────────────────────────────────────────────────────
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
BOLD = "\033[1m"
NC = "\033[0m"


def _vast_headers() -> dict:
    key = os.environ.get("VAST_AI_KEY") or _read_env_key("VAST_AI_KEY")
    if not key:
        print(f"{RED}VAST_AI_KEY not set in .env or environment.{NC}")
        print(f"Get one at https://cloud.vast.ai/account/ and add to {ENV_FILE}")
        sys.exit(1)
    return {"Authorization": f"Bearer {key}"}


def _read_env_key(name: str) -> str | None:
    """Read a key from the .env file."""
    if not ENV_FILE.exists():
        return None
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{name}=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return None


def _read_env_compute_mode() -> str:
    return _read_env_key("LABCLAW_COMPUTE") or "local"


def _set_env_key(name: str, value: str):
    """Set or update a key in .env, preserving other lines."""
    if not ENV_FILE.exists():
        ENV_FILE.write_text(f"{name}={value}\n")
        return

    lines = ENV_FILE.read_text().splitlines()
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{name}=") and not stripped.startswith("#"):
            lines[i] = f"{name}={value}"
            found = True
            break
    if not found:
        lines.append(f"{name}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


def _list_instances(headers: dict) -> list[dict]:
    """Get all Vast.ai instances for this account."""
    resp = requests.get(f"{VAST_API}/instances/", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json().get("instances", [])


def _opencure_instances(headers: dict) -> list[dict]:
    """Get Vast.ai instances tagged with opencurelabs."""
    instances = _list_instances(headers)
    return [i for i in instances if i.get("label") == "opencurelabs"
            or i.get("client_id") == "opencurelabs"]


def _destroy_instance(headers: dict, instance_id: int):
    """Destroy a single Vast.ai instance."""
    requests.delete(
        f"{VAST_API}/instances/{instance_id}/",
        headers=headers,
        timeout=30,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  burst on
# ═══════════════════════════════════════════════════════════════════════════
def burst_on(args):
    """Enable Vast.ai burst compute."""
    headers = _vast_headers()

    # Query offers
    query = {
        "verified": {"eq": True},
        "rentable": {"eq": True},
        "disk_space": {"gte": 20},
        "inet_down": {"gte": 100},
        "gpu_ram": {"gte": 8},
        "num_gpus": {"gte": 1},
    }

    resp = requests.get(
        f"{VAST_API}/bundles/",
        headers=headers,
        params={"q": json.dumps(query), "order": "dph_total", "limit": 10},
        timeout=30,
    )
    resp.raise_for_status()
    offers = resp.json().get("offers", [])

    if not offers:
        print(f"{RED}No GPU instances available on Vast.ai right now.{NC}")
        sys.exit(1)

    # Apply cost cap
    if args.max_cost:
        offers = [o for o in offers if o.get("dph_total", 999) <= args.max_cost]
        if not offers:
            print(f"{RED}No offers under ${args.max_cost:.2f}/hr.{NC}")
            print("Try a higher --max-cost or check availability later.")
            sys.exit(1)

    # Display offers
    print(f"\n{BOLD}Available Vast.ai GPU instances:{NC}\n")
    print(f"  {'GPU':<22} {'VRAM':>6} {'$/hr':>7}  {'Location'}")
    print(f"  {'─'*22} {'─'*6} {'─'*7}  {'─'*20}")
    for o in offers[:5]:
        gpu = o.get("gpu_name", "Unknown")
        vram = o.get("gpu_ram", 0)
        cost = o.get("dph_total", 0)
        loc = o.get("geolocation", "Unknown")
        print(f"  {gpu:<22} {vram:>5.0f}G ${cost:>6.3f}  {loc}")

    cheapest = offers[0]
    cost = cheapest.get("dph_total", 0)
    gpu = cheapest.get("gpu_name", "Unknown")
    print(f"\n{GREEN}Cheapest: {gpu} — ${cost:.3f}/hr{NC}")

    # Set mode
    _set_env_key("LABCLAW_COMPUTE", "vast_ai")
    os.environ["LABCLAW_COMPUTE"] = "vast_ai"

    print(f"\n{GREEN}{BOLD}Burst compute ENABLED{NC}")
    print("  Mode: vast_ai")
    print("  Skills will dispatch to Vast.ai for GPU workloads.")
    print(f"  Run {BOLD}opencure burst off{NC} when done to stop billing.\n")


# ═══════════════════════════════════════════════════════════════════════════
#  burst off
# ═══════════════════════════════════════════════════════════════════════════
def burst_off(_args):
    """Disable burst compute and destroy orphan instances."""
    _set_env_key("LABCLAW_COMPUTE", "local")
    os.environ["LABCLAW_COMPUTE"] = "local"

    print(f"\n{BOLD}Burst compute DISABLED{NC} — mode set to local\n")

    # Orphan scan
    key = os.environ.get("VAST_AI_KEY") or _read_env_key("VAST_AI_KEY")
    if not key:
        print(f"  {YELLOW}No VAST_AI_KEY — skipping instance cleanup.{NC}\n")
        return

    headers = {"Authorization": f"Bearer {key}"}
    orphans = _opencure_instances(headers)

    if not orphans:
        print(f"  {GREEN}No active opencurelabs instances found.{NC}\n")
        return

    print(f"  {YELLOW}Found {len(orphans)} active instance(s) — destroying:{NC}")
    for inst in orphans:
        iid = inst.get("id")
        gpu = inst.get("gpu_name", "Unknown")
        cost = inst.get("dph_total", 0)
        print(f"    Destroying instance {iid} ({gpu}, ${cost:.3f}/hr)...", end=" ")
        try:
            _destroy_instance(headers, iid)
            print(f"{GREEN}done{NC}")
        except Exception as e:
            print(f"{RED}failed: {e}{NC}")

    print(f"\n  {GREEN}Cleanup complete.{NC}\n")


# ═══════════════════════════════════════════════════════════════════════════
#  burst status
# ═══════════════════════════════════════════════════════════════════════════
def burst_status(_args):
    """Show current burst compute status."""
    mode = _read_env_compute_mode()
    color = GREEN if mode == "local" else YELLOW

    print(f"\n{BOLD}OpenCure Labs — Compute Status{NC}\n")
    print(f"  Mode: {color}{BOLD}{mode}{NC}")

    if mode == "local":
        print("  Skills run on local hardware (CPU/GPU).")
    else:
        print("  Skills dispatch to Vast.ai for GPU workloads.")

    # Check for active instances
    key = os.environ.get("VAST_AI_KEY") or _read_env_key("VAST_AI_KEY")
    if not key:
        print(f"\n  {YELLOW}VAST_AI_KEY not set — cannot check active instances.{NC}\n")
        return

    headers = {"Authorization": f"Bearer {key}"}
    try:
        instances = _opencure_instances(headers)
    except Exception:
        print(f"\n  {YELLOW}Could not reach Vast.ai API.{NC}\n")
        return

    if not instances:
        print(f"\n  Active instances: {GREEN}none{NC}\n")
    else:
        print(f"\n  Active instances: {YELLOW}{len(instances)}{NC}")
        for inst in instances:
            iid = inst.get("id")
            gpu = inst.get("gpu_name", "Unknown")
            cost = inst.get("dph_total", 0)
            status = inst.get("actual_status", "unknown")
            print(f"    #{iid}: {gpu} — ${cost:.3f}/hr — {status}")
        print()


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        prog="opencure",
        description="OpenCure Labs management CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # burst
    burst_parser = sub.add_parser("burst", help="Manage Vast.ai burst compute")
    burst_sub = burst_parser.add_subparsers(dest="action")

    on_parser = burst_sub.add_parser("on", help="Enable burst compute")
    on_parser.add_argument(
        "--max-cost", type=float, default=None,
        help="Maximum $/hr for GPU instance (e.g., 2.00)",
    )
    on_parser.set_defaults(func=burst_on)

    off_parser = burst_sub.add_parser("off", help="Disable burst + cleanup instances")
    off_parser.set_defaults(func=burst_off)

    status_parser = burst_sub.add_parser("status", help="Show compute mode + instances")
    status_parser.set_defaults(func=burst_status)

    args = parser.parse_args()

    if not hasattr(args, "func"):
        if args.command == "burst":
            burst_status(args)
        else:
            parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()

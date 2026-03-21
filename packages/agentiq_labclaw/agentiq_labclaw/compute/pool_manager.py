"""
Vast.ai instance pool manager — provisions and manages a fleet of GPU instances.

Handles concurrent provisioning, readiness detection, auto-scaling, and teardown.
Instances are tracked in the vast_pool PostgreSQL table.

Usage:
    from agentiq_labclaw.compute.pool_manager import PoolManager

    pool = PoolManager(target_size=10, gpu_required=True, max_cost_hr=0.50)
    pool.scale_up()                   # provision instances to target_size
    ready = pool.get_ready_instances() # instances with setup complete
    pool.scale_down()                 # destroy idle instances
    pool.teardown()                   # destroy all instances
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import requests

logger = logging.getLogger("labclaw.compute.pool_manager")

VAST_API = "https://console.vast.ai/api/v0"
SSH_KEY_PATH = os.path.expanduser("~/.ssh/xpclabs")


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class PoolInstance:
    """Represents one Vast.ai instance in the pool."""
    instance_id: int
    ssh_host: str | None = None
    ssh_port: int = 22
    gpu_name: str = ""
    cost_per_hr: float = 0.0
    status: str = "provisioning"  # provisioning | setup | ready | busy | failed | destroyed
    jobs_done: int = 0


# ── DB helpers ───────────────────────────────────────────────────────────────

def _get_conn():
    import psycopg2
    db_url = os.environ.get("POSTGRES_URL", "dbname=opencurelabs port=5433")
    return psycopg2.connect(db_url)


def _db_register_instance(inst: PoolInstance):
    """Insert a new instance into vast_pool."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO vast_pool (instance_id, ssh_host, ssh_port, gpu_name, cost_per_hr, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (instance_id) DO UPDATE
            SET ssh_host = EXCLUDED.ssh_host,
                ssh_port = EXCLUDED.ssh_port,
                status = EXCLUDED.status
            """,
            (inst.instance_id, inst.ssh_host, inst.ssh_port, inst.gpu_name, inst.cost_per_hr, inst.status),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _db_update_status(instance_id: int, status: str, **kwargs):
    """Update an instance's status in vast_pool."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        ssh_host = kwargs.get("ssh_host")
        ssh_port = kwargs.get("ssh_port")
        if status == "ready":
            cur.execute(
                "UPDATE vast_pool SET status = %s, ssh_host = COALESCE(%s, ssh_host), "
                "ssh_port = COALESCE(%s, ssh_port), ready_at = NOW() WHERE instance_id = %s",
                (status, ssh_host, ssh_port, instance_id),
            )
        elif status == "destroyed":
            cur.execute(
                "UPDATE vast_pool SET status = %s, destroyed_at = NOW() WHERE instance_id = %s",
                (status, instance_id),
            )
        elif ssh_host is not None or ssh_port is not None:
            cur.execute(
                "UPDATE vast_pool SET status = %s, ssh_host = COALESCE(%s, ssh_host), "
                "ssh_port = COALESCE(%s, ssh_port) WHERE instance_id = %s",
                (status, ssh_host, ssh_port, instance_id),
            )
        else:
            cur.execute(
                "UPDATE vast_pool SET status = %s WHERE instance_id = %s",
                (status, instance_id),
            )
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _db_increment_jobs(instance_id: int):
    """Increment jobs_done counter for an instance."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE vast_pool SET jobs_done = jobs_done + 1 WHERE instance_id = %s",
            (instance_id,),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


def _db_get_pool() -> list[dict]:
    """Get all non-destroyed instances from vast_pool."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT instance_id, ssh_host, ssh_port, gpu_name, cost_per_hr, status, jobs_done
            FROM vast_pool
            WHERE status != 'destroyed'
            ORDER BY created_at
            """
        )
        rows = cur.fetchall()
        cur.close()
        return [
            {
                "instance_id": r[0], "ssh_host": r[1], "ssh_port": r[2],
                "gpu_name": r[3], "cost_per_hr": r[4], "status": r[5], "jobs_done": r[6],
            }
            for r in rows
        ]
    finally:
        conn.close()


# ── Vast.ai API helpers ─────────────────────────────────────────────────────

def _vast_headers() -> dict:
    api_key = os.environ.get("VAST_AI_KEY", "")
    return {"Authorization": f"Bearer {api_key}"}


def _find_offers(gpu_required: bool, max_cost_hr: float, count: int = 20) -> list[dict]:
    """Search Vast.ai for cheap GPU offers."""
    query: dict = {
        "verified": {"eq": True},
        "rentable": {"eq": True},
        "disk_space": {"gte": 20},
        "inet_down": {"gte": 100},
        "dph_total": {"lte": max_cost_hr},
    }
    if gpu_required:
        query["gpu_ram"] = {"gte": 8}
        query["num_gpus"] = {"gte": 1}

    resp = requests.get(
        f"{VAST_API}/bundles/",
        headers=_vast_headers(),
        params={"q": json.dumps(query), "order": "dph_total", "limit": count},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("offers", [])


def _provision_one(offer_id: int, image: str = "pytorch/pytorch:latest") -> int:
    """Provision a single Vast.ai instance. Returns instance_id."""
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    if gh_token:
        pip_url = f"git+https://{gh_token}@github.com/OpenCureLabs/OpenCureLabs.git#subdirectory=packages/agentiq_labclaw"
    else:
        pip_url = "git+https://github.com/OpenCureLabs/OpenCureLabs.git#subdirectory=packages/agentiq_labclaw"

    onstart = (
        "#!/bin/bash\n"
        f"pip install '{pip_url}' 2>&1 | tail -5\n"
        "touch /tmp/labclaw_ready\n"
    )

    payload = {
        "client_id": "opencurelabs",
        "image": image,
        "disk": 20,
        "onstart": onstart,
    }
    resp = requests.put(
        f"{VAST_API}/asks/{offer_id}/",
        headers=_vast_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    instance_id = data.get("new_contract")
    if not instance_id:
        raise RuntimeError(f"Failed to provision from offer {offer_id}: {data}")
    return instance_id


def _poll_instance(instance_id: int) -> dict:
    """Get current instance info from Vast.ai API."""
    resp = requests.get(
        f"{VAST_API}/instances/{instance_id}/",
        headers=_vast_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _destroy_instance(instance_id: int):
    """Terminate and delete a Vast.ai instance."""
    try:
        requests.delete(
            f"{VAST_API}/instances/{instance_id}/",
            headers=_vast_headers(),
            timeout=30,
        )
        logger.info("Destroyed instance %d", instance_id)
    except requests.RequestException as e:
        logger.error("Failed to destroy instance %d: %s", instance_id, e)


def _check_setup_ready(ssh_host: str, ssh_port: int) -> bool:
    """Check if the onstart script has finished (marker file exists)."""
    try:
        result = subprocess.run(
            [
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                "-i", SSH_KEY_PATH,
                "-p", str(ssh_port),
                f"root@{ssh_host}",
                "test -f /tmp/labclaw_ready && echo READY || echo WAIT",
            ],
            capture_output=True, text=True, timeout=10,
        )
        return "READY" in result.stdout
    except Exception:
        return False


# ── Pool Manager ─────────────────────────────────────────────────────────────

class PoolManager:
    """Manages a fleet of Vast.ai GPU instances for batch compute."""

    def __init__(
        self,
        target_size: int = 10,
        gpu_required: bool = True,
        max_cost_hr: float = 0.50,
    ):
        self.target_size = target_size
        self.gpu_required = gpu_required
        self.max_cost_hr = max_cost_hr
        self.instances: dict[int, PoolInstance] = {}

        # Reload any existing pool from DB
        for row in _db_get_pool():
            self.instances[row["instance_id"]] = PoolInstance(
                instance_id=row["instance_id"],
                ssh_host=row["ssh_host"],
                ssh_port=row["ssh_port"],
                gpu_name=row["gpu_name"],
                cost_per_hr=row["cost_per_hr"],
                status=row["status"],
                jobs_done=row["jobs_done"],
            )

    @property
    def active_count(self) -> int:
        """Count of non-destroyed instances."""
        return sum(1 for i in self.instances.values() if i.status not in ("destroyed", "failed"))

    @property
    def ready_count(self) -> int:
        return sum(1 for i in self.instances.values() if i.status == "ready")

    def get_ready_instances(self) -> list[PoolInstance]:
        """Get all instances that are ready to accept jobs."""
        return [i for i in self.instances.values() if i.status == "ready"]

    # ── Scale up ─────────────────────────────────────────────────────────

    def scale_up(self, count: int | None = None):
        """Provision instances up to target_size (or explicit count).

        Uses ThreadPoolExecutor to provision in parallel.
        """
        needed = (count or self.target_size) - self.active_count
        if needed <= 0:
            logger.info("Pool already at target size (%d active)", self.active_count)
            return

        logger.info("Scaling up: provisioning %d instances (target=%d)", needed, self.target_size)

        # Find enough offers
        offers = _find_offers(self.gpu_required, self.max_cost_hr, count=needed + 5)
        if not offers:
            raise RuntimeError(
                f"No Vast.ai offers found (gpu={self.gpu_required}, max=${self.max_cost_hr}/hr)"
            )

        # Provision in parallel
        provisioned = []
        with ThreadPoolExecutor(max_workers=min(needed, 10)) as executor:
            futures = {}
            for i in range(needed):
                offer = offers[i % len(offers)]
                fut = executor.submit(_provision_one, offer["id"])
                futures[fut] = offer

            for fut in as_completed(futures):
                offer = futures[fut]
                try:
                    instance_id = fut.result()
                    inst = PoolInstance(
                        instance_id=instance_id,
                        gpu_name=offer.get("gpu_name", "GPU"),
                        cost_per_hr=offer.get("dph_total", 0),
                        status="provisioning",
                    )
                    self.instances[instance_id] = inst
                    _db_register_instance(inst)
                    provisioned.append(instance_id)
                    logger.info(
                        "Provisioned instance %d (%s, $%.3f/hr)",
                        instance_id, inst.gpu_name, inst.cost_per_hr,
                    )
                except Exception as e:
                    logger.error("Failed to provision from offer %s: %s", offer.get("id"), e)

        logger.info(
            "Scale up complete: %d/%d provisioned, %d total active",
            len(provisioned), needed, self.active_count,
        )

    # ── Wait for ready ───────────────────────────────────────────────────

    def wait_for_ready(self, min_ready: int = 1, timeout: int = 600):
        """Block until at least min_ready instances are fully ready.

        Polls all provisioning/setup instances in parallel.
        """
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if self.ready_count >= min_ready:
                logger.info("Pool ready: %d/%d instances", self.ready_count, self.active_count)
                return

            # Check provisioning instances for SSH info
            for inst in list(self.instances.values()):
                if inst.status == "provisioning":
                    try:
                        info = _poll_instance(inst.instance_id)
                        actual = info.get("actual_status") or info.get("status_msg", "")
                        if actual == "running":
                            inst.ssh_host = info.get("ssh_host")
                            inst.ssh_port = info.get("ssh_port", 22)
                            inst.status = "setup"
                            _db_update_status(
                                inst.instance_id, "setup",
                                ssh_host=inst.ssh_host,
                                ssh_port=inst.ssh_port,
                            )
                            logger.info(
                                "Instance %d running, waiting for setup...",
                                inst.instance_id,
                            )
                    except Exception as e:
                        logger.warning("Poll failed for %d: %s", inst.instance_id, e)

                elif inst.status == "setup":
                    if inst.ssh_host and _check_setup_ready(inst.ssh_host, inst.ssh_port):
                        inst.status = "ready"
                        _db_update_status(inst.instance_id, "ready")
                        logger.info("Instance %d is READY", inst.instance_id)

            time.sleep(10)

        raise TimeoutError(
            f"Only {self.ready_count}/{min_ready} instances ready after {timeout}s"
        )

    # ── Scale down ───────────────────────────────────────────────────────

    def scale_down(self, count: int | None = None):
        """Destroy idle instances. If count given, destroy that many. Otherwise destroy surplus."""
        if count is None:
            count = max(0, self.active_count - self.target_size)
        if count <= 0:
            return

        # Prefer destroying instances with most jobs done (they've served their purpose)
        candidates = sorted(
            [i for i in self.instances.values() if i.status in ("ready", "setup")],
            key=lambda i: -i.jobs_done,
        )

        destroyed = 0
        for inst in candidates[:count]:
            _destroy_instance(inst.instance_id)
            inst.status = "destroyed"
            _db_update_status(inst.instance_id, "destroyed")
            destroyed += 1

        logger.info("Scale down: destroyed %d instances, %d remaining", destroyed, self.active_count)

    # ── Auto-scale ───────────────────────────────────────────────────────

    def auto_scale(self, pending_jobs: int, budget_remaining: float):
        """Adjust pool size based on queue depth and budget.

        Rules:
        - target = min(pending_jobs, MAX_POOL, budget_allows)
        - Scale up if pending > 2 × active
        - Scale down if active > pending + 2 (keep a small buffer)
        """
        avg_cost = sum(i.cost_per_hr for i in self.instances.values() if i.status != "destroyed") / max(self.active_count, 1)
        budget_allows = int(budget_remaining / max(avg_cost, 0.10))  # how many instances can we afford for 1 hour

        ideal = min(pending_jobs, self.target_size, budget_allows)
        current = self.active_count

        if pending_jobs > 2 * current and current < ideal:
            self.scale_up(ideal)
        elif current > pending_jobs + 2 and current > ideal:
            self.scale_down(current - ideal)

    # ── Teardown ─────────────────────────────────────────────────────────

    def teardown(self):
        """Destroy ALL instances in the pool."""
        for inst in list(self.instances.values()):
            if inst.status not in ("destroyed", "failed"):
                _destroy_instance(inst.instance_id)
                inst.status = "destroyed"
                _db_update_status(inst.instance_id, "destroyed")
        logger.info("Pool teardown complete — all instances destroyed")

    # ── Info ──────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Pool status summary for dashboard."""
        statuses = {}
        total_cost_hr = 0.0
        total_jobs = 0
        for inst in self.instances.values():
            statuses[inst.status] = statuses.get(inst.status, 0) + 1
            if inst.status not in ("destroyed", "failed"):
                total_cost_hr += inst.cost_per_hr
            total_jobs += inst.jobs_done
        return {
            "active": self.active_count,
            "ready": self.ready_count,
            "target": self.target_size,
            "statuses": statuses,
            "total_cost_hr": round(total_cost_hr, 3),
            "total_jobs_completed": total_jobs,
        }

    def mark_busy(self, instance_id: int):
        """Mark an instance as busy (processing a job)."""
        if instance_id in self.instances:
            self.instances[instance_id].status = "busy"
            _db_update_status(instance_id, "busy")

    def mark_ready(self, instance_id: int):
        """Mark an instance as ready (job complete, available for next)."""
        if instance_id in self.instances:
            self.instances[instance_id].status = "ready"
            self.instances[instance_id].jobs_done += 1
            _db_update_status(instance_id, "ready")
            _db_increment_jobs(instance_id)

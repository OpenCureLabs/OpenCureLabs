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
DEFAULT_IMAGE = os.environ.get("LABCLAW_DOCKER_IMAGE", "ghcr.io/opencurelabs/labclaw-gpu:latest")


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
    provisioned_at: float = 0.0  # time.monotonic() when created


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


def _db_record_instance_spend(instance_id: int):
    """Record spend for a batch-mode instance into vast_spend.

    Calculates cost from vast_pool created_at → NOW() × cost_per_hr.
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO vast_spend (instance_id, skill_name, gpu_name, cost_per_hour, started_at, ended_at, total_cost)
            SELECT instance_id, 'batch_pool', gpu_name, cost_per_hr,
                   created_at, NOW(),
                   ROUND((EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600.0 * cost_per_hr)::numeric, 4)
            FROM vast_pool
            WHERE instance_id = %s AND created_at IS NOT NULL
            ON CONFLICT DO NOTHING
            """,
            (instance_id,),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning("Failed to record spend for instance %d: %s", instance_id, e)
        conn.rollback()
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
    """Search Vast.ai for cheap GPU offers with good reliability."""
    query: dict = {
        "verified": {"eq": True},
        "rentable": {"eq": True},
        "disk_space": {"gte": 20},
        "inet_down": {"gte": 100},
        "dph_total": {"lte": max_cost_hr},
        "reliability2": {"gte": 0.95},
    }
    if gpu_required:
        query["gpu_ram"] = {"gte": 8}
        query["num_gpus"] = {"gte": 1}
        query["cuda_max_good"] = {"gte": 12.0}

    resp = requests.get(
        f"{VAST_API}/bundles/",
        headers=_vast_headers(),
        params={"q": json.dumps(query), "order": "dph_total", "limit": count},
        timeout=30,
    )
    resp.raise_for_status()
    offers = resp.json().get("offers", [])

    # If too few reliable offers, relax to 0.90
    if len(offers) < count:
        query["reliability2"] = {"gte": 0.90}
        resp = requests.get(
            f"{VAST_API}/bundles/",
            headers=_vast_headers(),
            params={"q": json.dumps(query), "order": "dph_total", "limit": count},
            timeout=30,
        )
        resp.raise_for_status()
        offers = resp.json().get("offers", [])
        if offers:
            logger.info("Relaxed reliability to 0.90 — found %d offers", len(offers))

    return offers


def _provision_one(offer_id: int, image: str = "pytorch/pytorch:latest", onstart: str | None = None) -> int:
    """Provision a single Vast.ai instance. Returns instance_id."""
    if onstart is None:
        from agentiq_labclaw.compute import build_onstart_script, resolve_wheel_url
        onstart = build_onstart_script(resolve_wheel_url())

    payload = {
        "client_id": "opencurelabs",
        "image": image,
        "disk": 20,
        "onstart": onstart,
    }

    # Add Docker registry credentials for private images (ghcr.io)
    image_login = os.environ.get("LABCLAW_IMAGE_LOGIN")
    if image_login and ":" in image_login:
        user, token = image_login.split(":", 1)
        payload["image_login"] = f"-u {user} -p {token} ghcr.io"

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

    # Attach SSH key so we can connect later
    from agentiq_labclaw.compute import attach_ssh_key
    attach_ssh_key(instance_id)

    return instance_id


def _poll_instance(instance_id: int) -> dict:
    """Get current instance info from Vast.ai API."""
    resp = requests.get(
        f"{VAST_API}/instances/{instance_id}/",
        headers=_vast_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    # Vast.ai wraps single-instance response as {"instances": {<fields>}}
    return data.get("instances", data)


def _destroy_instance(instance_id: int, retries: int = 3) -> bool:
    """Terminate and delete a Vast.ai instance. Returns True on success."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.delete(
                f"{VAST_API}/instances/{instance_id}/",
                headers=_vast_headers(),
                timeout=30,
            )
            resp.raise_for_status()
            logger.info("Destroyed instance %d", instance_id)
            return True
        except requests.RequestException as e:
            logger.error("Failed to destroy instance %d (attempt %d/%d): %s", instance_id, attempt, retries, e)
            if attempt < retries:
                time.sleep(2 * attempt)
    return False


def _check_setup_ready(ssh_host: str, ssh_port: int) -> bool:
    """Check if the onstart script has finished (marker file exists)."""
    ssh_base = [
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5",
        "-i", SSH_KEY_PATH,
        "-p", str(ssh_port),
        f"root@{ssh_host}",
    ]
    try:
        result = subprocess.run(
            [*ssh_base, "test -f /tmp/labclaw_ready && echo READY || echo WAIT"],
            capture_output=True, text=True, timeout=10,
        )
        if "READY" in result.stdout:
            return True
        if result.returncode != 0:
            logger.debug("SSH check for %s:%d failed: %s", ssh_host, ssh_port, result.stderr.strip())
        return False
    except Exception as e:
        logger.debug("SSH check for %s:%d exception: %s", ssh_host, ssh_port, e)
        return False


def _check_ssh_alive(ssh_host: str, ssh_port: int, retries: int = 3, retry_delay: float = 5.0) -> bool:
    """SSH connectivity check — returns True if instance responds.

    Retries up to `retries` times with `retry_delay` seconds between attempts.
    Vast.ai instances can have momentary SSH hiccups after heavy GPU work
    (cooling, SSH daemon restart, transient network blip), so a single failure
    is not sufficient evidence that an instance is dead.
    """
    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(
                [
                    "ssh", "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=8",
                    "-o", "BatchMode=yes",
                    "-i", SSH_KEY_PATH,
                    "-p", str(ssh_port),
                    f"root@{ssh_host}",
                    "echo alive",
                ],
                capture_output=True, text=True, timeout=15,
            )
            if "alive" in result.stdout:
                return True
        except Exception:
            pass
        if attempt < retries:
            logger.debug(
                "SSH check attempt %d/%d failed for %s — retrying in %.0fs",
                attempt, retries, ssh_host, retry_delay,
            )
            time.sleep(retry_delay)
    return False


# ── Pool Manager ─────────────────────────────────────────────────────────────

class PoolManager:
    """Manages a fleet of Vast.ai GPU instances for batch compute."""

    def __init__(
        self,
        target_size: int = 10,
        gpu_required: bool = True,
        max_cost_hr: float = 0.50,
        image: str | None = None,
    ):
        self.target_size = target_size
        self.gpu_required = gpu_required
        self.max_cost_hr = max_cost_hr
        self.image = image or DEFAULT_IMAGE
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

        # Sync DB state against Vast.ai API — prune instances that were
        # destroyed externally (e.g. via 'vastai destroy' or dashboard)
        self._sync_with_api()

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

    def _sync_with_api(self):
        """Validate DB pool against Vast.ai API, prune ghost instances."""
        if not self.instances:
            return
        pruned = 0
        for inst in list(self.instances.values()):
            if inst.status in ("destroyed", "failed"):
                continue
            try:
                info = _poll_instance(inst.instance_id)
                if info is None:
                    inst.status = "destroyed"
                    _db_update_status(inst.instance_id, "destroyed")
                    pruned += 1
                    continue
                api_status = info.get("actual_status", "")
                if api_status in ("", "exited", "offline"):
                    inst.status = "destroyed"
                    _db_update_status(inst.instance_id, "destroyed")
                    pruned += 1
            except requests.RequestException:
                # Instance not found on API — mark destroyed
                inst.status = "destroyed"
                _db_update_status(inst.instance_id, "destroyed")
                pruned += 1
        if pruned:
            logger.info("Sync: pruned %d stale instances from pool (actually destroyed on Vast.ai)", pruned)

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

        # Resolve wheel URL once for all instances (avoids N API calls)
        from agentiq_labclaw.compute import build_onstart_script, resolve_wheel_url
        wheel_url = resolve_wheel_url()
        onstart = build_onstart_script(wheel_url)
        if wheel_url:
            logger.info("Using pre-built wheel: %s", wheel_url)
        else:
            logger.warning("No wheel found — falling back to full repo clone")

        # Provision in parallel
        provisioned = []
        with ThreadPoolExecutor(max_workers=min(needed, 10)) as executor:
            futures = {}
            for i in range(needed):
                offer = offers[i % len(offers)]
                fut = executor.submit(_provision_one, offer["id"], image=self.image, onstart=onstart)
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
                        provisioned_at=time.monotonic(),
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

    def wait_for_ready(self, min_ready: int = 1, timeout: int = 600, progress_fn=None):
        """Block until at least min_ready instances are fully ready.

        Polls all provisioning/setup instances in parallel.
        progress_fn: optional callable(msg, *args) for extra output (e.g. batch _log)
        """
        deadline = time.monotonic() + timeout
        last_progress = time.monotonic()

        while time.monotonic() < deadline:
            if self.ready_count >= min_ready:
                msg = "Pool ready: %d/%d instances"
                logger.info(msg, self.ready_count, self.active_count)
                if progress_fn:
                    progress_fn(msg, self.ready_count, self.active_count)
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
                            msg = "Instance %d (%s) booted — running onstart/pip install..."
                            logger.info(msg, inst.instance_id, inst.gpu_name)
                            if progress_fn:
                                progress_fn(msg, inst.instance_id, inst.gpu_name)
                    except Exception as e:
                        logger.warning("Poll failed for %d: %s", inst.instance_id, e)

                elif inst.status == "setup":
                    if inst.ssh_host and _check_setup_ready(inst.ssh_host, inst.ssh_port):
                        inst.status = "ready"
                        _db_update_status(inst.instance_id, "ready")
                        msg = "Instance %d (%s) READY  [%d/%d ready]"
                        logger.info(msg, inst.instance_id, inst.gpu_name,
                                    self.ready_count, self.active_count)
                        if progress_fn:
                            progress_fn(msg, inst.instance_id, inst.gpu_name,
                                        self.ready_count, self.active_count)

            # Print a progress summary every 30s so the screen isn't silent
            now = time.monotonic()
            if now - last_progress >= 30:
                provisioning = sum(1 for i in self.instances.values() if i.status == "provisioning")
                setup = sum(1 for i in self.instances.values() if i.status == "setup")
                ready = self.ready_count
                elapsed = int(now - (deadline - timeout))
                remaining = int(deadline - now)
                msg = "Waiting... %ds elapsed | provisioning:%d  installing:%d  ready:%d/%d | %ds left"
                args = (elapsed, provisioning, setup, ready, self.active_count, remaining)
                logger.info(msg, *args)
                if progress_fn:
                    progress_fn(msg, *args)
                last_progress = now

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

        # Prefer destroying instances with FEWEST jobs done (preserve productive workers)
        candidates = sorted(
            [i for i in self.instances.values() if i.status in ("ready", "setup")],
            key=lambda i: i.jobs_done,
        )

        destroyed = 0
        for inst in candidates[:count]:
            if _destroy_instance(inst.instance_id):
                inst.status = "destroyed"
                _db_update_status(inst.instance_id, "destroyed")
                destroyed += 1
            else:
                logger.error("Scale down: could not destroy instance %d — leaving in pool", inst.instance_id)

        logger.info("Scale down: destroyed %d instances, %d remaining", destroyed, self.active_count)

    # ── Auto-scale ───────────────────────────────────────────────────────

    def auto_scale(self, pending_jobs: int, budget_remaining: float):
        """Adjust pool size based on queue depth and budget.

        Rules:
        - Scale up if pending > 2 × active and budget allows
        - Never scale down below target_size (pool is meant to persist,
          especially in continuous mode where a new batch is imminent)
        - Only scale down if over budget
        """
        active_instances = [i for i in self.instances.values() if i.status != "destroyed"]
        avg_cost = sum(i.cost_per_hr for i in active_instances) / max(self.active_count, 1)
        budget_allows = int(budget_remaining / max(avg_cost, 0.10))  # how many instances can we afford for 1 hour

        current = self.active_count

        # Scale up if lots of pending work and budget permits
        ideal_up = min(pending_jobs, self.target_size, budget_allows)
        if pending_jobs > 2 * current and current < ideal_up:
            self.scale_up(ideal_up)

        # Only scale down if we exceed target AND budget is nearly gone
        if current > self.target_size and current > budget_allows:
            self.scale_down(current - self.target_size)

    # ── Health check & self-heal ─────────────────────────────────────────

    def poll_readiness(self):
        """Single non-blocking pass: transition provisioning→setup→ready.

        Call this periodically (e.g. in _monitor_loop) so new instances
        become available without waiting for the next cycle.

        Returns number of instances that became ready this pass.
        """
        became_ready = 0
        for inst in list(self.instances.values()):
            if inst.status == "provisioning":
                try:
                    info = _poll_instance(inst.instance_id)
                    if info is None:
                        continue
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
                            "Instance %d (%s) booted → setup",
                            inst.instance_id, inst.gpu_name,
                        )
                except Exception as e:
                    logger.warning("Poll failed for %d: %s", inst.instance_id, e)

            if inst.status == "setup" and inst.ssh_host:
                if _check_setup_ready(inst.ssh_host, inst.ssh_port):
                    inst.status = "ready"
                    _db_update_status(inst.instance_id, "ready")
                    became_ready += 1
                    logger.info(
                        "Instance %d (%s) READY  [%d/%d]",
                        inst.instance_id, inst.gpu_name,
                        self.ready_count, self.active_count,
                    )
        return became_ready

    def health_check(self, progress_fn=None) -> int:
        """Check all active instances via SSH, replace dead ones.

        Returns number of instances replaced.
        """
        # First, try to advance any provisioning instances
        self.poll_readiness()

        dead = []
        for inst in list(self.instances.values()):
            if inst.status in ("destroyed", "failed"):
                continue
            # SSH check with built-in retries (3 attempts, 5s gap each).
            # Only flag as dead if all retries fail — avoids killing instances
            # that have a momentary SSH hiccup after GPU-intensive work.
            if inst.ssh_host and inst.status in ("ready", "busy", "setup"):
                alive = _check_ssh_alive(inst.ssh_host, inst.ssh_port)
                if not alive:
                    dead.append(inst)
            elif inst.status == "provisioning":
                # Only kill provisioning instances stuck for >8 minutes
                age_min = (time.monotonic() - inst.provisioned_at) / 60 if inst.provisioned_at else 999
                if age_min < 8:
                    continue  # give it time to boot
                try:
                    info = _poll_instance(inst.instance_id)
                    api_status = info.get("actual_status", "") if info else ""
                    if api_status in ("", "exited", "offline", "created", "loading"):
                        dead.append(inst)
                        logger.info("Instance %d stuck in '%s' for %.1f min", inst.instance_id, api_status, age_min)
                except Exception:
                    dead.append(inst)

        if not dead:
            return 0

        msg = "Health check: %d dead instances detected — replacing"
        logger.warning(msg, len(dead))
        if progress_fn:
            progress_fn(msg, len(dead))

        for inst in dead:
            _db_record_instance_spend(inst.instance_id)
            if _destroy_instance(inst.instance_id):
                inst.status = "destroyed"
                _db_update_status(inst.instance_id, "destroyed")
                msg = "Removed dead instance %d (%s)"
                logger.info(msg, inst.instance_id, inst.gpu_name)
                if progress_fn:
                    progress_fn(msg, inst.instance_id, inst.gpu_name)
            else:
                msg = "WARN: could not destroy instance %d (%s) — will retry next health check"
                logger.error(msg, inst.instance_id, inst.gpu_name)
                if progress_fn:
                    progress_fn(msg, inst.instance_id, inst.gpu_name)

        # Scale back up to target
        if self.active_count < self.target_size:
            try:
                self.scale_up()
                self.wait_for_ready(min_ready=1, timeout=600, progress_fn=progress_fn)
            except (RuntimeError, TimeoutError) as e:
                msg = "Self-heal scale_up failed: %s"
                logger.warning(msg, e)
                if progress_fn:
                    progress_fn(msg, e)

        return len(dead)

    # ── Teardown ─────────────────────────────────────────────────────────

    def teardown(self):
        """Destroy ALL instances in the pool and record spend.

        Only marks instances as 'destroyed' in DB after confirming the
        Vast.ai API DELETE succeeded.  Runs a verification pass at the
        end to catch any that slipped through.
        """
        orphans = []
        for inst in list(self.instances.values()):
            if inst.status not in ("destroyed", "failed"):
                _db_record_instance_spend(inst.instance_id)
                if _destroy_instance(inst.instance_id):
                    inst.status = "destroyed"
                    _db_update_status(inst.instance_id, "destroyed")
                else:
                    orphans.append(inst)
                    logger.error("Teardown: instance %d destroy FAILED — will verify", inst.instance_id)

        # Verification pass — confirm nothing is still running on Vast.ai
        if orphans:
            logger.warning("Teardown: %d orphan(s) detected, running verification pass...", len(orphans))
            time.sleep(3)
            for inst in orphans:
                if _destroy_instance(inst.instance_id):
                    inst.status = "destroyed"
                    _db_update_status(inst.instance_id, "destroyed")
                    logger.info("Teardown: orphan %d destroyed on retry", inst.instance_id)
                else:
                    logger.critical(
                        "TEARDOWN FAILED: instance %d may still be running on Vast.ai! "
                        "Manual cleanup required: vastai destroy instance %d",
                        inst.instance_id, inst.instance_id,
                    )

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

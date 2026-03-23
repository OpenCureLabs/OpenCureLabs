"""Vast.ai GPU dispatch — provisions instances, runs jobs, streams results back."""

import json
import logging
import os
import subprocess
import time

import requests

logger = logging.getLogger("labclaw.compute.vast_dispatcher")

VAST_API = "https://console.vast.ai/api/v0"


# ── Budget tracking ──────────────────────────────────────────────────────────

def _get_db_connection():
    """Get a PostgreSQL connection for spend tracking."""
    try:
        import psycopg2
        db_url = os.environ.get("POSTGRES_URL", "dbname=opencurelabs port=5433")
        return psycopg2.connect(db_url)
    except Exception:
        return None


def _ensure_spend_table(conn):
    """Create vast_spend table if it doesn't exist."""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vast_spend (
                id SERIAL PRIMARY KEY,
                instance_id INTEGER,
                skill_name TEXT,
                gpu_name TEXT,
                cost_per_hour REAL,
                started_at TIMESTAMP DEFAULT NOW(),
                ended_at TIMESTAMP,
                total_cost REAL DEFAULT 0
            )
        """)
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning("Could not create vast_spend table: %s", e)


def _record_spend_start(skill_name, instance_id, gpu_name, cost_per_hour):
    """Record the start of a Vast.ai job."""
    conn = _get_db_connection()
    if not conn:
        return None
    try:
        _ensure_spend_table(conn)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO vast_spend (instance_id, skill_name, gpu_name, cost_per_hour) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (instance_id, skill_name, gpu_name, cost_per_hour),
        )
        spend_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return spend_id
    except Exception as e:
        logger.warning("Could not record spend start: %s", e)
        conn.close()
        return None


def _record_spend_end(spend_id, total_cost):
    """Record the end of a Vast.ai job with total cost."""
    if spend_id is None:
        return
    conn = _get_db_connection()
    if not conn:
        return
    try:
        _ensure_spend_table(conn)
        cur = conn.cursor()
        cur.execute(
            "UPDATE vast_spend SET ended_at = NOW(), total_cost = %s WHERE id = %s",
            (total_cost, spend_id),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("Could not record spend end: %s", e)
        conn.close()


def get_total_spend():
    """Get total Vast.ai spend recorded in the database."""
    conn = _get_db_connection()
    if not conn:
        return 0.0
    try:
        _ensure_spend_table(conn)
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(total_cost), 0) FROM vast_spend")
        total = float(cur.fetchone()[0])
        cur.close()
        conn.close()
        return total
    except Exception:
        conn.close()
        return 0.0


def get_account_balance():
    """Query real-time account credit from the Vast.ai API."""
    api_key = os.environ.get("VAST_AI_KEY", "")
    if not api_key:
        return 0.0
    try:
        resp = requests.get(
            f"{VAST_API}/users/current/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json().get("credit", 0))
    except Exception as e:
        logger.warning("Could not fetch Vast.ai account balance: %s", e)
        return 0.0


def check_budget(estimated_cost_hr=1.0):
    """Check if we're within budget. Returns (ok, remaining, budget)."""
    env_budget = float(os.environ.get("VAST_AI_BUDGET", "0"))

    # Use API balance as default; VAST_AI_BUDGET acts as optional cap
    api_balance = get_account_balance()
    if env_budget > 0 and api_balance > 0:
        budget = min(env_budget, api_balance)
    elif env_budget > 0:
        budget = env_budget
    elif api_balance > 0:
        budget = api_balance
    else:
        logger.warning("No Vast.ai budget or account balance available!")
        return True, float("inf"), 0

    spent = get_total_spend()
    remaining = budget - spent
    if remaining <= 0:
        logger.error("Vast.ai budget exhausted! Spent: $%.2f / $%.2f", spent, budget)
        return False, 0, budget
    if remaining < estimated_cost_hr:
        logger.warning(
            "Vast.ai budget low: $%.2f remaining (need ~$%.2f/hr). Proceeding cautiously.",
            remaining, estimated_cost_hr,
        )
    return True, remaining, budget


def _find_reusable_instance(api_key: str):
    """Check for an existing running Vast.ai instance we can reuse.

    Returns (instance_id, ssh_host, ssh_port, gpu_name, cost_hr) or None.
    Looks for instances tagged with client_id 'opencurelabs' that are
    already running, so parallel genesis tasks can share a single GPU
    instead of each trying to provision its own.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(f"{VAST_API}/instances/", headers=headers, timeout=30)
        resp.raise_for_status()
        instances = resp.json().get("instances", [])
        if not instances and isinstance(resp.json(), list):
            instances = resp.json()
    except Exception as e:
        logger.debug("Could not list Vast.ai instances: %s", e)
        return None

    for inst in instances:
        status = inst.get("actual_status") or ""
        client = inst.get("label") or inst.get("client_id") or ""
        if status == "running" and "opencurelabs" in client.lower():
            ssh_host = inst.get("ssh_host")
            ssh_port = inst.get("ssh_port", 22)
            if ssh_host:
                gpu_name = inst.get("gpu_name", "GPU")
                cost_hr = inst.get("dph_total", 0)
                iid = inst.get("id")
                logger.info(
                    "Found reusable Vast.ai instance %d (%s) at %s:%d",
                    iid, gpu_name, ssh_host, ssh_port,
                )
                return iid, ssh_host, ssh_port, gpu_name, cost_hr
    return None


# ── Pool-aware instance management ──────────────────────────────────────────

def _claim_pool_instance():
    """Atomically claim a 'ready' instance from vast_pool for exclusive use.

    Returns (instance_id, ssh_host, ssh_port, gpu_name, cost_per_hr) or None.
    Uses SELECT FOR UPDATE SKIP LOCKED so parallel tasks each claim a different
    instance without races.
    """
    conn = _get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE vast_pool
            SET status = 'busy'
            WHERE id = (
                SELECT id FROM vast_pool
                WHERE status = 'ready'
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING instance_id, ssh_host, ssh_port, gpu_name, cost_per_hr
        """)
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return row  # (instance_id, ssh_host, ssh_port, gpu_name, cost_per_hr) or None
    except Exception as e:
        logger.debug("Could not claim pool instance: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        return None


def _register_pool_instance(
    instance_id: int, ssh_host: str, ssh_port: int, gpu_name: str, cost_per_hr: float,
):
    """Register a newly provisioned instance in vast_pool with status 'busy'."""
    conn = _get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO vast_pool
                (instance_id, ssh_host, ssh_port, gpu_name, cost_per_hr, status, ready_at)
            VALUES (%s, %s, %s, %s, %s, 'busy', NOW())
            ON CONFLICT (instance_id) DO UPDATE
                SET status = 'busy',
                    ssh_host = EXCLUDED.ssh_host,
                    ssh_port = EXCLUDED.ssh_port
            """,
            (instance_id, ssh_host, ssh_port, gpu_name, cost_per_hr),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.debug("Could not register pool instance: %s", e)
        try:
            conn.close()
        except Exception:
            pass


def _release_pool_instance(instance_id: int, destroy: bool = False):
    """Mark a pool instance ready (or destroyed) after a job completes."""
    conn = _get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        if destroy:
            cur.execute(
                "UPDATE vast_pool SET status = 'destroyed', destroyed_at = NOW()"
                " WHERE instance_id = %s",
                (instance_id,),
            )
        else:
            cur.execute(
                "UPDATE vast_pool"
                " SET status = 'ready', jobs_done = COALESCE(jobs_done, 0) + 1"
                " WHERE instance_id = %s AND status = 'busy'",
                (instance_id,),
            )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.debug("Could not release pool instance: %s", e)
        try:
            conn.close()
        except Exception:
            pass


def teardown_all_instances():
    """Destroy all active Vast.ai pool instances at the end of a run.

    Called by the coordinator when a Genesis run ends (budget exhausted or stopped).
    Safe to call multiple times — already-destroyed instances are skipped.
    """
    vast_key = os.environ.get("VAST_AI_KEY")
    if not vast_key:
        return
    conn = _get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT instance_id FROM vast_pool WHERE status IN ('ready', 'busy', 'provisioning')"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("Could not query pool for teardown: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        return

    if not rows:
        logger.info("Teardown: no active pool instances to destroy")
        return

    logger.info("Teardown: destroying %d pool instance(s)", len(rows))
    for (instance_id,) in rows:
        try:
            VastInstance(vast_key, instance_id).destroy()
            _release_pool_instance(instance_id, destroy=True)
            logger.info("Teardown: destroyed instance %d", instance_id)
        except Exception as e:
            logger.warning("Teardown: failed to destroy instance %d: %s", instance_id, e)


class VastInstance:
    """Manages a single Vast.ai GPU instance lifecycle."""

    def __init__(self, api_key: str, instance_id: int):
        self.api_key = api_key
        self.instance_id = instance_id
        self._headers = {"Authorization": f"Bearer {api_key}"}

    @property
    def info(self) -> dict:
        resp = requests.get(
            f"{VAST_API}/instances/{self.instance_id}/",
            headers=self._headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def wait_until_ready(self, timeout: int = 900, poll_interval: int = 10) -> dict:
        """Poll until instance is running. Returns instance info.

        RTX 5090 instances can take 8-15 minutes to pull the Docker image and
        complete the onstart script. Default raised from 300s to 900s (15 min).
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            info = self.info
            status = info.get("actual_status") or info.get("status_msg", "")
            if status == "running":
                return info
            logger.info("Instance %d status: %s — waiting...", self.instance_id, status)
            time.sleep(poll_interval)
        raise TimeoutError(f"Instance {self.instance_id} did not start within {timeout}s")

    def destroy(self):
        """Terminate and delete the instance."""
        for attempt in range(1, 4):
            try:
                resp = requests.delete(
                    f"{VAST_API}/instances/{self.instance_id}/",
                    headers=self._headers,
                    timeout=30,
                )
                resp.raise_for_status()
                logger.info("Destroyed Vast.ai instance %d", self.instance_id)
                return
            except requests.RequestException as e:
                logger.error("Failed to destroy instance %d (attempt %d/3): %s", self.instance_id, attempt, e)
                if attempt < 3:
                    time.sleep(2 * attempt)
        logger.critical(
            "DESTROY FAILED: instance %d may still be running on Vast.ai! "
            "Manual cleanup: vastai destroy instance %d",
            self.instance_id, self.instance_id,
        )


def _find_cheapest_offer(api_key: str, gpu_required: bool) -> dict:
    """Search Vast.ai offers for the cheapest suitable GPU instance."""
    headers = {"Authorization": f"Bearer {api_key}"}

    query = {
        "verified": {"eq": True},
        "rentable": {"eq": True},
        "disk_space": {"gte": 20},
        "inet_down": {"gte": 100},
    }
    if gpu_required:
        query["gpu_ram"] = {"gte": 8}
        query["num_gpus"] = {"gte": 1}

    resp = requests.get(
        f"{VAST_API}/bundles/",
        headers=headers,
        params={"q": json.dumps(query), "order": "dph_total", "limit": 5},
        timeout=30,
    )
    resp.raise_for_status()
    offers = resp.json().get("offers", [])
    if not offers:
        raise RuntimeError("No suitable Vast.ai instances available")
    return offers[0]


def _create_instance(api_key: str, offer_id: int, image: str = "pytorch/pytorch:latest") -> int:
    """Create a Vast.ai instance from an offer. Returns instance ID."""
    headers = {"Authorization": f"Bearer {api_key}"}

    # Resolve wheel URL once and build onstart script
    from agentiq_labclaw.compute import build_onstart_script, resolve_wheel_url
    onstart_script = build_onstart_script(resolve_wheel_url())

    payload = {
        "client_id": "opencurelabs",
        "image": image,
        "disk": 20,
        "onstart": onstart_script,
    }

    resp = requests.put(
        f"{VAST_API}/asks/{offer_id}/",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    instance_id = data.get("new_contract")
    if not instance_id:
        raise RuntimeError(f"Failed to create instance: {data}")
    logger.info("Created Vast.ai instance %d from offer %d", instance_id, offer_id)

    # Attach SSH key so we can connect later
    from agentiq_labclaw.compute import attach_ssh_key
    attach_ssh_key(instance_id)

    return instance_id


def _wait_for_setup(ssh_host: str, ssh_port: int, timeout: int = 180):
    """Wait for the onstart script to finish installing agentiq_labclaw."""
    ssh_key = os.path.expanduser("~/.ssh/xpclabs")
    ssh_opts = [
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-i", ssh_key,
        "-p", str(ssh_port),
        f"root@{ssh_host}",
    ]

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [*ssh_opts, "test -f /tmp/labclaw_ready && echo READY || echo WAIT"],
                capture_output=True, text=True, timeout=15,
            )
            if "READY" in result.stdout:
                logger.info("Vast.ai instance setup complete")
                return True
        except (subprocess.TimeoutExpired, Exception):
            pass
        logger.info("Waiting for instance setup to complete...")
        time.sleep(15)

    raise TimeoutError(f"Instance setup did not complete within {timeout}s")


def _run_remote(skill_name, input_data, ssh_host, ssh_port, output_schema):
    """Execute a skill remotely on a Vast.ai instance via SSH."""
    input_json = json.dumps(input_data.model_dump(), default=str)
    ssh_key = os.path.expanduser("~/.ssh/xpclabs")

    remote_script = (
        "import json, sys; "
        "from agentiq_labclaw.base import get_skill; "
        f"Skill = get_skill('{skill_name}'); "
        "s = Skill(); "
        "inp = Skill.input_schema.model_validate(json.loads(sys.stdin.read())); "
        "result = s.run(inp); "
        "print(json.dumps(result.model_dump(), default=str))"
    )

    result = subprocess.run(
        [
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            "-i", ssh_key,
            "-p", str(ssh_port),
            f"root@{ssh_host}",
            f'python3 -c "{remote_script}"',
        ],
        input=input_json,
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        logger.error("Vast.ai remote stderr: %s", result.stderr[:500])
        raise RuntimeError(f"Remote execution failed: {result.stderr[:300]}")

    output_data = json.loads(result.stdout.strip())
    return output_schema.model_validate(output_data)


def dispatch(skill, input_data):
    """
    Dispatch a skill execution to Vast.ai for heavy compute.

    Instance lifecycle (continuous/Genesis mode):
    1. Check budget
    2. Claim an existing 'ready' instance from the pool (atomic DB claim)
    3. If no pool instance: find cheapest offer, provision a new instance
    4. Wait for it to be ready + onstart to complete
    5. Serialize input, SSH-execute the skill remotely
    6. On success: mark instance 'ready' in pool — keeps it alive for next batch
    7. On failure: destroy the instance and mark it 'destroyed'

    Instances persist between batches in continuous mode and are only destroyed
    when teardown_all_instances() is called at run end.
    """
    vast_key = os.environ.get("VAST_AI_KEY")
    if not vast_key:
        raise RuntimeError("VAST_AI_KEY not set — cannot dispatch to Vast.ai")

    # Budget check
    ok, remaining, budget = check_budget()
    if not ok:
        raise RuntimeError(
            f"Vast.ai budget exhausted (${budget:.2f}). "
            "Set VAST_AI_BUDGET higher or switch to local compute."
        )
    if budget > 0:
        logger.info("Vast.ai budget: $%.2f remaining of $%.2f", remaining, budget)

    logger.info("Dispatching %s to Vast.ai (GPU required: %s)", skill.name, skill.gpu_required)

    # ── Claim an existing ready instance from the persistent pool ──
    claimed = _claim_pool_instance()
    if claimed:
        inst_id, ssh_host, ssh_port, gpu_name, cost_hr = claimed
        logger.info(
            "[%s] Claimed pool instance %d (%s) at %s:%d",
            skill.name, inst_id, gpu_name, ssh_host, ssh_port,
        )
        spend_id = _record_spend_start(skill.name, inst_id, gpu_name, cost_hr)
        job_start = time.monotonic()
        try:
            result = _run_remote(skill.name, input_data, ssh_host, ssh_port, skill.output_schema)
            logger.info(
                "Vast.ai dispatch succeeded for %s (pool instance %d)", skill.name, inst_id,
            )
            _release_pool_instance(inst_id)  # return to pool for next task
            return result
        except Exception:
            # Instance may be broken — destroy it and evict from pool
            try:
                VastInstance(vast_key, inst_id).destroy()
            except Exception as destroy_err:
                logger.warning("Could not destroy failed pool instance %d: %s", inst_id, destroy_err)
            _release_pool_instance(inst_id, destroy=True)
            raise
        finally:
            elapsed_hrs = (time.monotonic() - job_start) / 3600
            total_cost = round(elapsed_hrs * cost_hr, 4)
            _record_spend_end(spend_id, total_cost)
            logger.info(
                "Vast.ai job complete (pool): %s, %.1f min, $%.4f",
                skill.name, elapsed_hrs * 60, total_cost,
            )

    # ── No pool instance available — provision a new one ──
    # 1. Find offer
    offer = _find_cheapest_offer(vast_key, skill.gpu_required)
    offer_id = offer["id"]
    cost_hr = offer.get("dph_total", 0)
    gpu_name = offer.get("gpu_name", "CPU")
    logger.info("Selected offer %d: %s GPU, $%.3f/hr", offer_id, gpu_name, cost_hr)

    # 2. Provision
    instance_id = _create_instance(vast_key, offer_id)
    instance = VastInstance(vast_key, instance_id)
    job_start = time.monotonic()

    # Record spend start
    spend_id = _record_spend_start(skill.name, instance_id, gpu_name, cost_hr)

    try:
        # 3. Wait for instance to be running (up to 15 min for RTX 5090 cold start)
        info = instance.wait_until_ready(timeout=900)
        ssh_host = info.get("ssh_host")
        ssh_port = info.get("ssh_port", 22)

        if not ssh_host:
            raise RuntimeError("Instance started but no SSH host available")

        # 4. Wait for onstart (pip install from GitHub) to finish
        _wait_for_setup(ssh_host, ssh_port)

        # 5. Register in pool as 'busy' (we're running on it)
        _register_pool_instance(instance_id, ssh_host, ssh_port, gpu_name, cost_hr)

        # 6. Run remotely
        result = _run_remote(skill.name, input_data, ssh_host, ssh_port, skill.output_schema)
        logger.info("Vast.ai dispatch succeeded for %s (new instance %d)", skill.name, instance_id)

        # 7. Keep alive — return to pool for the next batch
        _release_pool_instance(instance_id)
        logger.info("Instance %d returned to pool (ready for next task)", instance_id)
        return result

    except Exception:
        # Destroy on failure — don't leave broken instances in the pool
        try:
            instance.destroy()
        except Exception as destroy_err:
            logger.warning("Could not destroy failed instance %d: %s", instance_id, destroy_err)
        _release_pool_instance(instance_id, destroy=True)
        raise
    finally:
        elapsed_hrs = (time.monotonic() - job_start) / 3600
        total_cost = round(elapsed_hrs * cost_hr, 4)
        _record_spend_end(spend_id, total_cost)
        logger.info(
            "Vast.ai job complete: %s, %.1f min, $%.4f",
            skill.name, elapsed_hrs * 60, total_cost,
        )

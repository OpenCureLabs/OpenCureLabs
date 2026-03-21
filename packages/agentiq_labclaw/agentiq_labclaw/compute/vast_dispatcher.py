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


def check_budget(estimated_cost_hr=1.0):
    """Check if we're within budget. Returns (ok, remaining, budget)."""
    budget = float(os.environ.get("VAST_AI_BUDGET", "0"))
    if budget <= 0:
        # No budget set — unlimited (but warn)
        logger.warning("VAST_AI_BUDGET not set — no spending limit!")
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

    def wait_until_ready(self, timeout: int = 300, poll_interval: int = 10) -> dict:
        """Poll until instance is running. Returns instance info."""
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
        try:
            requests.delete(
                f"{VAST_API}/instances/{self.instance_id}/",
                headers=self._headers,
                timeout=30,
            )
            logger.info("Destroyed Vast.ai instance %d", self.instance_id)
        except requests.RequestException as e:
            logger.error("Failed to destroy instance %d: %s", self.instance_id, e)


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
    payload = {
        "client_id": "opencurelabs",
        "image": image,
        "disk": 20,
        "onstart": "pip install agentiq-labclaw",
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
    return instance_id


def dispatch(skill, input_data):
    """
    Dispatch a skill execution to Vast.ai for heavy compute.

    1. Check budget
    2. Find cheapest suitable GPU instance
    3. Provision the instance
    4. Wait for it to be ready
    5. Serialize input, SSH-execute the skill remotely
    6. Retrieve results
    7. Terminate the instance and record spend
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
        # 3. Wait for ready
        info = instance.wait_until_ready(timeout=300)
        ssh_host = info.get("ssh_host")
        ssh_port = info.get("ssh_port", 22)

        if not ssh_host:
            raise RuntimeError("Instance started but no SSH host available")

        # 4. Serialize input and run remotely
        input_json = json.dumps(input_data.model_dump(), default=str)

        remote_cmd = (
            f"python3 -c \""
            f"import json; "
            f"from agentiq_labclaw.base import get_skill; "
            f"Skill = get_skill('{skill.name}'); "
            f"s = Skill(); "
            f"inp = Skill.input_schema.model_validate(json.loads('{input_json}')); "
            f"result = s.run(inp); "
            f"print(json.dumps(result.model_dump(), default=str))"
            f"\""
        )

        result = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-p", str(ssh_port),
                f"root@{ssh_host}",
                remote_cmd,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Remote execution failed: {result.stderr}")

        # 5. Parse results
        output_data = json.loads(result.stdout.strip())
        return skill.output_schema.model_validate(output_data)

    finally:
        # 6. Always clean up and record spend
        instance.destroy()
        elapsed_hrs = (time.monotonic() - job_start) / 3600
        total_cost = round(elapsed_hrs * cost_hr, 4)
        _record_spend_end(spend_id, total_cost)
        logger.info(
            "Vast.ai job complete: %s, %.1f min, $%.4f",
            skill.name, elapsed_hrs * 60, total_cost,
        )

"""Vast.ai GPU dispatch — provisions instances, runs jobs, streams results back."""

import json
import logging
import os
import subprocess
import time

import requests

logger = logging.getLogger("labclaw.compute.vast_dispatcher")

VAST_API = "https://console.vast.ai/api/v0"


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

    1. Find cheapest suitable GPU instance
    2. Provision the instance
    3. Wait for it to be ready
    4. Serialize input, SSH-execute the skill remotely
    5. Retrieve results
    6. Terminate the instance
    """
    vast_key = os.environ.get("VAST_AI_KEY")
    if not vast_key:
        raise RuntimeError("VAST_AI_KEY not set — cannot dispatch to Vast.ai")

    logger.info("Dispatching %s to Vast.ai (GPU required: %s)", skill.name, skill.gpu_required)

    # 1. Find offer
    offer = _find_cheapest_offer(vast_key, skill.gpu_required)
    offer_id = offer["id"]
    logger.info(
        "Selected offer %d: %s GPU, $%.3f/hr",
        offer_id,
        offer.get("gpu_name", "CPU"),
        offer.get("dph_total", 0),
    )

    # 2. Provision
    instance_id = _create_instance(vast_key, offer_id)
    instance = VastInstance(vast_key, instance_id)

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
        # 6. Always clean up
        instance.destroy()

"""
Worker — manages one Vast.ai instance's job loop.

Each worker is a thread that:
  1. Claims a job from the batch queue (atomic, lock-free)
  2. SSH-executes the skill on the assigned Vast.ai instance
  3. Reports success/failure back to the queue
  4. Loops until the queue is empty

Uses persistent SSH connections via subprocess (paramiko optional upgrade).

Usage (typically called by batch_dispatcher, not directly):
    from agentiq_labclaw.compute.worker import Worker

    worker = Worker(instance_id=123, ssh_host="1.2.3.4", ssh_port=12345)
    worker.run()  # blocks until queue empty
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time

logger = logging.getLogger("labclaw.compute.worker")

SSH_KEY_PATH = os.path.expanduser("~/.ssh/xpclabs")


class Worker:
    """Executes batch jobs on a single Vast.ai instance."""

    def __init__(
        self,
        instance_id: int,
        ssh_host: str,
        ssh_port: int = 22,
        queue=None,
        pool_manager=None,
    ):
        self.instance_id = instance_id
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        self._queue = queue
        self._pool = pool_manager
        self.jobs_completed = 0
        self.jobs_failed = 0
        self._stop = threading.Event()

    def stop(self):
        """Signal the worker to stop after the current job."""
        self._stop.set()

    def run(self):
        """Main worker loop — claim and execute jobs until queue empty or stopped."""
        from agentiq_labclaw.compute.batch_queue import BatchQueue

        queue = self._queue or BatchQueue()
        logger.info(
            "Worker started: instance=%d, host=%s:%d",
            self.instance_id, self.ssh_host, self.ssh_port,
        )

        while not self._stop.is_set():
            job = queue.claim_job(self.instance_id)
            if job is None:
                logger.info("Worker %d: queue empty, stopping", self.instance_id)
                break

            # Mark instance busy
            if self._pool:
                self._pool.mark_busy(self.instance_id)

            job_id = job["id"]
            skill_name = job["skill_name"]
            label = job.get("label", skill_name)
            logger.info(
                "Worker %d: executing job %d — %s",
                self.instance_id, job_id, label,
            )

            try:
                result = self._execute_remote(skill_name, job["input_data"])
                queue.complete_job(job_id, result)
                self.jobs_completed += 1
                logger.info(
                    "Worker %d: job %d complete (%s)",
                    self.instance_id, job_id, label,
                )
            except Exception as e:
                error_msg = str(e)[:500]
                queue.fail_job(job_id, error_msg)
                self.jobs_failed += 1
                logger.error(
                    "Worker %d: job %d failed (%s): %s",
                    self.instance_id, job_id, label, error_msg,
                )

            # Mark instance ready for next job
            if self._pool:
                self._pool.mark_ready(self.instance_id)

        logger.info(
            "Worker %d finished: %d completed, %d failed",
            self.instance_id, self.jobs_completed, self.jobs_failed,
        )

    def _execute_remote(self, skill_name: str, input_data: dict) -> dict:
        """SSH into the Vast.ai instance and execute a skill."""
        input_json = json.dumps(input_data, default=str)

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
                "-o", "ServerAliveInterval=30",
                "-i", SSH_KEY_PATH,
                "-p", str(self.ssh_port),
                f"root@{self.ssh_host}",
                f'python3 -c "{remote_script}"',
            ],
            input=input_json,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            stderr = result.stderr[:500] if result.stderr else "no stderr"
            raise RuntimeError(f"Remote execution failed (exit {result.returncode}): {stderr}")

        stdout = result.stdout.strip()
        if not stdout:
            raise RuntimeError("Remote execution returned empty output")

        return json.loads(stdout)

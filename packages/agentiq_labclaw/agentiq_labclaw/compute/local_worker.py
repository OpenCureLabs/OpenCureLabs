"""
LocalWorker — executes batch queue jobs on the local GPU.

Same claim/execute/complete loop as the remote Worker, but calls
skill.run() directly instead of SSH-ing to a Vast.ai instance.
Uses instance_id=0 in the batch_jobs table for tracking.

Usage (typically called by batch_dispatcher, not directly):
    from agentiq_labclaw.compute.local_worker import LocalWorker

    worker = LocalWorker(worker_id=1)
    worker.run()  # blocks until queue empty
"""

from __future__ import annotations

import json
import logging
import threading

logger = logging.getLogger("labclaw.compute.local_worker")

LOCAL_INSTANCE_ID = 0


class LocalWorker:
    """Executes batch jobs on the local GPU."""

    def __init__(
        self,
        worker_id: int = 0,
        queue=None,
        batch_id: str | None = None,
        idle_timeout: int = 0,
    ):
        self.worker_id = worker_id
        self.instance_id = LOCAL_INSTANCE_ID
        self._queue = queue
        self.batch_id = batch_id
        self.idle_timeout = idle_timeout
        self.jobs_completed = 0
        self.jobs_failed = 0
        self._stop = threading.Event()

    def stop(self):
        """Signal the worker to stop after the current job."""
        self._stop.set()

    def run(self):
        """Main worker loop — claim and execute jobs until queue empty or stopped."""
        import time

        from agentiq_labclaw.compute.batch_queue import BatchQueue

        queue = self._queue or BatchQueue()
        logger.info("LocalWorker-%d started", self.worker_id)

        while not self._stop.is_set():
            job = queue.claim_job(self.instance_id, batch_id=self.batch_id)
            if job is None:
                if self.idle_timeout > 0:
                    waited = 0
                    while waited < self.idle_timeout and not self._stop.is_set():
                        time.sleep(5)
                        waited += 5
                        job = queue.claim_job(self.instance_id, batch_id=self.batch_id)
                        if job is not None:
                            break
                    if job is None:
                        logger.info(
                            "LocalWorker-%d: queue empty after %ds idle, stopping",
                            self.worker_id, waited,
                        )
                        break
                else:
                    logger.info("LocalWorker-%d: queue empty, stopping", self.worker_id)
                    break

            job_id = job["id"]
            skill_name = job["skill_name"]
            label = job.get("label", skill_name)
            logger.info(
                "LocalWorker-%d: executing job %d — %s",
                self.worker_id, job_id, label,
            )

            try:
                result = self._execute_local(skill_name, job["input_data"])
                queue.complete_job(job_id, result)
                self.jobs_completed += 1
                logger.info(
                    "LocalWorker-%d: job %d complete (%s)",
                    self.worker_id, job_id, label,
                )
            except Exception as e:
                error_msg = str(e)[:2000]
                queue.fail_job(job_id, error_msg)
                self.jobs_failed += 1
                logger.error(
                    "LocalWorker-%d: job %d failed (%s): %s",
                    self.worker_id, job_id, label, error_msg,
                )

        logger.info(
            "LocalWorker-%d finished: %d completed, %d failed",
            self.worker_id, self.jobs_completed, self.jobs_failed,
        )

    def _execute_local(self, skill_name: str, input_data: dict) -> dict:
        """Execute a skill directly on the local machine."""
        from agentiq_labclaw.base import get_skill

        SkillClass = get_skill(skill_name)
        skill = SkillClass()
        validated_input = SkillClass.input_schema.model_validate(input_data)
        result = skill.run(validated_input)
        return result.model_dump() if hasattr(result, "model_dump") else json.loads(json.dumps(result, default=str))

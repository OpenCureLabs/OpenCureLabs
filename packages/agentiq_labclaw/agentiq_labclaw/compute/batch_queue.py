"""
PostgreSQL-backed job queue for batch dispatch.

Uses FOR UPDATE SKIP LOCKED for lock-free concurrent job claiming —
multiple workers can pull jobs without conflicts.

Usage:
    from agentiq_labclaw.compute.batch_queue import BatchQueue

    queue = BatchQueue()
    batch_id = queue.submit_batch(tasks)           # insert 100 pending jobs
    job = queue.claim_job(instance_id=42)           # atomic claim
    queue.complete_job(job["id"], result_data={})   # mark done
    status = queue.batch_status(batch_id)           # {pending: 40, running: 10, ...}
"""

from __future__ import annotations

import json
import logging
import os
import uuid

logger = logging.getLogger("labclaw.compute.batch_queue")


def _get_conn():
    """Get a PostgreSQL connection."""
    import psycopg2
    db_url = os.environ.get("POSTGRES_URL", "dbname=opencurelabs port=5433")
    return psycopg2.connect(db_url)


class BatchQueue:
    """PostgreSQL-backed job queue with atomic claiming."""

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Create batch_jobs and vast_pool tables if they don't exist."""
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS batch_jobs (
                    id          SERIAL PRIMARY KEY,
                    batch_id    TEXT NOT NULL,
                    skill_name  TEXT NOT NULL,
                    input_data  JSONB NOT NULL,
                    domain      TEXT,
                    label       TEXT,
                    priority    INTEGER DEFAULT 5,
                    status      TEXT DEFAULT 'pending',
                    instance_id INTEGER,
                    result_data JSONB,
                    error       TEXT,
                    retry_count INTEGER DEFAULT 0,
                    created_at  TIMESTAMP DEFAULT NOW(),
                    claimed_at  TIMESTAMP,
                    started_at  TIMESTAMP,
                    completed_at TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_batch_jobs_batch_status
                    ON batch_jobs(batch_id, status);
                CREATE INDEX IF NOT EXISTS idx_batch_jobs_status_priority
                    ON batch_jobs(status, priority);

                CREATE TABLE IF NOT EXISTS vast_pool (
                    id           SERIAL PRIMARY KEY,
                    instance_id  INTEGER UNIQUE NOT NULL,
                    ssh_host     TEXT,
                    ssh_port     INTEGER DEFAULT 22,
                    gpu_name     TEXT,
                    cost_per_hr  REAL,
                    status       TEXT DEFAULT 'provisioning',
                    jobs_done    INTEGER DEFAULT 0,
                    created_at   TIMESTAMP DEFAULT NOW(),
                    ready_at     TIMESTAMP,
                    destroyed_at TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_vast_pool_status
                    ON vast_pool(status);
            """)
            conn.commit()
            cur.close()
        finally:
            conn.close()

    # ── Submit ────────────────────────────────────────────────────────────

    def submit_batch(self, tasks: list) -> str:
        """Insert a batch of tasks as pending jobs. Returns batch_id."""
        batch_id = uuid.uuid4().hex[:12]
        conn = _get_conn()
        try:
            cur = conn.cursor()
            for task in tasks:
                cur.execute(
                    """
                    INSERT INTO batch_jobs
                        (batch_id, skill_name, input_data, domain, label, priority)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        batch_id,
                        task.skill_name,
                        json.dumps(task.input_data, default=str),
                        task.domain,
                        task.label,
                        task.priority,
                    ),
                )
            conn.commit()
            cur.close()
            logger.info("Submitted batch %s with %d jobs", batch_id, len(tasks))
        finally:
            conn.close()
        return batch_id

    # ── Claim (atomic, lock-free) ────────────────────────────────────────

    def claim_job(self, instance_id: int, batch_id: str | None = None) -> dict | None:
        """Atomically claim the next pending job for an instance.

        Uses FOR UPDATE SKIP LOCKED so multiple workers never conflict.
        Returns job dict or None if queue is empty.
        If batch_id is provided, only claims jobs from that batch.
        """
        conn = _get_conn()
        try:
            cur = conn.cursor()
            if batch_id:
                cur.execute(
                    """
                    UPDATE batch_jobs
                    SET status = 'running',
                        instance_id = %s,
                        claimed_at = NOW(),
                        started_at = NOW()
                    WHERE id = (
                        SELECT id FROM batch_jobs
                        WHERE status = 'pending' AND batch_id = %s
                        ORDER BY priority ASC, id ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    RETURNING id, batch_id, skill_name, input_data, domain, label
                    """,
                    (instance_id, batch_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE batch_jobs
                    SET status = 'running',
                        instance_id = %s,
                        claimed_at = NOW(),
                        started_at = NOW()
                    WHERE id = (
                        SELECT id FROM batch_jobs
                        WHERE status = 'pending'
                        ORDER BY priority ASC, id ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    RETURNING id, batch_id, skill_name, input_data, domain, label
                    """,
                    (instance_id,),
                )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            if row is None:
                return None
            return {
                "id": row[0],
                "batch_id": row[1],
                "skill_name": row[2],
                "input_data": row[3] if isinstance(row[3], dict) else json.loads(row[3]),
                "domain": row[4],
                "label": row[5],
            }
        finally:
            conn.close()

    # ── Complete / Fail ──────────────────────────────────────────────────

    def complete_job(self, job_id: int, result_data: dict):
        """Mark a job as completed with its results."""
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE batch_jobs
                SET status = 'done',
                    result_data = %s,
                    completed_at = NOW()
                WHERE id = %s
                """,
                (json.dumps(result_data, default=str), job_id),
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

    def fail_job(self, job_id: int, error: str, retry: bool = True):
        """Mark a job as failed. Requeue if retry_count < 2."""
        conn = _get_conn()
        try:
            cur = conn.cursor()
            if retry:
                cur.execute(
                    """
                    UPDATE batch_jobs
                    SET status = CASE WHEN retry_count < 2 THEN 'pending' ELSE 'failed' END,
                        error = %s,
                        retry_count = retry_count + 1,
                        instance_id = NULL,
                        claimed_at = NULL,
                        started_at = NULL
                    WHERE id = %s
                    RETURNING status, retry_count
                    """,
                    (error, job_id),
                )
                row = cur.fetchone()
                if row:
                    logger.info(
                        "Job %d %s (retry %d): %s",
                        job_id, row[0], row[1], error[:200],
                    )
            else:
                cur.execute(
                    """
                    UPDATE batch_jobs
                    SET status = 'failed', error = %s, completed_at = NOW()
                    WHERE id = %s
                    """,
                    (error, job_id),
                )
            conn.commit()
            cur.close()
        finally:
            conn.close()

    # ── Heartbeat (stale job recovery) ───────────────────────────────────

    def heartbeat(self, job_id: int):
        """Update started_at to signal the job is still alive."""
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE batch_jobs SET started_at = NOW() WHERE id = %s",
                (job_id,),
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

    def reclaim_stale_jobs(self, stale_minutes: int = 15):
        """Requeue jobs that have been 'running' without a heartbeat for too long."""
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE batch_jobs
                SET status = 'pending',
                    instance_id = NULL,
                    claimed_at = NULL,
                    started_at = NULL
                WHERE status = 'running'
                  AND started_at < NOW() - INTERVAL '%s minutes'
                  AND retry_count < 2
                RETURNING id
                """,
                (stale_minutes,),
            )
            reclaimed = cur.fetchall()
            conn.commit()
            cur.close()
            if reclaimed:
                logger.warning("Reclaimed %d stale jobs", len(reclaimed))
            return len(reclaimed)
        finally:
            conn.close()

    # ── Status ───────────────────────────────────────────────────────────

    def batch_status(self, batch_id: str) -> dict:
        """Get counts by status for a batch."""
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT status, COUNT(*) FROM batch_jobs
                WHERE batch_id = %s
                GROUP BY status
                """,
                (batch_id,),
            )
            rows = cur.fetchall()
            cur.close()
            counts = {row[0]: row[1] for row in rows}
            counts["total"] = sum(counts.values())
            return counts
        finally:
            conn.close()

    def active_batches(self) -> list[dict]:
        """List batches that still have pending or running jobs."""
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT batch_id,
                       COUNT(*) FILTER (WHERE status = 'pending')  AS pending,
                       COUNT(*) FILTER (WHERE status = 'running')  AS running,
                       COUNT(*) FILTER (WHERE status = 'done')     AS done,
                       COUNT(*) FILTER (WHERE status = 'failed')   AS failed,
                       COUNT(*)                                    AS total,
                       MIN(created_at)                             AS started
                FROM batch_jobs
                GROUP BY batch_id
                HAVING COUNT(*) FILTER (WHERE status IN ('pending', 'running')) > 0
                ORDER BY MIN(created_at) DESC
                """,
            )
            rows = cur.fetchall()
            cur.close()
            return [
                {
                    "batch_id": r[0], "pending": r[1], "running": r[2],
                    "done": r[3], "failed": r[4], "total": r[5],
                    "started": str(r[6]),
                }
                for r in rows
            ]
        finally:
            conn.close()

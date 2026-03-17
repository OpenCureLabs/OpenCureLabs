"""Critique log database interface."""

import json
import logging

from agentiq_labclaw.db.connection import get_connection

logger = logging.getLogger("labclaw.db.critique_log")


def log_critique(run_id: int, reviewer: str, critique_json: dict) -> int:
    """Log a critique from a reviewer agent. Returns the critique ID."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO critique_log (run_id, reviewer, critique_json) VALUES (%s, %s, %s) RETURNING id",
            (run_id, reviewer, json.dumps(critique_json)),
        )
        critique_id = cur.fetchone()[0]
    logger.info("Logged critique %d from %s for run %d", critique_id, reviewer, run_id)
    return critique_id


def get_critiques_for_run(run_id: int) -> list[dict]:
    """Get all critiques for a pipeline run."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, reviewer, critique_json, timestamp FROM critique_log WHERE run_id = %s ORDER BY timestamp",
            (run_id,),
        )
        rows = cur.fetchall()
        return [
            {"id": r[0], "reviewer": r[1], "critique_json": r[2], "timestamp": r[3].isoformat() if r[3] else None}
            for r in rows
        ]

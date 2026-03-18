"""Agent runs database interface."""

import json
import logging

from agentiq_labclaw.db.connection import get_connection

logger = logging.getLogger("labclaw.db.agent_runs")


def start_run(agent_name: str) -> int:
    """Record the start of an agent run. Returns the run ID."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO agent_runs (agent_name, status) VALUES (%s, %s) RETURNING id",
            (agent_name, "running"),
        )
        run_id = cur.fetchone()[0]
    logger.info("Started agent run %d for %s", run_id, agent_name)
    return run_id


def complete_run(run_id: int, status: str, result: dict | None = None):
    """Mark an agent run as completed."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE agent_runs SET completed_at = NOW(), status = %s, result_json = %s WHERE id = %s",
            (status, json.dumps(result) if result else None, run_id),
        )
    logger.info("Completed agent run %d with status: %s", run_id, status)


def get_run(run_id: int) -> dict | None:
    """Get an agent run by ID."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, agent_name, started_at, completed_at, status, result_json FROM agent_runs WHERE id = %s",
            (run_id,),
        )
        row = cur.fetchone()
        if row:
            return {
                "id": row[0],
                "agent_name": row[1],
                "started_at": row[2].isoformat() if row[2] else None,
                "completed_at": row[3].isoformat() if row[3] else None,
                "status": row[4],
                "result_json": row[5],
            }
    return None

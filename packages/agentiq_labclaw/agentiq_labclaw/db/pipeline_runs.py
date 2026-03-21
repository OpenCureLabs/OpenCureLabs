"""Pipeline runs database interface."""

import json
import logging

from agentiq_labclaw.db.connection import get_connection

logger = logging.getLogger("labclaw.db.pipeline_runs")


def start_pipeline(pipeline_name: str, input_data: dict | None = None) -> int | None:
    """Record the start of a pipeline run. Returns the run ID, or None if DB unavailable."""
    conn = get_connection()
    if conn is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (pipeline_name, input_data, status) VALUES (%s, %s, %s) RETURNING id",
            (pipeline_name, json.dumps(input_data) if input_data else None, "running"),
        )
        run_id = cur.fetchone()[0]
    logger.info("Started pipeline run %d: %s", run_id, pipeline_name)
    return run_id


def complete_pipeline(run_id: int, status: str, output_path: str | None = None):
    """Mark a pipeline run as completed."""
    conn = get_connection()
    if conn is None:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE pipeline_runs SET status = %s, output_path = %s WHERE id = %s",
            (status, output_path, run_id),
        )
    logger.info("Completed pipeline run %d: %s", run_id, status)

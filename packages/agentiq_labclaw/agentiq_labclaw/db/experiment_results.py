"""Experiment results database interface."""

import json
import logging

from agentiq_labclaw.db.connection import get_connection

logger = logging.getLogger("labclaw.db.experiment_results")


def store_result(
    pipeline_run_id: int, result_type: str, result_data: dict,
    novel: bool = False, status: str = "published",
) -> int:
    """Store an experiment result. Returns the result ID."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO experiment_results (pipeline_run_id, result_type, result_data, novel, status)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (pipeline_run_id, result_type, json.dumps(result_data), novel, status),
        )
        result_id = cur.fetchone()[0]
    logger.info("Stored result %d (type: %s, novel: %s, status: %s)", result_id, result_type, novel, status)
    return result_id


def check_novelty(result_type: str, result_data: dict) -> bool:
    """Check if a result is novel by comparing against existing results."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM experiment_results WHERE result_type = %s AND result_data = %s",
            (result_type, json.dumps(result_data)),
        )
        count = cur.fetchone()[0]
    return count == 0

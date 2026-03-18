"""Novelty filter — flags results as novel vs replication of existing findings."""

import logging

from agentiq_labclaw.db.experiment_results import check_novelty as db_check_novelty

logger = logging.getLogger("labclaw.guardrails.novelty_filter")


def check_novelty(result_type: str, result_data: dict) -> bool:
    """
    Check if a result is novel by comparing against experiment_results in PostgreSQL.

    Returns True if the result is novel (no prior match exists).
    Only novel results trigger the Grok literature reviewer.
    """
    is_novel = db_check_novelty(result_type, result_data)
    if is_novel:
        logger.info("Result flagged as NOVEL (type: %s)", result_type)
    else:
        logger.info("Result is a replication (type: %s)", result_type)
    return is_novel

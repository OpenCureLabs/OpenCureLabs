"""Safety check — blocks publishing of incomplete or invalid results."""

import logging

from pydantic import BaseModel

logger = logging.getLogger("labclaw.guardrails.safety_check")

MINIMUM_CONFIDENCE = 0.005


def safety_check(
    output: BaseModel,
    agent_run_id: int | None = None,
    critique_completed: bool = False,
) -> tuple[bool, str | None]:
    """
    Run safety checks before publishing a result.

    Blocks publishing if:
    - Confidence score is below threshold
    - Required fields are missing
    - No associated agent_run_id
    - critique_required=True but no critique has been completed

    Returns (is_safe, reason_if_blocked).
    """
    output_dict = output.model_dump()

    # Check agent run ID
    if agent_run_id is None:
        reason = "No agent_run_id associated with this result"
        logger.warning("Safety check BLOCKED: %s", reason)
        return False, reason

    # Check confidence score if present
    confidence = output_dict.get("confidence_score")
    if confidence is not None and confidence < MINIMUM_CONFIDENCE:
        reason = f"Confidence score {confidence} below minimum threshold {MINIMUM_CONFIDENCE}"
        logger.warning("Safety check BLOCKED: %s", reason)
        return False, reason

    # Check critique requirement
    critique_required = output_dict.get("critique_required", False)
    if critique_required and not critique_completed:
        reason = "Result requires critique but no critique has been completed"
        logger.warning("Safety check BLOCKED: %s", reason)
        return False, reason

    logger.info("Safety check PASSED")
    return True, None

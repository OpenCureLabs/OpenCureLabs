"""Output validator — checks skill output matches its declared Pydantic schema."""

import logging

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("labclaw.guardrails.output_validator")


def validate_output(output: BaseModel, schema: type[BaseModel]) -> tuple[bool, str | None]:
    """
    Validate that a skill output conforms to its declared schema.

    Returns (is_valid, error_message).
    """
    try:
        # Re-validate by dumping and re-parsing
        schema.model_validate(output.model_dump())
        logger.info("Output validation passed for %s", schema.__name__)
        return True, None
    except ValidationError as e:
        error_msg = f"Output validation failed: {e}"
        logger.error(error_msg)
        return False, error_msg

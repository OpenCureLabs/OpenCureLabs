"""Vast.ai GPU dispatch — provisions instances, runs jobs, streams results back."""

import logging
import os

logger = logging.getLogger("labclaw.compute.vast_dispatcher")


def dispatch(skill, input_data):
    """
    Dispatch a skill execution to Vast.ai for heavy compute.

    1. Provision a GPU instance matching skill requirements
    2. Upload input data
    3. Execute the skill remotely
    4. Stream results back
    5. Terminate the instance
    """
    vast_key = os.environ.get("VAST_AI_KEY")
    if not vast_key:
        raise RuntimeError("VAST_AI_KEY not set — cannot dispatch to Vast.ai")

    logger.info("Dispatching %s to Vast.ai (GPU required: %s)", skill.name, skill.gpu_required)

    # TODO: Implement Vast.ai API integration
    # - POST /api/v0/instances/ to provision
    # - SCP input data to instance
    # - SSH execute skill
    # - SCP results back
    # - DELETE instance
    raise NotImplementedError(
        f"Vast.ai dispatch for skill '{skill.name}' is not yet implemented. "
        "Run with compute='local' or implement the Vast.ai API integration."
    )

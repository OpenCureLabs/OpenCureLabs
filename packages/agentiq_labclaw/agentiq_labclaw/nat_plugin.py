"""
NAT plugin registration — bridges LabClaw skills into NeMo Agent Toolkit.

Each LabClaw skill is exposed as a NAT function type called `labclaw_skill`
with a `skill_name` parameter that selects which skill to run.
"""

import json
import logging

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig
from pydantic import BaseModel, Field

from agentiq_labclaw.base import get_skill

logger = logging.getLogger("labclaw.nat_plugin")


class LabClawSkillConfig(FunctionBaseConfig, name="labclaw_skill"):
    """NAT function config for LabClaw skills. Use `skill_name` in the workflow YAML."""

    skill_name: str = Field(description="Name of the LabClaw skill to invoke")


@register_function(config_type=LabClawSkillConfig)
async def labclaw_skill_function(config: LabClawSkillConfig, builder: Builder):
    # Import all skills to ensure they're registered
    import agentiq_labclaw.skills  # noqa: F401

    skill_cls = get_skill(config.skill_name)
    skill_instance = skill_cls()

    async def _run_skill(input_json: str) -> str:
        input_data = skill_instance.input_schema.model_validate_json(input_json)
        result = skill_instance.execute(input_data)
        if isinstance(result, BaseModel):
            return result.model_dump_json(indent=2)
        return json.dumps(result, default=str)

    yield FunctionInfo.from_fn(
        _run_skill,
        description=skill_instance.description or f"LabClaw skill: {config.skill_name}",
    )

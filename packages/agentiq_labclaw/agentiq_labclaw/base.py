"""
Base classes and decorators for LabClaw skills.
"""

import logging
import os
from abc import ABC, abstractmethod

from pydantic import BaseModel

logger = logging.getLogger("labclaw")


class LabClawSkill(ABC):
    """Base class for all LabClaw scientific skills."""

    name: str = ""
    description: str = ""
    compute: str = "local"  # "local" | "vast_ai"
    gpu_required: bool = False
    input_schema: type[BaseModel] | None = None
    output_schema: type[BaseModel] | None = None

    def execute(self, input_data: BaseModel) -> BaseModel:
        """Execute the skill, routing to Vast.ai if configured.

        Priority: LABCLAW_COMPUTE env var > decorator default.
        Falls back to local if Vast.ai dispatch fails or key is missing.
        """
        compute = os.environ.get("LABCLAW_COMPUTE") or self.compute

        if compute == "vast_ai":
            if not os.environ.get("VAST_AI_KEY"):
                logger.warning(
                    "[%s] LABCLAW_COMPUTE=vast_ai but VAST_AI_KEY not set — running locally",
                    self.name,
                )
                return self.run(input_data)
            try:
                logger.info("[%s] Dispatching to Vast.ai...", self.name)
                return self._dispatch_to_vast_ai(input_data)
            except Exception as e:
                logger.error(
                    "[%s] Vast.ai dispatch failed: %s — falling back to local",
                    self.name, e,
                )
                return self.run(input_data)

        logger.info("[%s] Running locally (compute=%s)", self.name, compute)
        return self.run(input_data)

    @abstractmethod
    def run(self, input_data: BaseModel) -> BaseModel:
        """Run the skill locally. Must be implemented by subclasses."""
        ...

    def _dispatch_to_vast_ai(self, input_data: BaseModel) -> BaseModel:
        """Dispatch job to Vast.ai for heavy compute."""
        from agentiq_labclaw.compute.vast_dispatcher import dispatch

        return dispatch(self, input_data)


def labclaw_skill(
    name: str,
    description: str,
    input_schema: type[BaseModel],
    output_schema: type[BaseModel],
    compute: str = "local",
    gpu_required: bool = False,
):
    """Decorator to register a class as a LabClaw skill."""

    def decorator(cls):
        cls.name = name
        cls.description = description
        cls.compute = compute
        cls.gpu_required = gpu_required
        cls.input_schema = input_schema
        cls.output_schema = output_schema

        # Register with the skill registry
        _SKILL_REGISTRY[name] = cls
        logger.info("Registered LabClaw skill: %s", name)

        return cls

    return decorator


# Global skill registry
_SKILL_REGISTRY: dict[str, type[LabClawSkill]] = {}


def get_skill(name: str) -> type[LabClawSkill]:
    """Get a registered skill by name."""
    if not _SKILL_REGISTRY:
        # Skills register via @labclaw_skill when their module is imported.
        # If the registry is empty, eagerly import all skill modules.
        from agentiq_labclaw.skills import register_all
        register_all()
    if name not in _SKILL_REGISTRY:
        raise KeyError(f"Skill '{name}' not found. Available: {list(_SKILL_REGISTRY.keys())}")
    return _SKILL_REGISTRY[name]


def list_skills() -> list[str]:
    """List all registered skill names."""
    return list(_SKILL_REGISTRY.keys())

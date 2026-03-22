"""
agentiq_labclaw — Scientific skill layer for OpenCure Labs.

Built on NVIDIA NeMo Agent Toolkit (AgentIQ), LabClaw provides domain-specific
scientific skills, guardrails, and connectors for computational biology workflows.
"""
from agentiq_labclaw.base import LabClawSkill, labclaw_skill
__version__ = "0.24.0"
__all__ = ["LabClawSkill", "labclaw_skill"]

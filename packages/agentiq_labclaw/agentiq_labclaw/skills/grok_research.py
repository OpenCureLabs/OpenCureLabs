"""Grok researcher skill — searches for new datasets relevant to a research domain."""

import logging

from pydantic import BaseModel, Field

from agentiq_labclaw.base import LabClawSkill, labclaw_skill

logger = logging.getLogger("labclaw.skills.grok_research")


class GrokResearchInput(BaseModel):
    domain: str = Field(
        description="Research domain to scan (e.g. 'cancer genomics', 'rare disease', 'drug discovery')",
    )


class GrokResearchOutput(BaseModel):
    domain: str
    discoveries: list[dict] = Field(default_factory=list)
    count: int = 0
    novel: bool = False
    critique_required: bool = False


@labclaw_skill(
    name="grok_research",
    description="Search for new datasets, preprints, and data sources in a research domain using Grok",
    input_schema=GrokResearchInput,
    output_schema=GrokResearchOutput,
    compute="local",
    gpu_required=False,
)
class GrokResearchSkill(LabClawSkill):
    """
    Coordinator-level tool that invokes GrokResearcher to discover new datasets.
    Results can be piped to register_source to log them in the DB.
    """

    def run(self, input_data: GrokResearchInput) -> GrokResearchOutput:
        import os
        import sys

        # Add project root so reviewer module is importable
        project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        from reviewer.grok_reviewer import GrokResearcher

        logger.info("Grok researcher scanning domain: %s", input_data.domain)
        researcher = GrokResearcher()
        discoveries = researcher.search_new_datasets(input_data.domain)

        return GrokResearchOutput(
            domain=input_data.domain,
            discoveries=discoveries,
            count=len(discoveries),
            novel=len(discoveries) > 0,
            critique_required=False,
        )

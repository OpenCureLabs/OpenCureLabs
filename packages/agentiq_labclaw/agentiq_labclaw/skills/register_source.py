"""Register discovered data source skill — called by Grok when it finds new datasets."""

import logging

from pydantic import BaseModel

from agentiq_labclaw.base import LabClawSkill, labclaw_skill

logger = logging.getLogger("labclaw.skills.register_source")


class RegisterSourceInput(BaseModel):
    url: str
    domain: str  # e.g. "genomics", "proteomics", "drug_bioactivity"
    discovered_by: str = "grok"
    notes: str | None = None


class RegisterSourceOutput(BaseModel):
    source_id: int
    url: str
    domain: str
    registered: bool
    novel: bool
    critique_required: bool


@labclaw_skill(
    name="register_source",
    description="Registers a newly discovered data source for coordinator validation and ingestion",
    input_schema=RegisterSourceInput,
    output_schema=RegisterSourceOutput,
    compute="local",
    gpu_required=False,
)
class RegisterSourceSkill(LabClawSkill):
    """
    Called by Grok when it discovers a new dataset source.
    Writes to discovered_sources in PostgreSQL and queues for coordinator review.
    """

    def run(self, input_data: RegisterSourceInput) -> RegisterSourceOutput:
        logger.info("Registering source: %s (domain: %s)", input_data.url, input_data.domain)

        from agentiq_labclaw.db.discovered_sources import register_source

        source_id = register_source(
            url=input_data.url,
            domain=input_data.domain,
            discovered_by=input_data.discovered_by,
            notes=input_data.notes,
        )

        return RegisterSourceOutput(
            source_id=source_id,
            url=input_data.url,
            domain=input_data.domain,
            registered=True,
            novel=True,
            critique_required=False,
        )

"""Scientific PDF report generation skill."""

import logging
from pathlib import Path

from pydantic import BaseModel

from agentiq_labclaw.base import LabClawSkill, labclaw_skill

logger = logging.getLogger("labclaw.skills.report_generator")


class ReportInput(BaseModel):
    title: str
    pipeline_run_id: int
    sections: list[dict]  # [{"heading": "...", "content": "...", "figures": [...]}]
    critique_json: dict | None = None
    output_dir: str = "/root/opencurelabs/reports/"


class ReportOutput(BaseModel):
    pdf_path: str
    page_count: int
    novel: bool
    critique_required: bool


@labclaw_skill(
    name="report_generator",
    description="Generates scientific PDF reports from pipeline results and critique",
    input_schema=ReportInput,
    output_schema=ReportOutput,
    compute="local",
    gpu_required=False,
)
class ReportGeneratorSkill(LabClawSkill):
    """
    Pipeline:
    1. Compile sections into LaTeX or Markdown
    2. Include figures and tables
    3. Append critique notes if present
    4. Render to PDF
    """

    def run(self, input_data: ReportInput) -> ReportOutput:
        logger.info("Generating report: %s", input_data.title)

        output_dir = Path(input_data.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # TODO: Integrate reportlab or LaTeX compilation
        return ReportOutput(
            pdf_path="",
            page_count=0,
            novel=False,
            critique_required=False,
        )

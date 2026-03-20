"""Scientific PDF report generation skill — reportlab integration."""

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

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
    1. Build PDF document with reportlab
    2. Add title page, sections, tables, and critique appendix
    3. Save to reports directory
    """

    def run(self, input_data: ReportInput) -> ReportOutput:
        logger.info("Generating report: %s", input_data.title)

        output_dir = Path(input_data.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in input_data.title).strip().replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_path = output_dir / f"{safe_title}_{timestamp}.pdf"

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("ReportTitle", parent=styles["Title"], fontSize=20, spaceAfter=30)
        heading_style = ParagraphStyle("SectionHeading", parent=styles["Heading2"], spaceBefore=20, spaceAfter=10)
        body_style = styles["BodyText"]
        code_style = ParagraphStyle(
            "Code", parent=styles["Code"], fontSize=8, leading=10,
            backColor=colors.HexColor("#f5f5f5"),
        )

        elements = []

        # Title
        elements.append(Paragraph(input_data.title, title_style))
        elements.append(Paragraph(
            f"Pipeline Run #{input_data.pipeline_run_id} — Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            body_style,
        ))
        elements.append(Spacer(1, 1 * cm))

        # Sections
        for section in input_data.sections:
            heading = section.get("heading", "Untitled Section")
            content = section.get("content", "")
            elements.append(Paragraph(heading, heading_style))

            # Content — handle multi-line text
            for para in content.split("\n\n"):
                para = para.strip()
                if para:
                    elements.append(Paragraph(para.replace("\n", "<br/>"), body_style))
                    elements.append(Spacer(1, 0.3 * cm))

            # Tables from section data
            table_data = section.get("table")
            if table_data and isinstance(table_data, list) and len(table_data) > 1:
                t = Table(table_data)
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4A90D9")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F0F0F0")]),
                ]))
                elements.append(t)
                elements.append(Spacer(1, 0.5 * cm))

        # Critique appendix
        if input_data.critique_json:
            elements.append(Paragraph("Reviewer Critique", heading_style))
            critique_text = json.dumps(input_data.critique_json, indent=2, default=str)
            # Wrap long JSON for PDF
            for line in critique_text.split("\n"):
                elements.append(Paragraph(line, code_style))

        # Build PDF
        doc.build(elements)

        # Count pages (approximate from elements)
        page_count = max(1, len(elements) // 15)

        logger.info("Report saved to %s (%d pages approx)", pdf_path, page_count)

        return ReportOutput(
            pdf_path=str(pdf_path),
            page_count=page_count,
            novel=False,
            critique_required=False,
        )

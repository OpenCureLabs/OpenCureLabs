"""PDF report publisher — generates and stores PDF reports using reportlab."""

import json
import logging
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

logger = logging.getLogger("labclaw.publishers.pdf")


def _default_reports_dir() -> str:
    """Resolve the default reports directory from project root."""
    import os
    root = os.environ.get("OPENCURELABS_ROOT", str(Path(__file__).resolve().parents[3]))
    return str(Path(root) / "reports")


class PDFPublisher:
    """Generates PDF reports from pipeline results."""

    def __init__(self, output_dir: str | None = None):
        if output_dir is None:
            output_dir = _default_reports_dir()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(self, title: str, sections: list[dict], critique: dict | None = None, synthetic: bool = False) -> str:
        """
        Generate a PDF report.

        sections: [{"heading": "...", "content": "...", "figures": [...]}]

        Returns the path to the generated PDF.
        """
        logger.info("Generating PDF report: %s", title)

        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip().replace(" ", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_path = self.output_dir / f"{safe_title}_{timestamp}.pdf"

        doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        elements = []

        # Synthetic data disclaimer banner
        if synthetic:
            disclaimer_style = ParagraphStyle(
                "SyntheticDisclaimer",
                parent=styles["Heading2"],
                textColor=colors.white,
                backColor=colors.HexColor("#cc0000"),
                alignment=1,  # center
                spaceAfter=12,
                spaceBefore=6,
            )
            elements.append(Paragraph(
                "⚠ SYNTHETIC DATA — NOT FOR CLINICAL OR PRODUCTION USE ⚠",
                disclaimer_style,
            ))
            elements.append(Spacer(1, 0.3 * cm))

        # Title
        elements.append(Paragraph(title, styles["Title"]))
        elements.append(Spacer(1, 0.5 * cm))

        # Sections
        for section in sections:
            elements.append(Paragraph(section.get("heading", ""), styles["Heading2"]))
            content = section.get("content", "").replace("\n", "<br/>")
            elements.append(Paragraph(content, styles["BodyText"]))
            elements.append(Spacer(1, 0.3 * cm))

        # Critique
        if critique:
            elements.append(Paragraph("Reviewer Critique", styles["Heading2"]))
            code_style = ParagraphStyle("Code", parent=styles["Code"], fontSize=8, backColor=colors.HexColor("#f5f5f5"))
            for line in json.dumps(critique, indent=2, default=str).split("\n"):
                elements.append(Paragraph(line, code_style))

        doc.build(elements)
        logger.info("PDF report saved to %s", pdf_path)
        return str(pdf_path)

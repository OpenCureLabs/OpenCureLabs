"""PDF report publisher — generates and stores PDF reports."""

import logging
from pathlib import Path

logger = logging.getLogger("labclaw.publishers.pdf")


class PDFPublisher:
    """Generates PDF reports from pipeline results."""

    def __init__(self, output_dir: str = "/root/xpc-labs/reports/"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(self, title: str, sections: list[dict], critique: dict | None = None) -> str:
        """
        Generate a PDF report.

        sections: [{"heading": "...", "content": "...", "figures": [...]}]

        Returns the path to the generated PDF.
        """
        logger.info("Generating PDF report: %s", title)

        # TODO: Integrate reportlab or weasyprint for PDF generation
        # For now, generate a Markdown file as placeholder
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip().replace(" ", "_")
        md_path = self.output_dir / f"{safe_title}.md"

        lines = [f"# {title}\n"]
        for section in sections:
            lines.append(f"\n## {section.get('heading', 'Untitled')}\n")
            lines.append(section.get("content", "") + "\n")

        if critique:
            lines.append("\n## Reviewer Critique\n")
            lines.append(f"```json\n{critique}\n```\n")

        md_path.write_text("\n".join(lines))
        logger.info("Report saved to %s (Markdown placeholder — PDF generation pending)", md_path)
        return str(md_path)

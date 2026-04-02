"""Claude Opus scientific critic — structured JSON critique of pipeline results."""

import json
import logging
import os

import anthropic

logger = logging.getLogger("labclaw.reviewer.claude")


class ClaudeReviewer:
    """
    Calls Claude Opus 4.6 with a scientific critic system prompt.
    Returns structured JSON critique for novel or high-confidence results.
    """

    SYSTEM_PROMPT = (
        "You are a scientific critic reviewing computational biology results "
        "produced by an autonomous research pipeline.\n"
        "Your role is to evaluate:\n"
        "1. Scientific logic — does the methodology match the question?\n"
        "2. Statistical validity — are the statistics appropriate and correctly applied?\n"
        "3. Interpretive accuracy — do the conclusions follow from the data?\n"
        "4. Reproducibility — could this result be independently verified?\n"
        "5. Novelty assessment — is this a genuine new finding or expected behavior?\n\n"
        "IMPORTANT: Distinguish between BAD science and INCREMENTAL science.\n"
        "A methodologically sound result that confirms known biology is NOT flawed — "
        "it is confirmatory. Reserve low scores (0-3) for results with genuine "
        "methodological problems, not for results that merely lack novelty.\n\n"
        "Scoring guide:\n"
        "- 8-10: Novel, scientifically rigorous, immediately publishable.\n"
        "- 6-7: Sound methodology with useful results; minor gaps to address.\n"
        "- 4-5: Methodologically correct but confirmatory/incremental; "
        "useful as validation data or building blocks for future work.\n"
        "- 2-3: Significant methodological concerns or unusable output.\n"
        "- 0-1: Fundamentally flawed — wrong method, critical errors, or "
        "uninterpretable output.\n\n"
        "Recommendation criteria:\n"
        "- \"publish\": overall_score >= 8 AND no critical methodological flaws.\n"
        "- \"revise\": overall_score 6-7. Sound work needing minor improvements.\n"
        "- \"archive\": overall_score 4-5. Methodologically correct but confirmatory "
        "or incremental. Valuable as reference data or pipeline validation.\n"
        "- \"reject\": overall_score < 4. Genuine methodological flaws or unusable output.\n\n"
        "Always return your critique as a JSON object with this schema:\n"
        "{\n"
        '  "overall_score": 0-10,\n'
        '  "scientific_logic": {"score": 0-10, "comments": "..."},\n'
        '  "statistical_validity": {"score": 0-10, "comments": "..."},\n'
        '  "interpretive_accuracy": {"score": 0-10, "comments": "..."},\n'
        '  "reproducibility": {"score": 0-10, "comments": "..."},\n'
        '  "novelty_assessment": {"is_novel": true/false, "comments": "..."},\n'
        '  "recommendation": "publish" | "revise" | "archive" | "reject",\n'
        '  "revision_notes": "..."\n'
        "}"
    )

    def __init__(self, api_key: str | None = None, model: str = "claude-opus-4-6"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def critique(
        self,
        pipeline_name: str,
        result_data: dict,
        methodology: str = "",
        max_tokens: int = 4096,
    ) -> dict:
        """
        Submit a pipeline result for scientific critique.

        Returns the parsed JSON critique object, or a dict with an error key.
        """
        logger.info("Requesting Claude critique for %s", pipeline_name)

        user_content = (
            f"Pipeline: {pipeline_name}\n\n"
            f"Result data:\n```json\n{json.dumps(result_data, indent=2, default=str)}\n```\n"
        )
        if methodology:
            user_content += f"\nMethodology notes:\n{methodology}\n"
        user_content += "\nPlease provide your structured critique as JSON."

        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=0.0,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        response_text = message.content[0].text

        # Parse the JSON from the response
        try:
            # Try to extract JSON from markdown code block
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0]
            else:
                json_str = response_text

            critique = json.loads(json_str)
            logger.info(
                "Claude critique: overall_score=%s, recommendation=%s",
                critique.get("overall_score"),
                critique.get("recommendation"),
            )
            return critique
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning("Failed to parse Claude critique JSON: %s", e)
            return {
                "overall_score": None,
                "recommendation": "revise",
                "raw_response": response_text,
                "parse_error": str(e),
            }

    def should_critique(self, result: dict) -> bool:
        """Check if a result requires critique based on its flags."""
        return result.get("critique_required", False) or result.get("novel", False)

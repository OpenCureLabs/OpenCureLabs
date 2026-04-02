"""Grok reviewer — scientific critique and literature review."""

import json
import logging
import os
import re

import openai

logger = logging.getLogger("labclaw.reviewer.grok")

try:
    from agentiq_labclaw.nat_specialists import _log_llm_usage
except ImportError:
    _log_llm_usage = None


class GrokReviewer:
    """
    Calls Grok (xAI API, OpenAI-compatible) for scientific critique and
    literature review of pipeline results.
    """

    CRITIQUE_PROMPT = (
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
        "it is confirmatory. A high-confidence AlphaFold prediction that matches "
        "existing structures validates the pipeline and has archival value. "
        "Reserve low scores (0-3) for results with genuine methodological problems, "
        "not for results that merely lack novelty.\n\n"
        "Scoring guide:\n"
        "- 8-10: Novel, scientifically rigorous, immediately publishable.\n"
        "- 6-7: Sound methodology with useful results; minor gaps to address.\n"
        "- 4-5: Methodologically correct but confirmatory/incremental; "
        "useful as validation data or building blocks for future work.\n"
        "- 2-3: Significant methodological concerns or unusable output "
        "(e.g., very low confidence predictions, missing controls).\n"
        "- 0-1: Fundamentally flawed — wrong method, critical errors, or "
        "uninterpretable output.\n\n"
        "Recommendation criteria:\n"
        "- \"publish\": overall_score >= 8 AND no critical methodological flaws. "
        "The result is novel, scientifically sound, and ready for dissemination.\n"
        "- \"revise\": overall_score 6-7. Sound work that needs minor improvements "
        "or additional analysis before publication.\n"
        "- \"archive\": overall_score 4-5. Methodologically correct but confirmatory "
        "or incremental. Valuable as reference data, pipeline validation, or input "
        "for downstream analysis. Not flawed — just not novel enough to publish alone.\n"
        "- \"reject\": overall_score < 4. Genuine methodological flaws, unreliable "
        "output, or critical errors that make the result unusable.\n\n"
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

    LITERATURE_PROMPT = (
        "You are a literature reviewer. When presented with a novel scientific result, "
        "search recent publications and preprint servers for:\n"
        "1. Corroborating evidence — does recent literature support this finding?\n"
        "2. Contradicting evidence — are there findings that conflict?\n"
        "3. Related work — what is the current state of the art?\n"
        "4. Methodology precedent — has this approach been validated elsewhere?\n\n"
        "You MUST include a numeric literature_score (integer 0-10) and "
        "confidence_in_finding (\"high\", \"medium\", or \"low\") in your response.\n\n"
        "Return your review as a JSON object with this schema:\n"
        "{\n"
        '  "corroborating": [{"title": "...", "source": "...", "summary": "..."}],\n'
        '  "contradicting": [{"title": "...", "source": "...", "summary": "..."}],\n'
        '  "related_work": [{"title": "...", "source": "...", "relevance": "..."}],\n'
        '  "literature_score": 0-10,\n'
        '  "confidence_in_finding": "high" | "medium" | "low",\n'
        '  "summary": "..."\n'
        "}"
    )

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "grok-4-1-fast-non-reasoning",
        base_url: str = "https://api.x.ai/v1",
    ):
        self.api_key = api_key or os.environ.get("XAI_API_KEY", "")
        self.model = model
        self.client = openai.OpenAI(api_key=self.api_key, base_url=base_url)

    def critique(
        self,
        pipeline_name: str,
        result_data: dict,
        max_tokens: int = 4096,
    ) -> dict:
        """
        Scientific critique of a pipeline result.

        Returns parsed JSON critique with overall_score, recommendation, etc.
        """
        logger.info("Requesting Grok critique for %s", pipeline_name)

        user_content = (
            f"Pipeline: {pipeline_name}\n\n"
            f"Result data:\n```json\n{json.dumps(result_data, indent=2, default=str)}\n```\n"
            "\nPlease provide your structured critique as JSON."
        )

        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.0,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": self.CRITIQUE_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )

        if _log_llm_usage and response.usage:
            _log_llm_usage(
                model=self.model,
                usage={"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens},
                agent_name="grok_critique",
            )

        response_text = response.choices[0].message.content

        try:
            json_str = self._extract_json(response_text)
            critique_result = json.loads(json_str)
            logger.info(
                "Grok critique: overall_score=%s, recommendation=%s",
                critique_result.get("overall_score"),
                critique_result.get("recommendation"),
            )
            return critique_result
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning("Failed to parse Grok critique JSON: %s", e)
            return {
                "overall_score": None,
                "recommendation": "revise",
                "raw_response": response_text,
                "parse_error": str(e),
            }

    def review_literature(
        self,
        pipeline_name: str,
        result_data: dict,
        max_tokens: int = 4096,
    ) -> dict:
        """
        Review a novel result against the literature.

        Returns parsed JSON literature review, or dict with error key.
        """
        logger.info("Requesting Grok literature review for %s", pipeline_name)

        user_content = (
            f"A computational biology pipeline ({pipeline_name}) produced this novel result.\n"
            f"Please search recent literature for corroborating or contradicting evidence.\n\n"
            f"Result:\n```json\n{json.dumps(result_data, indent=2, default=str)}\n```\n"
        )

        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.0,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": self.LITERATURE_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )

        if _log_llm_usage and response.usage:
            _log_llm_usage(
                model=self.model,
                usage={"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens},
                agent_name="grok_literature",
            )

        response_text = response.choices[0].message.content

        try:
            json_str = self._extract_json(response_text)
            review = json.loads(json_str)
            logger.info(
                "Grok review: lit_score=%s, confidence=%s",
                review.get("literature_score"),
                review.get("confidence_in_finding"),
            )
            return review
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning("Failed to parse Grok review JSON: %s", e)
            return {
                "literature_score": None,
                "confidence_in_finding": "low",
                "raw_response": response_text,
                "parse_error": str(e),
            }

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from a response, stripping code fences and control characters."""
        if "```json" in text:
            json_str = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            json_str = text.split("```")[1].split("```")[0]
        else:
            json_str = text
        # Strip control characters (except whitespace) that cause parse failures
        json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str)
        return json_str


class GrokResearcher:
    """
    Proactive researcher mode — Grok searches for new datasets and sources.
    Uses the xAI API with tool-use for web search capabilities.
    """

    SYSTEM_PROMPT = (
        "You are a computational biology researcher. Search for new datasets, "
        "preprints, and data sources relevant to cancer genomics, rare disease, "
        "and drug discovery. Focus on:\n"
        "- bioRxiv / medRxiv preprints\n"
        "- New GEO accessions\n"
        "- ClinicalTrials.gov updates\n"
        "- UniProt / EBI releases\n"
        "- PubChem new compound data\n\n"
        "For each discovery, return JSON:\n"
        "{\n"
        '  "discoveries": [\n'
        '    {"url": "...", "domain": "...", "title": "...", "relevance": "...", "notes": "..."}\n'
        "  ]\n"
        "}"
    )

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "grok-4.20-non-reasoning",
        base_url: str = "https://api.x.ai/v1",
    ):
        self.api_key = api_key or os.environ.get("XAI_API_KEY", "")
        self.model = model
        self.client = openai.OpenAI(api_key=self.api_key, base_url=base_url)

    def search_new_datasets(self, domain: str, max_tokens: int = 4096) -> list[dict]:
        """Search for new datasets relevant to a research domain."""
        logger.info("Grok searching for new datasets in domain: %s", domain)

        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.3,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": f"Search for new datasets and papers in: {domain}"},
            ],
        )

        if _log_llm_usage and response.usage:
            _log_llm_usage(
                model=self.model,
                usage={"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens},
                agent_name="grok_researcher",
            )

        response_text = response.choices[0].message.content

        try:
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0]
            else:
                json_str = response_text

            data = json.loads(json_str)
            discoveries = data.get("discoveries", [])
            logger.info("Grok found %d new sources for %s", len(discoveries), domain)
            return discoveries
        except (json.JSONDecodeError, IndexError):
            logger.warning("Failed to parse Grok discoveries")
            return []

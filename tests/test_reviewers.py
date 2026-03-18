"""Tests for Claude and Grok reviewer wrappers."""

import importlib
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path for reviewer package
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Force reimport of reviewer package from our project directory
if "reviewer" in sys.modules:
    del sys.modules["reviewer"]
if "reviewer.claude_reviewer" in sys.modules:
    del sys.modules["reviewer.claude_reviewer"]
if "reviewer.grok_reviewer" in sys.modules:
    del sys.modules["reviewer.grok_reviewer"]


class TestClaudeReviewer:
    def test_critique(self):
        import reviewer.claude_reviewer as claude_mod

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(claude_mod, "anthropic") as mock_anthropic:
                mock_client = MagicMock()
                mock_anthropic.Anthropic.return_value = mock_client

                critique_json = {
                    "overall_score": 8.0,
                    "scientific_logic": {"score": 8, "comments": "solid"},
                    "statistical_validity": {"score": 7, "comments": "ok"},
                    "interpretive_accuracy": {"score": 9, "comments": "good"},
                    "reproducibility": {"score": 8, "comments": "yes"},
                    "novelty_assessment": {"is_novel": True, "comments": "new"},
                    "recommendation": "publish",
                }
                mock_client.messages.create.return_value = MagicMock(
                    content=[MagicMock(text=json.dumps(critique_json))]
                )

                reviewer = claude_mod.ClaudeReviewer()
                result = reviewer.critique(
                    pipeline_name="neoantigen",
                    result_data={"findings": "5 novel neoantigens identified"},
                )

                assert result["recommendation"] == "publish"
                assert result["overall_score"] == 8.0


class TestGrokReviewer:
    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_review_literature(self, MockOpenAI):
        from reviewer.grok_reviewer import GrokReviewer

        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client

        review_json = {
            "corroborating": [{"title": "Study A", "source": "Nature", "summary": "confirms"}],
            "contradicting": [],
            "related_work": [],
            "literature_score": 8,
            "confidence_in_finding": "high",
            "summary": "Well supported",
        }
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps(review_json)))]
        )

        reviewer = GrokReviewer()
        result = reviewer.review_literature(
            pipeline_name="neoantigen",
            result_data={"findings": "Novel neoantigen"},
        )

        assert result["literature_score"] == 8
        assert result["confidence_in_finding"] == "high"

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_researcher(self, MockOpenAI):
        from reviewer.grok_reviewer import GrokResearcher

        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client

        research_json = {
            "discoveries": [
                {"url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
                 "domain": "GEO", "title": "BRCA1 expression",
                 "relevance": "high", "notes": "New dataset"}
            ],
        }
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps(research_json)))]
        )

        researcher = GrokResearcher()
        result = researcher.search_new_datasets("BRCA1 breast cancer")

        assert len(result) >= 1
        assert result[0]["domain"] == "GEO"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

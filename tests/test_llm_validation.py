"""LLM validation tests for Grok (scientific critic) and Gemini (coordinator).

Phases 1-4 of the LLM Validation Test Suite plan:
  - Phase 1: Grok response parsing edge cases (mocked)
  - Phase 2: Gemini coordinator prompt validation (mocked)
  - Phase 3: Pipeline integration — post_execute flow (mocked)
  - Phase 4: Live API integration (@integration, costs tokens)
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_openai_response(content: str):
    """Build a mock OpenAI chat completion response with the given content."""
    return MagicMock(
        choices=[MagicMock(message=MagicMock(content=content))]
    )


VALID_CRITIQUE = {
    "overall_score": 8.5,
    "scientific_logic": {"score": 9, "comments": "Solid methodology"},
    "statistical_validity": {"score": 8, "comments": "Appropriate tests"},
    "interpretive_accuracy": {"score": 8, "comments": "Sound conclusions"},
    "reproducibility": {"score": 9, "comments": "Well documented"},
    "novelty_assessment": {"is_novel": True, "comments": "New finding"},
    "recommendation": "publish",
    "revision_notes": "None needed",
}

VALID_LITERATURE = {
    "corroborating": [{"title": "Study A", "source": "Nature", "summary": "confirms"}],
    "contradicting": [],
    "related_work": [{"title": "Study B", "source": "bioRxiv", "relevance": "related"}],
    "literature_score": 7,
    "confidence_in_finding": "high",
    "summary": "Well supported by existing literature",
}

SAMPLE_RESULT = {"findings": "5 novel neoantigens identified", "confidence_score": 0.85}


# ===========================================================================
# Phase 1: Grok Response Parsing Tests
# ===========================================================================


class TestGrokCritiqueResponseParsing:
    """Validate JSON extraction from various Grok response formats."""

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_bare_json(self, MockOpenAI):
        from reviewer.grok_reviewer import GrokReviewer

        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(json.dumps(VALID_CRITIQUE)))
            ))
        )
        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        assert result["overall_score"] == 8.5
        assert result["recommendation"] == "publish"

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_markdown_fenced_json(self, MockOpenAI):
        fenced = f"Here is my critique:\n```json\n{json.dumps(VALID_CRITIQUE)}\n```\nEnd."
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(fenced))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        assert result["overall_score"] == 8.5

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_generic_code_fence(self, MockOpenAI):
        fenced = f"```\n{json.dumps(VALID_CRITIQUE)}\n```"
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(fenced))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        assert result["overall_score"] == 8.5

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_truncated_json_returns_fallback(self, MockOpenAI):
        truncated = '{"overall_score": 7, "recommendation": "publish", "scientific_logic":'
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(truncated))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        assert result["overall_score"] is None
        assert result["recommendation"] == "revise"
        assert "parse_error" in result
        assert "raw_response" in result

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_empty_string_returns_fallback(self, MockOpenAI):
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(""))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        assert result["overall_score"] is None
        assert result["recommendation"] == "revise"
        assert "parse_error" in result

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_whitespace_only_returns_fallback(self, MockOpenAI):
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response("   \n\t  "))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        assert result["overall_score"] is None
        assert "parse_error" in result

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_html_garbage_returns_fallback(self, MockOpenAI):
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response("<html><body>Error 500</body></html>"))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        assert result["overall_score"] is None
        assert "parse_error" in result

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_multiple_code_blocks_takes_first(self, MockOpenAI):
        multi = (
            "```json\n" + json.dumps(VALID_CRITIQUE) + "\n```\n"
            "Here is another block:\n"
            '```json\n{"overall_score": 1}\n```'
        )
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(multi))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        assert result["overall_score"] == 8.5  # first block wins

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_missing_overall_score_still_parses(self, MockOpenAI):
        no_score = {"recommendation": "revise", "scientific_logic": {"score": 5, "comments": "ok"}}
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(json.dumps(no_score)))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        # Valid JSON → parsed (not fallback), but overall_score missing
        assert result.get("overall_score") is None
        assert result["recommendation"] == "revise"
        assert "parse_error" not in result  # it parsed fine, just missing field

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_string_score_parses_as_is(self, MockOpenAI):
        """Grok might return 'very good' instead of a number for overall_score."""
        bad = {**VALID_CRITIQUE, "overall_score": "very good"}
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(json.dumps(bad)))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        # JSON parses fine, but overall_score is a string — downstream must handle
        assert result["overall_score"] == "very good"

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_negative_score_parses(self, MockOpenAI):
        bad = {**VALID_CRITIQUE, "overall_score": -1}
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(json.dumps(bad)))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        assert result["overall_score"] == -1  # parsed, not validated

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_score_over_10_parses(self, MockOpenAI):
        bad = {**VALID_CRITIQUE, "overall_score": 42}
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(json.dumps(bad)))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        assert result["overall_score"] == 42  # parsed, not validated


class TestGrokLiteratureResponseParsing:
    """Validate JSON extraction for literature review responses."""

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_valid_literature_review(self, MockOpenAI):
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(json.dumps(VALID_LITERATURE)))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().review_literature("test", SAMPLE_RESULT)
        assert result["literature_score"] == 7
        assert result["confidence_in_finding"] == "high"
        assert len(result["corroborating"]) == 1

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_markdown_fenced_literature(self, MockOpenAI):
        fenced = f"```json\n{json.dumps(VALID_LITERATURE)}\n```"
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(fenced))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().review_literature("test", SAMPLE_RESULT)
        assert result["literature_score"] == 7

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_truncated_literature_fallback(self, MockOpenAI):
        truncated = '{"literature_score": 5, "corroborating":'
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(truncated))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().review_literature("test", SAMPLE_RESULT)
        assert result["literature_score"] is None
        assert result["confidence_in_finding"] == "low"
        assert "parse_error" in result

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_empty_response_literature_fallback(self, MockOpenAI):
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(""))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().review_literature("test", SAMPLE_RESULT)
        assert result["literature_score"] is None
        assert result["confidence_in_finding"] == "low"
        assert "parse_error" in result

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_missing_confidence_field(self, MockOpenAI):
        no_conf = {"literature_score": 6, "corroborating": [], "contradicting": [],
                    "related_work": [], "summary": "ok"}
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(json.dumps(no_conf)))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().review_literature("test", SAMPLE_RESULT)
        assert result["literature_score"] == 6
        assert result.get("confidence_in_finding") is None  # valid parse, field missing


class TestGrokFallbackBehavior:
    """Verify the fallback dict structure on parse failures."""

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_critique_fallback_has_required_keys(self, MockOpenAI):
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response("not json at all"))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        assert result["overall_score"] is None
        assert result["recommendation"] == "revise"
        assert isinstance(result["parse_error"], str)
        assert isinstance(result["raw_response"], str)

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_literature_fallback_has_required_keys(self, MockOpenAI):
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response("not json"))
            ))
        )
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().review_literature("test", SAMPLE_RESULT)
        assert result["literature_score"] is None
        assert result["confidence_in_finding"] == "low"
        assert isinstance(result["parse_error"], str)
        assert isinstance(result["raw_response"], str)

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_critique_fallback_recommendation_is_always_revise(self, MockOpenAI):
        """A parse failure should never return 'publish' — it defaults to 'revise'."""
        for bad_content in ["", "   ", "<error>", "{broken", "```json\n{broken\n```"]:
            MockOpenAI.return_value = MagicMock(
                chat=MagicMock(completions=MagicMock(
                    create=MagicMock(return_value=_mock_openai_response(bad_content))
                ))
            )
            from reviewer.grok_reviewer import GrokReviewer

            result = GrokReviewer().critique("test", SAMPLE_RESULT)
            assert result["recommendation"] == "revise", f"Failed for content: {bad_content!r}"


class TestGrokExtractJson:
    """Test the _extract_json static method including control character stripping."""

    def test_strips_control_characters(self):
        from reviewer.grok_reviewer import GrokReviewer

        # Simulate control char in JSON (the real bug from run 288)
        dirty = '{"overall_score": 7, "recommendation": "publish\x0b"}'
        cleaned = GrokReviewer._extract_json(dirty)
        parsed = json.loads(cleaned)
        assert parsed["overall_score"] == 7

    def test_preserves_normal_whitespace(self):
        from reviewer.grok_reviewer import GrokReviewer

        text = '{\n  "overall_score": 8,\n  "recommendation": "publish"\n}'
        cleaned = GrokReviewer._extract_json(text)
        parsed = json.loads(cleaned)
        assert parsed["overall_score"] == 8

    def test_strips_null_bytes(self):
        from reviewer.grok_reviewer import GrokReviewer

        text = '{"overall_score": 5\x00}'
        cleaned = GrokReviewer._extract_json(text)
        parsed = json.loads(cleaned)
        assert parsed["overall_score"] == 5

    def test_extracts_from_markdown_fence(self):
        from reviewer.grok_reviewer import GrokReviewer

        text = 'Here:\n```json\n{"score": 9}\n```\nDone.'
        cleaned = GrokReviewer._extract_json(text)
        parsed = json.loads(cleaned)
        assert parsed["score"] == 9

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch("reviewer.grok_reviewer.openai.OpenAI")
    def test_control_char_in_response_parses_successfully(self, MockOpenAI):
        """End-to-end: control characters in Grok response don't cause parse failure."""
        from reviewer.grok_reviewer import GrokReviewer

        # This would have failed before the fix (the real bug)
        dirty_json = json.dumps(VALID_CRITIQUE).replace('"publish"', '"publish\x1b"')
        MockOpenAI.return_value = MagicMock(
            chat=MagicMock(completions=MagicMock(
                create=MagicMock(return_value=_mock_openai_response(dirty_json))
            ))
        )
        result = GrokReviewer().critique("test", SAMPLE_RESULT)
        assert result["overall_score"] == 8.5
        assert "parse_error" not in result


class TestGrokPromptContent:
    """Verify the prompt changes — recommendation criteria and literature requirements."""

    def test_critique_prompt_defines_publish_criteria(self):
        from reviewer.grok_reviewer import GrokReviewer

        prompt = GrokReviewer.CRITIQUE_PROMPT
        assert "publish" in prompt.lower()
        assert "overall_score >= 7" in prompt

    def test_critique_prompt_defines_revise_criteria(self):
        from reviewer.grok_reviewer import GrokReviewer

        prompt = GrokReviewer.CRITIQUE_PROMPT
        assert "revise" in prompt.lower()
        assert "4-7" in prompt

    def test_critique_prompt_defines_reject_criteria(self):
        from reviewer.grok_reviewer import GrokReviewer

        prompt = GrokReviewer.CRITIQUE_PROMPT
        assert "reject" in prompt.lower()
        assert "< 4" in prompt

    def test_literature_prompt_requires_score(self):
        from reviewer.grok_reviewer import GrokReviewer

        prompt = GrokReviewer.LITERATURE_PROMPT
        assert "MUST include" in prompt
        assert "literature_score" in prompt

    def test_literature_prompt_requires_confidence(self):
        from reviewer.grok_reviewer import GrokReviewer

        prompt = GrokReviewer.LITERATURE_PROMPT
        assert "confidence_in_finding" in prompt


# ===========================================================================
# Phase 2: Gemini Coordinator Prompt Tests
# ===========================================================================


class TestGeminiCoordinatorPrompts:
    """Verify coordinator and specialist prompts contain required elements."""

    def test_coordinator_prompt_routes_all_specialists(self):
        from agentiq_labclaw.nat_specialists import COORDINATOR_SYSTEM_PROMPT  # noqa: F811

        # The coordinator must know about all three specialist agents
        for agent in ["cancer_agent", "rare_disease_agent", "drug_response_agent"]:
            assert agent in COORDINATOR_SYSTEM_PROMPT, f"Missing {agent} in coordinator prompt"

    def test_coordinator_prompt_has_fabrication_guard(self):
        from agentiq_labclaw.nat_specialists import COORDINATOR_SYSTEM_PROMPT

        assert "fabricat" in COORDINATOR_SYSTEM_PROMPT.lower()

    def test_cancer_prompt_has_fabrication_guard(self):
        from agentiq_labclaw.nat_specialists import CANCER_SYSTEM_PROMPT

        assert "never fabricate" in CANCER_SYSTEM_PROMPT.lower()

    def test_rare_disease_prompt_has_fabrication_guard(self):
        from agentiq_labclaw.nat_specialists import RARE_DISEASE_SYSTEM_PROMPT

        assert "never fabricate" in RARE_DISEASE_SYSTEM_PROMPT.lower()

    def test_drug_response_prompt_has_fabrication_guard(self):
        from agentiq_labclaw.nat_specialists import DRUG_RESPONSE_SYSTEM_PROMPT

        assert "never fabricate" in DRUG_RESPONSE_SYSTEM_PROMPT.lower()

    def test_llm_rate_cards_include_required_models(self):
        from agentiq_labclaw.nat_specialists import LLM_RATE_CARDS

        assert "grok-3" in LLM_RATE_CARDS
        # At least one gemini model
        gemini_models = [k for k in LLM_RATE_CARDS if "gemini" in k.lower()]
        assert len(gemini_models) >= 1

    def test_llm_rate_cards_have_valid_structure(self):
        from agentiq_labclaw.nat_specialists import LLM_RATE_CARDS

        for model_name, card in LLM_RATE_CARDS.items():
            assert "provider" in card, f"{model_name} missing provider"
            assert "input" in card, f"{model_name} missing input rate"
            assert "output" in card, f"{model_name} missing output rate"
            assert card["input"] >= 0, f"{model_name} negative input rate"
            assert card["output"] >= 0, f"{model_name} negative output rate"


# ===========================================================================
# Phase 3: Pipeline Integration Tests (mocked)
# ===========================================================================


class TestGrokCritiquePipeline:
    """Test the full post_execute() orchestration flow with mocked dependencies."""

    def _make_mock_result(self, confidence=0.85, critique_required=True, novel=False, synthetic=False):
        """Build a mock Pydantic BaseModel result."""
        from pydantic import BaseModel

        mock = MagicMock(spec=BaseModel)
        mock.model_dump.return_value = {
            "findings": "test finding",
            "confidence_score": confidence,
            "critique_required": critique_required,
            "novel": novel,
            "synthetic": synthetic,
        }
        return mock

    def _mock_modules(self, extra=None):
        """Build sys.modules mock dict for post_execute dependencies."""
        mock_grok_module = MagicMock()
        self._mock_grok_cls = MagicMock()
        mock_grok_module.GrokReviewer = self._mock_grok_cls

        mods = {
            "reviewer": MagicMock(),
            "reviewer.grok_reviewer": mock_grok_module,
            "agentiq_labclaw.db.pipeline_runs": MagicMock(
                start_pipeline=MagicMock(return_value=1),
                complete_pipeline=MagicMock(),
            ),
            "agentiq_labclaw.db.experiment_results": MagicMock(store_result=MagicMock()),
            "agentiq_labclaw.db.critique_log": MagicMock(log_critique=MagicMock()),
            "agentiq_labclaw.guardrails.output_validator": MagicMock(
                validate_output=MagicMock(return_value=(True, None)),
            ),
            "agentiq_labclaw.guardrails.safety_check": MagicMock(
                safety_check=MagicMock(return_value=(True, None)),
            ),
        }
        if extra:
            mods.update(extra)
        return mods

    @pytest.mark.asyncio
    @patch("agentiq_labclaw.orchestrator._guardrails_enabled", return_value=True)
    @patch("agentiq_labclaw.orchestrator._publisher_enabled", return_value=False)
    async def test_valid_critique_completes_pipeline(self, mock_pub, mock_guard):
        from agentiq_labclaw.orchestrator import post_execute

        mods = self._mock_modules()
        with patch("agentiq_labclaw.orchestrator._get_config", return_value={}):
            with patch.dict("sys.modules", mods):
                self._mock_grok_cls.return_value.critique.return_value = VALID_CRITIQUE

                result = await post_execute("neoantigen", self._make_mock_result(), run_id=1)

                orch = result["orchestration"]
                assert len(orch["critiques"]) >= 1
                assert orch["critiques"][0]["critique"]["overall_score"] == 8.5

    @pytest.mark.asyncio
    @patch("agentiq_labclaw.orchestrator._guardrails_enabled", return_value=True)
    @patch("agentiq_labclaw.orchestrator._publisher_enabled", return_value=False)
    async def test_parse_failure_still_logs_critique(self, mock_pub, mock_guard):
        from agentiq_labclaw.orchestrator import post_execute

        parse_failure = {
            "overall_score": None,
            "recommendation": "revise",
            "raw_response": "garbled",
            "parse_error": "Expecting value: line 1 column 1",
        }

        mods = self._mock_modules()
        with patch("agentiq_labclaw.orchestrator._get_config", return_value={}):
            with patch.dict("sys.modules", mods):
                self._mock_grok_cls.return_value.critique.return_value = parse_failure

                result = await post_execute("neoantigen", self._make_mock_result(), run_id=1)

                orch = result["orchestration"]
                assert len(orch["critiques"]) >= 1
                critique = orch["critiques"][0]["critique"]
                assert critique["overall_score"] is None
                assert "parse_error" in critique

    @pytest.mark.asyncio
    @patch("agentiq_labclaw.orchestrator._guardrails_enabled", return_value=True)
    @patch("agentiq_labclaw.orchestrator._publisher_enabled", return_value=False)
    async def test_grok_api_timeout_degrades_gracefully(self, mock_pub, mock_guard):
        from agentiq_labclaw.orchestrator import post_execute

        mods = self._mock_modules()
        with patch("agentiq_labclaw.orchestrator._get_config", return_value={}):
            with patch.dict("sys.modules", mods):
                self._mock_grok_cls.return_value.critique.side_effect = Exception("Connection timeout")

                result = await post_execute("neoantigen", self._make_mock_result(), run_id=1)

                orch = result["orchestration"]
                # critique should have an error entry, not crash the pipeline
                assert any("error" in c for c in orch["critiques"])

    @pytest.mark.asyncio
    @patch("agentiq_labclaw.orchestrator._guardrails_enabled", return_value=True)
    @patch("agentiq_labclaw.orchestrator._publisher_enabled", return_value=False)
    async def test_safety_blocks_when_critique_required_but_missing(self, mock_pub, mock_guard):
        from agentiq_labclaw.orchestrator import post_execute

        mods = self._mock_modules()
        # Remove safety_check mock so the real one runs and blocks
        del mods["agentiq_labclaw.guardrails.safety_check"]
        with patch("agentiq_labclaw.orchestrator._get_config", return_value={}):
            with patch.dict("sys.modules", mods):
                self._mock_grok_cls.return_value.critique.side_effect = Exception("API down")

                result = await post_execute("neoantigen", self._make_mock_result(critique_required=True), run_id=1)

                orch = result["orchestration"]
                # critique_completed = False because API errored
                # safety_check should block since critique_required=True
                assert orch["safety"]["safe"] is False
                assert "critique" in orch["safety"]["reason"].lower()

    @pytest.mark.asyncio
    @patch("agentiq_labclaw.orchestrator._guardrails_enabled", return_value=True)
    @patch("agentiq_labclaw.orchestrator._publisher_enabled", return_value=False)
    async def test_synthetic_result_skips_review(self, mock_pub, mock_guard):
        from agentiq_labclaw.orchestrator import post_execute

        mods = self._mock_modules()
        with patch("agentiq_labclaw.orchestrator._get_config", return_value={}):
            with patch.dict("sys.modules", mods):
                mock_result = self._make_mock_result(synthetic=True, critique_required=True)
                result = await post_execute("neoantigen", mock_result, run_id=1)

                orch = result["orchestration"]
                # Synthetic results skip critique entirely
                assert len(orch["critiques"]) == 0


class TestSafetyCheckUnit:
    """Direct unit tests for safety_check function."""

    def _make_output(self, confidence=0.85, critique_required=False):
        mock = MagicMock()
        mock.model_dump.return_value = {
            "confidence_score": confidence,
            "critique_required": critique_required,
        }
        return mock

    def test_passes_with_valid_inputs(self):
        from agentiq_labclaw.guardrails.safety_check import safety_check

        is_safe, reason = safety_check(self._make_output(), agent_run_id=1, critique_completed=True)
        assert is_safe is True
        assert reason is None

    def test_blocks_no_run_id(self):
        from agentiq_labclaw.guardrails.safety_check import safety_check

        is_safe, reason = safety_check(self._make_output(), agent_run_id=None)
        assert is_safe is False
        assert "agent_run_id" in reason

    def test_blocks_low_confidence(self):
        from agentiq_labclaw.guardrails.safety_check import safety_check

        is_safe, reason = safety_check(self._make_output(confidence=0.05), agent_run_id=1)
        assert is_safe is False
        assert "Confidence" in reason

    def test_blocks_critique_required_not_completed(self):
        from agentiq_labclaw.guardrails.safety_check import safety_check

        is_safe, reason = safety_check(
            self._make_output(critique_required=True), agent_run_id=1, critique_completed=False
        )
        assert is_safe is False
        assert "critique" in reason.lower()

    def test_passes_critique_required_and_completed(self):
        from agentiq_labclaw.guardrails.safety_check import safety_check

        is_safe, reason = safety_check(
            self._make_output(critique_required=True), agent_run_id=1, critique_completed=True
        )
        assert is_safe is True

    def test_passes_no_confidence_field(self):
        """If there's no confidence_score, safety check should not block on it."""
        from agentiq_labclaw.guardrails.safety_check import safety_check

        mock = MagicMock()
        mock.model_dump.return_value = {}  # no confidence_score field
        is_safe, reason = safety_check(mock, agent_run_id=1)
        assert is_safe is True

    def test_minimum_confidence_constant(self):
        from agentiq_labclaw.guardrails.safety_check import MINIMUM_CONFIDENCE

        assert MINIMUM_CONFIDENCE == 0.1


# ===========================================================================
# Phase 4: Live API Integration Tests (@integration, costs tokens)
# ===========================================================================


@pytest.mark.integration
class TestGrokLiveAPI:
    """Live Grok API tests — require XAI_API_KEY, cost tokens."""

    @pytest.fixture(autouse=True)
    def _require_api_key(self):
        if not os.environ.get("XAI_API_KEY"):
            pytest.skip("XAI_API_KEY not set")

    def test_api_connectivity(self):
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique("test_connectivity", {"test": "ping"})
        assert result is not None
        assert isinstance(result, dict)

    def test_critique_returns_numeric_score(self):
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique(
            "neoantigen",
            {"findings": "3 neoantigens predicted", "confidence_score": 0.8},
        )
        if "parse_error" not in result:
            assert isinstance(result["overall_score"], (int, float))
            assert 0 <= result["overall_score"] <= 10

    def test_critique_returns_valid_recommendation(self):
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique(
            "neoantigen",
            {"findings": "3 neoantigens predicted", "confidence_score": 0.8},
        )
        if "parse_error" not in result:
            assert result["recommendation"] in ("publish", "revise", "reject")

    def test_literature_review_returns_valid_schema(self):
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().review_literature(
            "neoantigen",
            {"findings": "Novel KRAS G12D neoantigen", "confidence_score": 0.9},
        )
        if "parse_error" not in result:
            assert isinstance(result.get("literature_score"), (int, float))
            assert result.get("confidence_in_finding") in ("high", "medium", "low")

    def test_response_is_not_garbled(self):
        from reviewer.grok_reviewer import GrokReviewer

        result = GrokReviewer().critique(
            "test_garble_check",
            {"findings": "simple test"},
        )
        raw = result.get("raw_response", json.dumps(result))
        # No terminal escape sequences
        assert "\x1b[" not in raw
        assert "\x00" not in raw


@pytest.mark.integration
class TestGeminiLiveAPI:
    """Live Gemini API tests — require GENAI_API_KEY, cost tokens."""

    @pytest.fixture(autouse=True)
    def _require_api_key(self):
        if not os.environ.get("GENAI_API_KEY"):
            pytest.skip("GENAI_API_KEY not set")

    def test_api_connectivity(self):
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model="gemini-2.5-flash-lite",
            api_key=os.environ["GENAI_API_KEY"],
            temperature=0.0,
        )
        response = llm.invoke("Reply with the word 'hello' and nothing else.")
        assert response.content.strip().lower().startswith("hello")

    def test_response_is_not_empty(self):
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model="gemini-2.5-flash-lite",
            api_key=os.environ["GENAI_API_KEY"],
            temperature=0.0,
        )
        response = llm.invoke("What is 2+2?")
        assert len(response.content.strip()) > 0

    def test_response_is_not_garbled(self):
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model="gemini-2.5-flash-lite",
            api_key=os.environ["GENAI_API_KEY"],
            temperature=0.0,
        )
        response = llm.invoke("Say 'test response'")
        assert "\x1b[" not in response.content
        assert "\x00" not in response.content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

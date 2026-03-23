"""End-to-end integration tests for the LabClaw hierarchical agent system."""

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestSkillRegistry:
    """Verify all skills are properly registered."""

    def test_all_skills_registered(self):
        from agentiq_labclaw.skills import (  # noqa: F401
            docking,
            grok_research,
            neoantigen,
            qsar,
            register_source,
            report_generator,
            sequencing_qc,
            structure,
            variant_pathogenicity,
        )
        from agentiq_labclaw.base import list_skills

        skills = list_skills()
        expected = [
            "neoantigen_prediction",
            "structure_prediction",
            "molecular_docking",
            "qsar",
            "variant_pathogenicity",
            "sequencing_qc",
            "register_source",
            "report_generator",
            "grok_research",
        ]
        for name in expected:
            assert name in skills, f"Skill {name} not registered"

    def test_skill_schemas_defined(self):
        from agentiq_labclaw.skills import (  # noqa: F401
            docking,
            grok_research,
            neoantigen,
            qsar,
            register_source,
            report_generator,
            sequencing_qc,
            structure,
            variant_pathogenicity,
        )
        from agentiq_labclaw.base import get_skill

        for name in ["neoantigen_prediction", "structure_prediction", "molecular_docking",
                      "qsar", "variant_pathogenicity", "sequencing_qc", "register_source",
                      "report_generator", "grok_research"]:
            cls = get_skill(name)
            assert cls.input_schema is not None, f"{name} missing input_schema"
            assert cls.output_schema is not None, f"{name} missing output_schema"


class TestNATPluginImports:
    """Test that the NAT plugin correctly imports all components."""

    def test_specialist_module_imported(self):
        import agentiq_labclaw.nat_specialists as ns

        assert hasattr(ns, "SpecialistAgentConfig")
        assert hasattr(ns, "HierarchicalCoordinatorConfig")
        assert hasattr(ns, "specialist_agent")
        assert hasattr(ns, "hierarchical_coordinator")

    def test_orchestrator_importable(self):
        from agentiq_labclaw.orchestrator import post_execute

        assert callable(post_execute)


class TestGuardrailsIntegration:
    """Test the guardrails modules are properly wired."""

    def test_output_validator(self):
        from pydantic import BaseModel

        from agentiq_labclaw.guardrails.output_validator import validate_output

        class TestSchema(BaseModel):
            value: int

        valid = TestSchema(value=42)
        is_valid, error = validate_output(valid, TestSchema)
        assert is_valid is True
        assert error is None

    def test_safety_check_blocks_no_run_id(self):
        from pydantic import BaseModel

        from agentiq_labclaw.guardrails.safety_check import safety_check

        class TestOutput(BaseModel):
            confidence_score: float = 0.9
            critique_required: bool = False

        output = TestOutput()
        is_safe, reason = safety_check(output, agent_run_id=None)
        assert is_safe is False
        assert "agent_run_id" in reason

    def test_safety_check_blocks_low_confidence(self):
        from pydantic import BaseModel

        from agentiq_labclaw.guardrails.safety_check import safety_check

        class TestOutput(BaseModel):
            confidence_score: float = 0.01

        output = TestOutput()
        is_safe, reason = safety_check(output, agent_run_id=1)
        assert is_safe is False
        assert "Confidence" in reason

    def test_safety_check_passes(self):
        from pydantic import BaseModel

        from agentiq_labclaw.guardrails.safety_check import safety_check

        class TestOutput(BaseModel):
            confidence_score: float = 0.9

        output = TestOutput()
        is_safe, reason = safety_check(output, agent_run_id=1)
        assert is_safe is True


class TestPublishersIntegration:
    """Test publisher classes are importable and constructable."""

    def test_pdf_publisher(self, tmp_path):
        from agentiq_labclaw.publishers.pdf_publisher import PDFPublisher

        pub = PDFPublisher(output_dir=str(tmp_path))
        report_path = pub.generate_report(
            title="Test Report",
            sections=[{"heading": "Summary", "content": "This is a test."}],
        )
        assert os.path.exists(report_path)
        assert report_path.endswith(".pdf")


class TestReviewersIntegration:
    """Test reviewer classes work with mocked APIs."""

    def test_claude_reviewer_init(self):
        from reviewer.claude_reviewer import ClaudeReviewer

        with patch("reviewer.claude_reviewer.anthropic.Anthropic"):
            reviewer = ClaudeReviewer(api_key="test-key")
            assert reviewer.model == "claude-opus-4-6"

    def test_grok_reviewer_init(self):
        from reviewer.grok_reviewer import GrokReviewer

        with patch("reviewer.grok_reviewer.openai.OpenAI"):
            reviewer = GrokReviewer(api_key="test-key")
            assert reviewer.model == "grok-3"

    def test_grok_researcher_init(self):
        from reviewer.grok_reviewer import GrokResearcher

        with patch("reviewer.grok_reviewer.openai.OpenAI"):
            researcher = GrokResearcher(api_key="test-key")
            assert researcher.model == "grok-3"


class TestDBInterfaces:
    """Test DB interface modules are importable with correct signatures."""

    def test_critique_log_interface(self):
        from agentiq_labclaw.db.critique_log import log_critique, get_critiques_for_run

        assert callable(log_critique)
        assert callable(get_critiques_for_run)

    def test_agent_runs_interface(self):
        from agentiq_labclaw.db.agent_runs import start_run, complete_run, get_run

        assert callable(start_run)
        assert callable(complete_run)
        assert callable(get_run)

    def test_experiment_results_interface(self):
        from agentiq_labclaw.db.experiment_results import store_result, check_novelty

        assert callable(store_result)
        assert callable(check_novelty)

    def test_pipeline_runs_interface(self):
        from agentiq_labclaw.db.pipeline_runs import start_pipeline, complete_pipeline

        assert callable(start_pipeline)
        assert callable(complete_pipeline)


class TestFullPipeline:
    """Test the complete skill → orchestrator → output pipeline with mocks."""

    @pytest.mark.asyncio
    async def test_neoantigen_pipeline_e2e(self):
        """Simulate a neoantigen prediction flowing through the full orchestrator."""
        from pydantic import BaseModel
        from agentiq_labclaw.orchestrator import post_execute, _get_config

        if hasattr(_get_config, '_cache'):
            del _get_config._cache

        class NeoantigenResult(BaseModel):
            candidates: list = [{"peptide": "MVLSPADKTNV", "affinity_nm": 45.2, "hla": "HLA-A*02:01"}]
            novel: bool = True
            critique_required: bool = True
            confidence_score: float = 0.92

        result = NeoantigenResult()

        mock_critique = {"overall_score": 9, "recommendation": "publish"}
        mock_lit = {"literature_score": 8, "confidence_in_finding": "high"}

        with patch("reviewer.grok_reviewer.GrokReviewer.critique", return_value=mock_critique), \
             patch("reviewer.grok_reviewer.GrokReviewer.review_literature", return_value=mock_lit), \
             patch("agentiq_labclaw.db.critique_log.log_critique", return_value=1), \
             patch("agentiq_labclaw.db.experiment_results.store_result", return_value=1), \
             patch("agentiq_labclaw.guardrails.novelty_filter.db_check_novelty", return_value=True), \
             patch("agentiq_labclaw.guardrails.safety_check.safety_check", return_value=(True, None)), \
             patch("agentiq_labclaw.publishers.pdf_publisher.PDFPublisher.generate_report", return_value="/tmp/neo.pdf"):

            enriched = await post_execute("neoantigen_prediction", result, run_id=1)

        # Verify full pipeline executed
        orch = enriched["orchestration"]
        assert orch["novelty"]["is_novel"] is True
        assert len(orch["critiques"]) == 2
        assert orch["safety"]["safe"] is True
        assert any("pdf:" in p for p in orch["published"])

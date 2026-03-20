"""Tests for hierarchical multi-agent architecture routing."""

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agentiq_labclaw"))


class TestSpecialistAgentConfig:
    """Test that specialist agent configs are properly defined."""

    def test_config_registration(self):
        from agentiq_labclaw.nat_specialists import SpecialistAgentConfig

        config = SpecialistAgentConfig(
            llm_name="test_llm",
            description="Test cancer specialist",
            specialty_domain="tumor_immunology",
            system_prompt="You are a cancer agent.",
            tool_names=["neoantigen_prediction", "structure_prediction"],
        )
        assert config.specialty_domain == "tumor_immunology"
        assert len(config.tool_names) == 2
        assert config.llm_name == "test_llm"

    def test_hierarchical_coordinator_config(self):
        from agentiq_labclaw.nat_specialists import HierarchicalCoordinatorConfig

        config = HierarchicalCoordinatorConfig(
            llm_name="test_llm",
            description="Test hierarchical coordinator",
            specialist_names=["cancer_agent", "rare_disease_agent", "drug_response_agent"],
            utility_tool_names=["register_discovered_source", "report_generator"],
        )
        assert len(config.specialist_names) == 3
        assert len(config.utility_tool_names) == 2


class TestWorkflowYAML:
    """Test that the coordinator YAML defines the correct hierarchical structure."""

    def test_yaml_structure(self):
        import yaml

        yaml_path = os.path.join(os.path.dirname(__file__), "..", "coordinator", "labclaw_workflow.yaml")
        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        # Should have LLM config
        assert "llms" in config
        assert "coordinator_llm" in config["llms"]

        # Should have functions section with skills AND specialist agents
        functions = config["functions"]
        assert functions["neoantigen_prediction"]["_type"] == "labclaw_skill"
        assert functions["cancer_agent"]["_type"] == "specialist_agent"
        assert functions["rare_disease_agent"]["_type"] == "specialist_agent"
        assert functions["drug_response_agent"]["_type"] == "specialist_agent"

        # Specialist agents should have correct skill subsets
        cancer = functions["cancer_agent"]
        assert "neoantigen_prediction" in cancer["tool_names"]
        assert "structure_prediction" in cancer["tool_names"]
        assert "sequencing_qc" in cancer["tool_names"]
        assert "qsar" not in cancer["tool_names"]

        rare = functions["rare_disease_agent"]
        assert "variant_pathogenicity" in rare["tool_names"]
        assert "sequencing_qc" in rare["tool_names"]
        assert "molecular_docking" not in rare["tool_names"]

        drug = functions["drug_response_agent"]
        assert "qsar" in drug["tool_names"]
        assert "molecular_docking" in drug["tool_names"]
        assert "neoantigen_prediction" not in drug["tool_names"]

    def test_workflow_type_is_hierarchical(self):
        import yaml

        yaml_path = os.path.join(os.path.dirname(__file__), "..", "coordinator", "labclaw_workflow.yaml")
        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        workflow = config["workflow"]
        assert workflow["_type"] == "hierarchical_coordinator"
        assert "specialist_names" in workflow
        assert "cancer_agent" in workflow["specialist_names"]
        assert "rare_disease_agent" in workflow["specialist_names"]
        assert "drug_response_agent" in workflow["specialist_names"]

    def test_guardrails_enabled(self):
        import yaml

        yaml_path = os.path.join(os.path.dirname(__file__), "..", "coordinator", "labclaw_workflow.yaml")
        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        guardrails = config.get("guardrails", {})
        assert guardrails.get("output_validation") is True
        assert guardrails.get("novelty_filter") is True
        assert guardrails.get("safety_check") is True

    def test_publishers_enabled(self):
        import yaml

        yaml_path = os.path.join(os.path.dirname(__file__), "..", "coordinator", "labclaw_workflow.yaml")
        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        publishers = config.get("publishers", {})
        assert publishers["github"]["enabled"] is True
        assert publishers["discord"]["enabled"] is True
        assert publishers["pdf"]["enabled"] is True


class TestDomainSystemPrompts:
    """Test that domain system prompts are defined."""

    def test_prompts_exist(self):
        from agentiq_labclaw.nat_specialists import (
            CANCER_SYSTEM_PROMPT,
            COORDINATOR_SYSTEM_PROMPT,
            DRUG_RESPONSE_SYSTEM_PROMPT,
            RARE_DISEASE_SYSTEM_PROMPT,
        )

        assert "tumor immunology" in CANCER_SYSTEM_PROMPT.lower()
        assert "rare disease" in RARE_DISEASE_SYSTEM_PROMPT.lower()
        assert "drug response" in DRUG_RESPONSE_SYSTEM_PROMPT.lower()
        assert "specialist" in COORDINATOR_SYSTEM_PROMPT.lower()

    def test_specialist_prompts_in_yaml(self):
        import yaml

        yaml_path = os.path.join(os.path.dirname(__file__), "..", "coordinator", "labclaw_workflow.yaml")
        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        functions = config["functions"]
        assert "system_prompt" in functions["cancer_agent"]
        assert "system_prompt" in functions["rare_disease_agent"]
        assert "system_prompt" in functions["drug_response_agent"]


class TestGrokResearchSkill:
    """Test the Grok researcher skill registration."""

    def test_skill_registered(self):
        from agentiq_labclaw.skills import grok_research  # noqa: F401
        from agentiq_labclaw.base import get_skill

        skill_cls = get_skill("grok_research")
        assert skill_cls is not None
        assert skill_cls.name == "grok_research"

    def test_grok_research_in_yaml(self):
        import yaml

        yaml_path = os.path.join(os.path.dirname(__file__), "..", "coordinator", "labclaw_workflow.yaml")
        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        assert "grok_research" in config["functions"]
        assert config["functions"]["grok_research"]["skill_name"] == "grok_research"
        assert "grok_research" in config["workflow"]["utility_tool_names"]

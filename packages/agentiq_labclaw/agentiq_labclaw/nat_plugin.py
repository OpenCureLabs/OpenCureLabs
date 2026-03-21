"""
NAT plugin registration — bridges LabClaw skills into NeMo Agent Toolkit.

Each LabClaw skill is exposed as a NAT function type called `labclaw_skill`
with a `skill_name` parameter that selects which skill to run.

Also registers `labclaw_react` — a ReAct-style coordinator agent workflow
that uses LangGraph to route tasks through LabClaw skills.
"""

import json
import logging

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.agent import AgentBaseConfig
from nat.data_models.function import FunctionBaseConfig
from pydantic import BaseModel, Field

# Import specialist agent registrations so NAT discovers them
import agentiq_labclaw.nat_specialists  # noqa: F401
from agentiq_labclaw.base import get_skill

logger = logging.getLogger("labclaw.nat_plugin")


class LabClawSkillConfig(FunctionBaseConfig, name="labclaw_skill"):
    """NAT function config for LabClaw skills. Use `skill_name` in the workflow YAML."""

    skill_name: str = Field(description="Name of the LabClaw skill to invoke")


@register_function(config_type=LabClawSkillConfig)
async def labclaw_skill_function(config: LabClawSkillConfig, builder: Builder):
    # Eagerly import all skill modules to trigger @labclaw_skill registration
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

    skill_cls = get_skill(config.skill_name)
    skill_instance = skill_cls()

    async def _run_skill(input_json: str) -> str:
        # Normalize LLM parameter names to match Pydantic schema fields
        data = json.loads(input_json)
        schema_fields = set(skill_instance.input_schema.model_fields.keys())
        normalized = {}

        # Common LLM field name aliases → canonical schema field names
        _FIELD_ALIASES = {
            "hla": "hla_alleles",
            "hla_type": "hla_alleles",
            "hla_types": "hla_alleles",
            "alleles": "hla_alleles",
            "tumor": "tumor_type",
            "cancer_type": "tumor_type",
            "sample": "sample_id",
            "patient_id": "sample_id",
            "patient": "sample_id",
            "vcf": "vcf_path",
            "vcf_file": "vcf_path",
            "protein_sequence": "sequence",
            "seq": "sequence",
            "fasta": "sequence",
            "ligand": "ligand_smiles",
            "smiles": "ligand_smiles",
            "receptor": "receptor_pdb",
            "pdb": "receptor_pdb",
            "pdb_path": "receptor_pdb",
            "dataset": "dataset_path",
            "data_path": "dataset_path",
            "target": "target_column",
            "variant": "variant_id",
            "gene_name": "gene",
            "gene_symbol": "gene",
            "fastq": "fastq_paths",
            "fastq_files": "fastq_paths",
            "reference": "reference_genome",
            "genome": "reference_genome",
        }

        for key, val in data.items():
            if key in schema_fields:
                normalized[key] = val
            else:
                # Check explicit alias map first
                alias = _FIELD_ALIASES.get(key)
                if alias and alias in schema_fields and alias not in normalized:
                    normalized[alias] = val
                else:
                    # Fuzzy fallback: underscore-insensitive, file→path, patient→sample
                    matched = False
                    for field_name in schema_fields:
                        if field_name not in normalized and (
                            key.replace("file", "path") == field_name
                            or key.replace("patient", "sample") == field_name
                            or key.replace("_", "") == field_name.replace("_", "")
                        ):
                            normalized[field_name] = val
                            matched = True
                            break
                    if not matched:
                        normalized[key] = val  # pass through for Pydantic to validate

        input_data = skill_instance.input_schema.model_validate(normalized)
        result = skill_instance.execute(input_data)

        # Post-execution orchestration: guardrails → reviewer → publisher
        try:
            from agentiq_labclaw.orchestrator import post_execute

            # Create an agent run in DB so safety check passes
            run_id = None
            try:
                from agentiq_labclaw.db.agent_runs import complete_run, start_run

                run_id = start_run(agent_name=config.skill_name)
            except Exception as e:
                logger.debug("Could not create agent_run for orchestration: %s", e)

            enriched = await post_execute(
                skill_name=config.skill_name,
                result=result,
                run_id=run_id,
            )

            if run_id is not None:
                try:
                    complete_run(run_id, status="completed")
                except Exception:
                    logger.debug("Failed to mark run %s as completed", run_id)

            return json.dumps(enriched, default=str, indent=2)
        except Exception as e:
            logger.warning("Post-execution orchestration error (returning raw result): %s", e)
            if isinstance(result, BaseModel):
                return result.model_dump_json(indent=2)
            return json.dumps(result, default=str)

    # Build a description that includes the input schema so the LLM knows exact parameter names
    base_desc = skill_instance.description or f"LabClaw skill: {config.skill_name}"
    schema_fields = skill_instance.input_schema.model_json_schema().get("properties", {})
    if schema_fields:
        param_lines = []
        for name, info in schema_fields.items():
            ftype = info.get("type", "string")
            if "items" in info:
                ftype = f"array of {info['items'].get('type', 'string')}"
            param_lines.append(f"  - {name} ({ftype})")
        schema_hint = "Input JSON parameters:\n" + "\n".join(param_lines)
        full_desc = f"{base_desc}\n\n{schema_hint}"
    else:
        full_desc = base_desc

    yield FunctionInfo.from_fn(
        _run_skill,
        description=full_desc,
    )


# ── LabClaw ReAct Coordinator Workflow ──────────────────────────────────────


class LabClawReactConfig(AgentBaseConfig, name="labclaw_react"):
    """ReAct agent workflow for LabClaw — routes tasks through scientific skills."""

    tool_names: list[str] = Field(
        default_factory=list,
        description="Names of registered NAT functions to use as tools",
    )
    parse_agent_response_max_retries: int = Field(
        default=3,
        description="Max retries for parsing the LLM's structured response",
    )


@register_function(config_type=LabClawReactConfig)
async def labclaw_react_workflow(config: LabClawReactConfig, builder: Builder):
    """Build a LangGraph ReAct agent that coordinates LabClaw skills."""
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import StructuredTool
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    # Build LangChain LLM directly from NAT config (nvidia-nat-langchain not installed)
    llm_config = builder.get_llm_config(config.llm_name)
    llm = ChatOpenAI(
        base_url=llm_config.base_url,
        model=llm_config.model_name,
        api_key=llm_config.api_key.get_secret_value() if llm_config.api_key else None,
        temperature=getattr(llm_config, "temperature", 0.0),
    )

    # Build LangChain tools from NAT functions
    nat_functions = await builder.get_functions(config.tool_names)
    tools = []
    for i, fn in enumerate(nat_functions):
        tool_name = config.tool_names[i]
        nat_fn = fn  # capture for closure

        async def _tool_fn(input_json: str, _fn=nat_fn) -> str:
            return await _fn.ainvoke(input_json)

        tool = StructuredTool.from_function(
            coroutine=_tool_fn,
            name=tool_name,
            description=f"LabClaw skill: {tool_name}",
        )
        tools.append(tool)

    agent = create_react_agent(model=llm, tools=tools)

    async def _run(input_text: str) -> str:
        result = await agent.ainvoke({"messages": [HumanMessage(content=input_text)]})
        messages = result.get("messages", [])
        if messages:
            return messages[-1].content
        return "No response generated."

    yield FunctionInfo.from_fn(
        _run,
        description=(
            config.description
            if hasattr(config, "description") and config.description
            else "LabClaw ReAct coordinator agent"
        ),
    )

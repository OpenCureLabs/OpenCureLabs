"""
Hierarchical multi-agent architecture for LabClaw.

Registers two NAT component types:
  - specialist_agent: Domain-specific ReAct agent with a curated skill subset
  - hierarchical_coordinator: Top-level coordinator that delegates to specialists

Architecture:
  Coordinator (Gemini 2.5 Flash Lite)
    ├── Cancer Agent        → neoantigen, structure_prediction, sequencing_qc
    ├── Rare Disease Agent  → variant_pathogenicity, sequencing_qc
    ├── Drug Response Agent → qsar, molecular_docking, structure_prediction
    └── Utility tools       → register_source, report_generator (coordinator-level)
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.agent import AgentBaseConfig
from pydantic import Field

logger = logging.getLogger("labclaw.nat_specialists")

# ── Domain system prompts ────────────────────────────────────────────────────

CANCER_SYSTEM_PROMPT = (
    "You are a specialist agent for tumor immunology and cancer genomics.\n"
    "Your tools include neoantigen prediction, protein structure prediction, and sequencing QC.\n"
    "When given a task:\n"
    "1. Assess whether sequencing QC is needed first\n"
    "2. Run the appropriate analysis pipeline\n"
    "3. Return structured results with confidence scores\n\n"
    "Always use your tools — never fabricate scientific results."
)

RARE_DISEASE_SYSTEM_PROMPT = (
    "You are a specialist agent for rare disease variant analysis.\n"
    "Your tools include variant pathogenicity assessment and sequencing QC.\n"
    "When given a task:\n"
    "1. Run sequencing QC if raw data is provided\n"
    "2. Assess variant pathogenicity against ClinVar/OMIM\n"
    "3. Rank candidate genes by pathogenicity score\n\n"
    "Always use your tools — never fabricate scientific results."
)

DRUG_RESPONSE_SYSTEM_PROMPT = (
    "You are a specialist agent for drug response prediction.\n"
    "Your tools include QSAR modeling, molecular docking, and structure prediction.\n"
    "When given a task:\n"
    "1. Predict or retrieve the target protein structure\n"
    "2. Run molecular docking or QSAR as appropriate\n"
    "3. Report binding affinities, predicted activity, and confidence\n\n"
    "Always use your tools — never fabricate scientific results."
)


# ── Specialist Agent ─────────────────────────────────────────────────────────


class SpecialistAgentConfig(AgentBaseConfig, name="specialist_agent"):
    """NAT config for a domain-specialist ReAct agent."""

    specialty_domain: str = Field(description="Domain name (e.g. 'tumor_immunology')")
    system_prompt: str = Field(default="", description="Domain-specific system prompt")
    tool_names: list[str] = Field(
        default_factory=list,
        description="Names of labclaw_skill functions this specialist can use",
    )


@register_function(config_type=SpecialistAgentConfig)
async def specialist_agent(config: SpecialistAgentConfig, builder: Builder):
    """Build a domain-specific ReAct agent scoped to a skill subset."""

    llm_config = builder.get_llm_config(config.llm_name)
    llm = ChatOpenAI(
        base_url=llm_config.base_url,
        model=llm_config.model_name,
        api_key=llm_config.api_key.get_secret_value() if llm_config.api_key else None,
        temperature=getattr(llm_config, "temperature", 0.0),
    )

    nat_functions = await builder.get_functions(config.tool_names)
    tools = []
    for i, fn in enumerate(nat_functions):
        tool_name = config.tool_names[i]
        nat_fn = fn

        async def _tool_fn(input_json: str, _fn=nat_fn) -> str:
            return await _fn.ainvoke(input_json)

        tool = StructuredTool.from_function(
            coroutine=_tool_fn,
            name=tool_name,
            description=f"{config.specialty_domain} skill: {tool_name}",
        )
        tools.append(tool)

    system_msg = config.system_prompt or f"You are the {config.specialty_domain} specialist agent."
    agent = create_react_agent(model=llm, tools=tools, prompt=SystemMessage(content=system_msg))

    async def _run(input_text: str) -> str:
        result = await agent.ainvoke({"messages": [HumanMessage(content=input_text)]})
        messages = result.get("messages", [])
        return messages[-1].content if messages else "No response generated."

    yield FunctionInfo.from_fn(
        _run,
        description=f"{config.specialty_domain.replace('_', ' ').title()} Specialist Agent",
    )


# ── Hierarchical Coordinator ────────────────────────────────────────────────


class HierarchicalCoordinatorConfig(AgentBaseConfig, name="hierarchical_coordinator"):
    """Top-level coordinator that routes to specialist agents + utility tools."""

    specialist_names: list[str] = Field(
        description="Names of specialist_agent functions to delegate to",
    )
    utility_tool_names: list[str] = Field(
        default_factory=list,
        description="Names of utility functions available directly (e.g. register_source, report_generator)",
    )


COORDINATOR_SYSTEM_PROMPT = (
    "You are the LabClaw scientific coordinator for OpenCure Labs.\n"
    "You route research tasks to the correct specialist agent:\n\n"
    "- **cancer_agent**: Tumor immunology, neoantigen prediction, cancer genomics\n"
    "- **rare_disease_agent**: Variant pathogenicity, rare disease analysis, de novo mutations\n"
    "- **drug_response_agent**: QSAR models, molecular docking, drug discovery\n\n"
    "You also have utility tools:\n"
    "- **register_discovered_source**: Log a newly discovered data source\n"
    "- **report_generator**: Generate a PDF report of results\n\n"
    "Rules:\n"
    "1. Always delegate scientific work to the appropriate specialist.\n"
    "2. Never fabricate results — only report what specialists return.\n"
    "3. If a task spans domains, call multiple specialists in sequence.\n"
    "4. Use report_generator to produce final reports when requested.\n"
    "5. Pass complete task context to each specialist — include data paths, parameters, etc."
)


@register_function(config_type=HierarchicalCoordinatorConfig)
async def hierarchical_coordinator(config: HierarchicalCoordinatorConfig, builder: Builder):
    """Build the top-level coordinator that delegates to specialist agents."""

    llm_config = builder.get_llm_config(config.llm_name)
    llm = ChatOpenAI(
        base_url=llm_config.base_url,
        model=llm_config.model_name,
        api_key=llm_config.api_key.get_secret_value() if llm_config.api_key else None,
        temperature=getattr(llm_config, "temperature", 0.0),
    )

    all_tool_names = config.specialist_names + config.utility_tool_names
    nat_functions = await builder.get_functions(all_tool_names)

    tools = []
    for i, fn in enumerate(nat_functions):
        tool_name = all_tool_names[i]
        nat_fn = fn

        async def _tool_fn(input_text: str, _fn=nat_fn) -> str:
            return await _fn.ainvoke(input_text)

        tool = StructuredTool.from_function(
            coroutine=_tool_fn,
            name=tool_name,
            description=f"Delegate to {tool_name}" if tool_name in config.specialist_names
            else f"Utility: {tool_name}",
        )
        tools.append(tool)

    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SystemMessage(content=COORDINATOR_SYSTEM_PROMPT),
    )

    async def _run(input_text: str) -> str:
        result = await agent.ainvoke({"messages": [HumanMessage(content=input_text)]})
        messages = result.get("messages", [])
        return messages[-1].content if messages else "No response generated."

    yield FunctionInfo.from_fn(
        _run,
        description=config.description or "LabClaw Hierarchical Coordinator — routes to specialist agents",
    )

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
        input_data = skill_instance.input_schema.model_validate_json(input_json)
        result = skill_instance.execute(input_data)

        # Post-execution orchestration: guardrails → reviewer → publisher
        try:
            from agentiq_labclaw.orchestrator import post_execute

            enriched = await post_execute(
                skill_name=config.skill_name,
                result=result,
            )
            return json.dumps(enriched, default=str, indent=2)
        except Exception as e:
            logger.warning("Post-execution orchestration error (returning raw result): %s", e)
            if isinstance(result, BaseModel):
                return result.model_dump_json(indent=2)
            return json.dumps(result, default=str)

    yield FunctionInfo.from_fn(
        _run_skill,
        description=skill_instance.description or f"LabClaw skill: {config.skill_name}",
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

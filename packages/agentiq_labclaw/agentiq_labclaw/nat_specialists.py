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

import json
import logging
import os

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

# ── LLM cost rate cards (per token) ──────────────────────────────────────────
# Rates as of March 2026.  Update when pricing changes.
LLM_RATE_CARDS = {
    "gemini-2.5-flash-lite-preview-06-17": {"provider": "gemini", "input": 0.075e-6, "output": 0.3e-6},
    "gemini-2.5-flash-lite": {"provider": "gemini", "input": 0.075e-6, "output": 0.3e-6},
    "claude-opus-4-0-20250514": {"provider": "claude", "input": 15e-6, "output": 75e-6},
    "grok-4-1-fast-non-reasoning": {"provider": "grok", "input": 0.2e-6, "output": 0.5e-6},
    "grok-4.20-non-reasoning": {"provider": "grok", "input": 2e-6, "output": 6e-6},
}


def _log_llm_usage(model: str, usage: dict, agent_name: str = ""):
    """Log LLM token usage and estimated cost to the llm_spend table."""
    if not usage:
        return
    input_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0) or 0
    output_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0) or 0
    if input_tokens == 0 and output_tokens == 0:
        return

    # Look up rate card
    rates = LLM_RATE_CARDS.get(model, {})
    provider = rates.get("provider", model.split("-")[0] if model else "unknown")
    cost = (input_tokens * rates.get("input", 0)) + (output_tokens * rates.get("output", 0))

    try:
        import psycopg2
        db_url = os.environ.get("POSTGRES_URL", "dbname=opencurelabs port=5433")
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS llm_spend ("
            "  id SERIAL PRIMARY KEY, provider TEXT NOT NULL, model TEXT,"
            "  input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,"
            "  estimated_cost REAL DEFAULT 0, skill_name TEXT, agent_name TEXT,"
            "  created_at TIMESTAMP DEFAULT NOW())",
        )
        cur.execute(
            "INSERT INTO llm_spend (provider, model, input_tokens, output_tokens, estimated_cost, agent_name)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (provider, model, input_tokens, output_tokens, cost, agent_name),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.debug(
            "LLM usage: %s %d in / %d out → $%.6f",
            provider, input_tokens, output_tokens, cost,
        )
    except Exception as e:
        logger.debug("Could not log LLM usage: %s", e)

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


def _make_schema_tool_fn(nat_fn):
    """Factory to create a tool function that accepts schema kwargs and serializes to JSON."""

    async def _tool_fn(**kwargs) -> str:
        return await nat_fn.ainvoke(json.dumps(kwargs, default=str))

    return _tool_fn


def _get_skill_schema(tool_name: str):
    """Try to get a skill's input schema and description from the registry."""
    # Ensure all skill modules are imported so the registry is populated
    try:
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
    except ImportError:
        pass

    try:
        from agentiq_labclaw.base import get_skill

        skill_cls = get_skill(tool_name)
        return skill_cls.input_schema, skill_cls.description
    except (KeyError, ImportError):
        return None, None


@register_function(config_type=SpecialistAgentConfig)
async def specialist_agent(config: SpecialistAgentConfig, builder: Builder):
    """Build a domain-specific ReAct agent scoped to a skill subset."""

    llm_config = builder.get_llm_config(config.llm_name)
    llm = ChatOpenAI(
        base_url=llm_config.base_url,
        model=llm_config.model_name,
        api_key=llm_config.api_key.get_secret_value() if llm_config.api_key else None,
        temperature=getattr(llm_config, "temperature", 0.0),
        request_timeout=300,  # 5-min guard against hung Gemini connections
    )

    nat_functions = await builder.get_functions(config.tool_names)
    tools = []
    for i, fn in enumerate(nat_functions):
        tool_name = config.tool_names[i]
        nat_fn = fn

        # Try to get the Pydantic input schema so the LLM sees exact field names/types
        skill_schema, skill_desc = _get_skill_schema(tool_name)

        if skill_schema is not None:
            tool = StructuredTool.from_function(
                coroutine=_make_schema_tool_fn(nat_fn),
                name=tool_name,
                description=skill_desc or f"{config.specialty_domain} skill: {tool_name}",
                args_schema=skill_schema,
            )
        else:
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
        run_id = None
        try:
            from agentiq_labclaw.db.agent_runs import complete_run, start_run
            run_id = start_run(agent_name=config.specialty_domain)
        except Exception as e:
            logger.debug("Could not record specialist run start: %s", e)

        try:
            result = await agent.ainvoke({"messages": [HumanMessage(content=input_text)]})
            messages = result.get("messages", [])
            response = messages[-1].content if messages else "No response generated."

            # Log LLM token usage from all AI messages
            for msg in messages:
                if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                    _log_llm_usage(
                        model=llm.model_name,
                        usage=msg.usage_metadata,
                        agent_name=config.specialty_domain,
                    )
                elif hasattr(msg, "response_metadata"):
                    token_usage = (msg.response_metadata or {}).get("token_usage") or \
                                  (msg.response_metadata or {}).get("usage", {})
                    if token_usage:
                        _log_llm_usage(
                            model=llm.model_name,
                            usage=token_usage,
                            agent_name=config.specialty_domain,
                        )

            if run_id is not None:
                try:
                    complete_run(run_id, status="completed")
                except Exception:
                    logger.debug("Failed to mark specialist run %s as completed", run_id)

            return response
        except Exception as e:
            if run_id is not None:
                try:
                    from agentiq_labclaw.db.agent_runs import complete_run as _cr
                    _cr(run_id, status="failed", result={"error": str(e)})
                except Exception:
                    pass
            raise

    yield FunctionInfo.from_fn(
        _run,
        description=f"{config.specialty_domain.replace('_', ' ').title()} Specialist Agent",
    )


# ── Hierarchical Coordinator ────────────────────────────────────────────────

# Fallback descriptions when FunctionInfo.description is not available
_SPECIALIST_DESCRIPTIONS = {
    "cancer_agent": (
        "CALL THIS TOOL for any task involving tumor immunology, neoantigen prediction, "
        "cancer genomics, or veterinary oncology (canine/feline). Pass the complete task "
        "description including sample IDs, VCF paths, HLA alleles, tumor types, and species."
    ),
    "rare_disease_agent": (
        "CALL THIS TOOL for any task involving variant pathogenicity, rare disease analysis, "
        "de novo mutations, or genetic variant assessment. Pass the complete task description "
        "including gene names, variant IDs, and species."
    ),
    "drug_response_agent": (
        "CALL THIS TOOL for any task involving QSAR modeling, molecular docking, drug discovery, "
        "or drug response prediction. Pass the complete task description including SMILES, "
        "receptor PDB IDs, and dataset paths."
    ),
}


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
    "You route research tasks to the correct specialist agent.\n\n"
    "CRITICAL RULES — you MUST follow these without exception:\n"
    "1. For ANY scientific task, you MUST call the appropriate specialist agent tool.\n"
    "   Do NOT answer scientific questions with text — ALWAYS delegate by calling a tool.\n"
    "2. Route to the correct specialist:\n"
    "   - cancer_agent: neoantigen prediction, tumor immunology, cancer genomics, veterinary oncology\n"
    "   - rare_disease_agent: variant pathogenicity, rare disease analysis, de novo mutations\n"
    "   - drug_response_agent: QSAR modeling, molecular docking, drug discovery\n"
    "3. Pass the COMPLETE task description to the specialist — include ALL data paths, parameters,\n"
    "   sample IDs, species, HLA alleles, tumor types, VCF paths, etc. Do not summarize or omit details.\n"
    "4. Never fabricate results — only report what specialists return.\n"
    "5. If a task spans domains, call multiple specialists in sequence.\n"
    "6. Use register_discovered_source to log new data sources.\n"
    "7. Use report_generator to produce PDF reports when requested.\n\n"
    "REMEMBER: Your job is to DELEGATE, not to answer. Call a tool for every scientific request."
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
        request_timeout=300,  # 5-min guard against hung Gemini connections
    )

    all_tool_names = config.specialist_names + config.utility_tool_names
    nat_functions = await builder.get_functions(all_tool_names)

    tools = []
    for i, fn in enumerate(nat_functions):
        tool_name = all_tool_names[i]
        nat_fn = fn
        is_specialist = tool_name in config.specialist_names

        if is_specialist:
            # Specialist agents take free-text task descriptions
            async def _tool_fn(input_text: str, _fn=nat_fn) -> str:
                return await _fn.ainvoke(input_text)

            # Use the description from the FunctionInfo if available
            spec_desc = getattr(fn, 'description', '') or ''
            if not spec_desc:
                spec_desc = _SPECIALIST_DESCRIPTIONS.get(tool_name, f"Delegate to {tool_name}")

            tool = StructuredTool.from_function(
                coroutine=_tool_fn,
                name=tool_name,
                description=spec_desc,
            )
        else:
            # Utility tools — try to get skill schema for structured args
            skill_schema, skill_desc = _get_skill_schema(tool_name)

            if skill_schema is not None:
                tool = StructuredTool.from_function(
                    coroutine=_make_schema_tool_fn(nat_fn),
                    name=tool_name,
                    description=skill_desc or f"Utility: {tool_name}",
                    args_schema=skill_schema,
                )
            else:
                async def _tool_fn(input_text: str, _fn=nat_fn) -> str:
                    return await _fn.ainvoke(input_text)

                tool = StructuredTool.from_function(
                    coroutine=_tool_fn,
                    name=tool_name,
                    description=f"Utility: {tool_name}",
                )
        tools.append(tool)

    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SystemMessage(content=COORDINATOR_SYSTEM_PROMPT),
    )

    async def _run(input_text: str) -> str:
        run_id = None
        try:
            from agentiq_labclaw.db.agent_runs import complete_run, start_run
            run_id = start_run(agent_name="coordinator")
        except Exception as e:
            logger.debug("Could not record coordinator run start: %s", e)

        try:
            result = await agent.ainvoke({"messages": [HumanMessage(content=input_text)]})
            messages = result.get("messages", [])
            response = messages[-1].content if messages else "No response generated."

            # Log LLM token usage from coordinator's AI messages
            for msg in messages:
                if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                    _log_llm_usage(
                        model=llm.model_name,
                        usage=msg.usage_metadata,
                        agent_name="coordinator",
                    )
                elif hasattr(msg, "response_metadata"):
                    token_usage = (msg.response_metadata or {}).get("token_usage") or \
                                  (msg.response_metadata or {}).get("usage", {})
                    if token_usage:
                        _log_llm_usage(
                            model=llm.model_name,
                            usage=token_usage,
                            agent_name="coordinator",
                        )

            if run_id is not None:
                try:
                    complete_run(run_id, status="completed")
                except Exception:
                    logger.debug("Failed to mark coordinator run %s as completed", run_id)

            return response
        except Exception as e:
            if run_id is not None:
                try:
                    from agentiq_labclaw.db.agent_runs import complete_run as _cr
                    _cr(run_id, status="failed", result={"error": str(e)})
                except Exception:
                    pass
            raise

    yield FunctionInfo.from_fn(
        _run,
        description=config.description or "LabClaw Hierarchical Coordinator — routes to specialist agents",
    )

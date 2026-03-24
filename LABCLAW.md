# LabClaw — Scientific Skill Layer Specification

## What is LabClaw?

LabClaw is the **scientific skill layer** that sits on top of the NVIDIA NeMo Agent Toolkit (AgentIQ). It is not a separate framework — it is OpenCure Labs' domain-specific extension of NeMo that makes general-purpose agent orchestration useful for computational biology.

Think of the relationship like this:

```
┌─────────────────────────────────────────────────┐
│                   NemoClaw                       │
│  The running coordinator instance — the          │
│  process that boots, loads config, and           │
│  manages the agent session lifecycle             │
│                                                  │
│  ┌───────────────────────────────────────────┐  │
│  │               LabClaw                      │  │
│  │  The scientific skill registry and         │  │
│  │  domain logic layer — the OpenCure Labs         │  │
│  │  plugin that lives inside NeMo AgentIQ     │  │
│  │                                            │  │
│  │  ┌─────────────────────────────────────┐  │  │
│  │  │     NVIDIA NeMo Agent Toolkit        │  │  │
│  │  │     (AgentIQ) — the foundation       │  │  │
│  │  │     YAML orchestration · nat CLI     │  │  │
│  │  │     tool registry · telemetry        │  │  │
│  │  └─────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

**NemoClaw** = the coordinator process (boots the system, manages sessions)
**LabClaw** = the scientific plugin layer (skills, guardrails, domain routing)
**NeMo AgentIQ** = the underlying orchestration framework both run on

---

## LabClaw Responsibilities

| Responsibility | Description |
|---|---|
| **Skill registry** | Registers and exposes scientific skill modules to NeMo's tool registry |
| **Domain routing** | Maps incoming tasks to the correct specialist agent based on input type |
| **Skill invocation** | Calls skill modules with validated inputs and returns structured outputs |
| **Guardrail enforcement** | Validates outputs before they reach downstream agents or publishing |
| **Data registration** | Accepts newly discovered sources from Grok and queues them for ingestion |
| **Result routing** | Sends novel results to the Grok reviewer agent (two-tier critique) |
| **Publishing coordination** | Triggers GitHub commits and PDF report generation |

---

## Architecture: How LabClaw Sits Inside NeMo AgentIQ

NeMo Agent Toolkit uses a plugin system based on Python entry points and decorators. LabClaw is implemented as a NeMo AgentIQ package (`agentiq_labclaw`) that registers its skills and workflows into the NeMo tool registry at startup.

```
packages/
  agentiq_labclaw/
    __init__.py
    skills/
      neoantigen.py        # Neoantigen prediction skill
      structure.py         # Protein structure prediction (ESMFold, AlphaFold)
      docking.py           # Molecular docking (AutoDock Vina, Gnina)
      qsar.py              # QSAR model training and inference
      variant_pathogenicity.py  # Variant scoring (ClinVar/OMIM cross-ref)
      sequencing_qc.py     # Sequencing data ingestion and QC
      report_generator.py  # Scientific PDF report generation
    guardrails/
      output_validator.py  # Schema validation on all skill outputs
      novelty_filter.py    # Flags results as novel vs replication
      safety_check.py      # Prevents publishing incomplete/invalid results
    connectors/
      tcga.py              # TCGA/GEO data ingestion
      clinvar.py           # ClinVar/OMIM variant lookup
      chembl.py            # ChEMBL compound queries
      discovered_sources.py # Handles Grok-registered dynamic sources
    publishers/
      pdf_publisher.py     # Generates and stores PDF reports
    db/
      agent_runs.py        # PostgreSQL interface for run logging
      discovered_sources.py
      pipeline_runs.py
      critique_log.py
      experiment_results.py
```

---

## Skill Interface

Every LabClaw skill is a Python class that inherits from `LabClawSkill` and registers itself with the NeMo tool registry via the `@labclaw_skill` decorator.

```python
from agentiq_labclaw import LabClawSkill, labclaw_skill
from pydantic import BaseModel

class NeoantigenInput(BaseModel):
    sample_id: str
    vcf_path: str
    hla_alleles: list[str]
    tumor_type: str

class NeoantigenOutput(BaseModel):
    sample_id: str
    candidates: list[dict]
    top_candidate: dict
    confidence_score: float
    novel: bool
    critique_required: bool

@labclaw_skill(
    name="neoantigen_prediction",
    description="Predicts neoantigens from somatic variant calls and HLA typing",
    input_schema=NeoantigenInput,
    output_schema=NeoantigenOutput,
    compute="local",        # "local" | "vast_ai"
    gpu_required=True,
)
class NeoantigenSkill(LabClawSkill):
    def run(self, input: NeoantigenInput) -> NeoantigenOutput:
        # pipeline logic here
        ...
```

**All skills must:**
- Define typed input and output schemas using Pydantic
- Declare compute target (`local` or `vast_ai`)
- Return structured output that guardrails can validate
- Set `critique_required=True` if output is a novel scientific result

---

## YAML Workflow Configuration

The coordinator is configured via YAML and run with `nat run`. A LabClaw workflow config looks like this:

```yaml
# coordinator/labclaw_workflow.yaml

llms:
  coordinator_llm:
    _type: openai
    base_url: https://generativelanguage.googleapis.com/v1beta/openai/
    model_name: gemini-2.5-flash-lite
    api_key: ${GENAI_API_KEY}
    temperature: 0.0

functions:
  neoantigen_prediction:
    _type: labclaw_skill
    skill_name: neoantigen_prediction

  variant_pathogenicity:
    _type: labclaw_skill
    skill_name: variant_pathogenicity

  molecular_docking:
    _type: labclaw_skill
    skill_name: docking
    compute: vast_ai              # override to burst for this skill

  register_discovered_source:
    _type: labclaw_skill
    skill_name: register_source   # called by Grok when it finds new data

workflow:
  _type: labclaw_react
  llm_name: coordinator_llm
  tool_names:
    - neoantigen_prediction
    - variant_pathogenicity
    - molecular_docking
    - register_discovered_source
  verbose: true
  parse_agent_response_max_retries: 3

guardrails:
  output_validation: true
  novelty_filter: true
  safety_check: true

publishers:
  github:
    enabled: true
    repo: git@github.com:OpenCureLabs/OpenCureLabs.git
  pdf:
    enabled: true
    output_dir: /path/to/OpenCureLabs/reports/
```

---

## Coordinator LLM — Local First

LabClaw does **not** require NVIDIA hosted NIM endpoints. The coordinator LLM can be:

| Option | Setup | Notes |
|---|---|---|
| **Gemini API (current)** | `GENAI_API_KEY` in .env | Uses Gemini 2.0 Flash Lite for coordinator reasoning |
| **xAI API** | `XAI_API_KEY` in .env | Uses Grok for coordinator reasoning |

The RTX 5070 is reserved for scientific compute (structure prediction, docking, ML). The coordinator LLM should be lightweight — its job is routing and reasoning, not heavy inference.

**Current setup:**
```bash
# Set your Gemini API key in .env
# GENAI_API_KEY=your-key-here

# The coordinator connects to Gemini 2.0 Flash Lite via OpenAI-compatible API
# Configuration is in coordinator/labclaw_workflow.yaml
```

---

## Guardrails

LabClaw implements three guardrail layers that run on every skill output before it reaches downstream agents or publishing:

**1. Output Validator**
Checks that skill output matches its declared Pydantic schema. Rejects malformed outputs and logs the failure to PostgreSQL.

**2. Novelty Filter**
Compares results against `experiment_results` in PostgreSQL. Flags results as `novel=True` if no matching prior result exists. Only novel results trigger the Grok literature reviewer.

**3. Safety Check**
Blocks publishing if:
- Confidence score is below threshold
- Required fields are missing
- The pipeline run has no associated `agent_run_id`
- The result has not been through critique (if `critique_required=True`)

---

## Communication Between Components

LabClaw communicates with specialist agents and reviewer agents via the NeMo tool registry — everything is a function call, not a network request.

```
Coordinator (NeMo labclaw_react)
    │
    ├── calls labclaw_skill("neoantigen_prediction", input)
    │       └── runs NeoantigenSkill.run()
    │               └── executes local pipeline on RTX 5070
    │                       └── returns NeoantigenOutput
    │
    ├── guardrails validate NeoantigenOutput
    │
    ├── if novel=True → calls claude_opus_reviewer(result)
    │       └── returns CritiqueJSON → stored in critique_log
    │
    ├── if novel=True → calls grok_literature_reviewer(result)
    │       └── returns LiteratureContext
    │
    └── publishes to GitHub + PDF
```

Grok communicates back to LabClaw via a dedicated `register_discovered_source` skill — when Grok finds a new dataset, it calls this skill with the source URL and domain, which writes to `discovered_sources` in PostgreSQL and queues it for coordinator review.

---

## PostgreSQL Integration

LabClaw reads and writes to the `opencurelabs` PostgreSQL database for all persistent state. Connection string is read from the environment: `POSTGRES_URL=postgresql://localhost/opencurelabs`.

All database interactions go through the `agentiq_labclaw.db` module — skills never write to PostgreSQL directly.

---

## Compute Routing

Each skill declares its compute target. LabClaw handles routing:

```python
# In LabClawSkill base class
def execute(self, input):
    if self.compute == "vast_ai":
        return self._dispatch_to_vast_ai(input)
    else:
        return self.run(input)  # local RTX 5070
```

Vast.ai dispatch is handled by `agentiq_labclaw.compute.vast_dispatcher`, which provisions a GPU instance, runs the job, streams results back, and terminates the instance.

---

## File Locations

| Path | Contents |
|---|---|
| `coordinator/labclaw_workflow.yaml` | Main NeMo workflow config |
| `skills/` | LabClaw skill module implementations |
| `agents/` | Specialist agent configs (cancer, rare-disease, drug-response) |
| `config/` | Additional NeMo configs, model settings |
| `db/` | PostgreSQL schemas and migration scripts |
| `workspace/` | Grok's sandboxed working directory |
| `logs/` | Agent run logs |
| `reports/` | Generated PDF outputs |

---

## Running LabClaw

```bash
# Activate venv
source /path/to/OpenCureLabs/.venv/bin/activate

# Ensure PostgreSQL is running
service postgresql start

# Run the coordinator
cd /path/to/OpenCureLabs
nat run --config_file coordinator/labclaw_workflow.yaml --input "your task here"

# Run Grok researcher (from workspace/ only)
cd /path/to/OpenCureLabs/workspace
grok --max-tool-rounds 200 --prompt "search bioRxiv for new neoantigen datasets this week"
```

---

## Implementation Status

| Component | Status |
|---|---|
| NeMo Agent Toolkit install | ✅ Installed (v1.1.0) |
| `agentiq_labclaw` package | ✅ Implemented (v0.1.0) |
| Coordinator YAML config | ✅ Implemented |
| Skill: neoantigen_prediction | ✅ Implemented (VCF→pyensembl→MHCflurry pipeline, batch predictions, tested with KRAS G12V + TP53 R175H) |
| Skill: structure_prediction | ✅ Scaffold (pipeline logic TODO) |
| Skill: molecular_docking | ✅ Scaffold (pipeline logic TODO) |
| Skill: qsar | ✅ Scaffold (pipeline logic TODO) |
| Skill: variant_pathogenicity | ✅ Scaffold (pipeline logic TODO) |
| Skill: sequencing_qc | ✅ Scaffold (pipeline logic TODO) |
| Skill: report_generator | ✅ Scaffold (PDF rendering TODO) |
| Skill: register_source | ✅ Implemented |
| Guardrails layer | ✅ Implemented (output validator, novelty filter, safety check) |
| PostgreSQL integration | ✅ Implemented (5 DB modules) |
| Grok source registration | ✅ Implemented |
| PDF publisher | ✅ Scaffold (Markdown placeholder) |
| Vast.ai dispatcher | ✅ Scaffold (API integration TODO) |
| Ollama local LLM | ❌ Removed (coordinator uses Gemini API) |
| Data connectors (TCGA, ClinVar, ChEMBL) | ✅ Scaffold (API calls TODO) |
| Agent configs (cancer, rare-disease, drug-response) | ✅ Implemented |
| Reviewer configs (Grok two-tier) | ✅ Implemented |

---

*This document is the authoritative spec for LabClaw. README.md describes what it does. This document describes how it works.*

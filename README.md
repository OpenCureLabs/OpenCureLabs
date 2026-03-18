# 🧬 OpenCure Labs — Autonomous AI-for-Science Platform

> An open, transparent, multi-agent computational research lab — running real scientific pipelines, iterating autonomously, and sharing every step live with the world.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Data Sources](#data-sources)
- [Agent Layer](#agent-layer)
- [Compute Infrastructure](#compute-infrastructure)
- [Reviewer Agents](#reviewer-agents)
- [Outputs & Publishing](#outputs--publishing)
- [Scientific Capabilities](#scientific-capabilities)
- [Roadmap](#roadmap)
- [Philosophy](#philosophy)
- [Getting Started](#getting-started)
- [Contributing](#contributing)

See also: **[CONTRIBUTING.md](CONTRIBUTING.md)** — full guide for researchers and developers.

---

## Overview

OpenCure Labs is an autonomous AI-for-Science environment built to explore **computational biology**, **personalized medicine**, and **large-scale scientific workflows** through multi-agent orchestration.

Rather than a traditional research pipeline with manual handoffs, OpenCure Labs runs **agents that coordinate, critique, and iterate** — analyzing genomics data, predicting protein structures, running docking simulations, and publishing findings, all with minimal human bottlenecking.

Everything is logged publicly to **Discord** in real time so anyone can follow the reasoning, question the methods, and engage with the science as it happens.

---

## Architecture

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │                        DATA LAYER                                    │
 │  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐             │
 │  │  TCGA / GEO  │  │ ClinVar / OMIM│  │   ChEMBL     │  + more ──► │
 │  │Cancer genomics│  │ Rare variants │  │Drug bioact.  │  (see below)│
 │  └──────┬───────┘  └──────┬────────┘  └──────┬───────┘             │
 └─────────┼─────────────────┼─────────────────-┼─────────────────────┘
           │                 │                   │
           └─────────────────┼───────────────────┘
                             │        ▲
                             │        │ new datasets
                             │        │ discovered
                             ▼        │
 ┌───────────────────────────────────────────────────────────────────┐
 │        Agent Coordinator — NemoClaw / LabClaw                      │
 │        Powered by NVIDIA NeMo Agent Toolkit (AgentIQ)              │
 │   Routes tasks · calls skills · enforces guardrails · publishes    │
 │   YAML-configured · nat CLI · NIM inference · telemetry            │
 └──────────────────────────┬────────────────────────────────────────┘
                 ┌───────────┼─────────────┐
                 ▼           ▼             ▼
          ┌─────────┐  ┌──────────┐  ┌───────────┐
          │ Cancer  │  │   Rare   │  │   Drug    │
          │  Agent  │  │ Disease  │  │ Response  │
          │ Tumor   │  │ Variant  │  │ QSAR +    │
          │Immunol. │  │ Analysis │  │  Docking  │
          └────┬────┘  └──────────┘  └─────┬─────┘
               │                           │
               ▼                           ▼
        ┌────────────┐             ┌─────────────┐
        │ Local RTX  │             │  Vast.ai    │
        │   5070     │             │   Burst     │
        │ Genomics,  │             │  Heavy ML   │
        │ Structure  │             │    Jobs     │
        └─────┬──────┘             └──────┬──────┘
              │                           │
              ▼                           ▼
        ┌──────────────┐           ┌──────────────────────────────┐
        │ Claude       │           │  Grok (VM resident)          │
        │ Opus 4.6     │           │  grok-cli / xAI API          │
        │ Scientific   │           │  ┌────────────────────────┐  │
        │ logic · stats│           │  │ Researcher role:       │  │
        │ Returns JSON │           │  │ · Hunt new datasets    │  │
        │ critique     │           │  │ · Scrape bioRxiv/EBI   │  │
        └──────┬───────┘           │  │ · Monitor ClinTrials   │  │
               │                   │  │ · Find GEO accessions  │  │
               │                   │  │ · DeepSearch (xAI)     │  │
               │                   │  │ · Execute bash on VM   │  │
               │                   │  └────────────────────────┘  │
               │                   └──────────────┬───────────────┘
               │                                  │
               └──────────────┬───────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         ┌────────┐     ┌──────────┐    ┌──────────┐
         │ GitHub │     │ Discord  │    │   PDF    │
         │Pipelines│    │  Live    │    │ Reports  │
         │ + code │     │  Logs    │    │Findings  │
         └────────┘     └──────────┘    └──────────┘
```

---

## Data Sources

OpenCure Labs ingests data from three primary scientific repositories — plus a continuously expanding pool of sources discovered autonomously by the Grok researcher agent:

### Pre-configured Sources

| Source | Domain | Description |
|---|---|---|
| **TCGA / GEO** | Cancer Genomics | Tumor sequencing data, expression profiles, somatic mutation datasets |
| **ClinVar / OMIM** | Rare Variants | Clinically curated variant classifications, gene-disease associations |
| **ChEMBL** | Drug Bioactivity | Compound bioactivity data, binding affinities, pharmacological annotations |

### Grok-Discovered Sources (dynamic)

Grok runs continuously on the VM and surfaces new data sources the system hasn't seen before. Confirmed candidates include:

| Source | Domain | How Grok finds it |
|---|---|---|
| **bioRxiv / medRxiv** | Preprints | DeepSearch + xAI web access |
| **EBI / UniProt** | Protein / variant | Structured API queries from VM |
| **ClinicalTrials.gov** | Trial data | Monitoring new registrations |
| **GEO new accessions** | Expression datasets | Watching release feeds |
| **PubChem** | Compound data | Expanding ChEMBL hits |
| **OpenTargets** | Gene-disease links | Cross-referencing ClinVar findings |
| **Zenodo / Figshare** | Open science data | Surfacing curated community datasets |

All discovered sources are registered with the coordinator for validation and routing before ingestion.

---

---

## Agent Layer

### Coordinator — NemoClaw / LabClaw

Built on the **[NVIDIA NeMo Agent Toolkit](https://github.com/NVIDIA/NeMo-Agent-Toolkit)** (AgentIQ), the coordinator is defined in YAML and orchestrated via the `nat` CLI, backed by NVIDIA NIM microservices for inference. NeMo manages the agent lifecycle — workflow definition, evaluation, telemetry, and hyperparameter tuning. NIMs handle model inference. When NeMo fine-tunes or improves a model, it redeploys back into a NIM, creating a continuous improvement loop native to the platform.

The coordinator is responsible for:

- **Task routing** — dispatching jobs to the correct domain agent based on input type and objective
- **Skill invocation** — calling specific scientific skill modules (e.g., structure prediction, neoantigen scoring)
- **Guardrail enforcement** — validating outputs before downstream consumption
- **Publishing** — coordinating delivery to GitHub, Discord, and PDF reports

### Specialist Agents

**Cancer Agent** — Tumor Immunology
Processes cancer genomics data to identify somatic mutations, predict neoantigens, and model tumor-immune microenvironments.

**Rare Disease Agent** — Variant Analysis
Analyzes rare and de novo variants against ClinVar/OMIM databases to assess pathogenicity, identify candidate genes, and support diagnosis workflows.

**Drug Response Agent** — QSAR + Docking
Builds quantitative structure–activity relationship models, runs molecular docking simulations, and predicts compound efficacy profiles using ChEMBL data.

---

## Compute Infrastructure

OpenCure Labs is designed for hybrid local/cloud execution:

### Local Compute

| Component | Specification |
|---|---|
| GPU | RTX 5070 (current) → dual RTX 5090 (planned) |
| CPU | Future: Threadripper Pro |
| RAM | 256 GB |
| Storage | 8 TB NVMe |
| Environment | WSL-Agents + Python venv |

Best suited for: **genomics pipelines, protein structure prediction, standard ML inference**

### Cloud Burst — Vast.ai

Heavy GPU/CPU workloads that exceed local capacity are offloaded to Vast.ai on demand. The Drug Response agent's ML training jobs are the primary consumer of burst compute.

Best suited for: **large-scale QSAR training, multi-GPU docking sweeps, distributed ML**

---

## Reviewer Agents

All novel results pass through two independent reviewer agents before publication:

### Claude Opus 4.6 — Scientific Critic
- Evaluates scientific logic, statistical methodology, and interpretive validity
- Returns structured JSON critique objects that downstream agents can parse and act on
- Triggers on every non-trivial result

### Grok — VM Resident Researcher & Literature Monitor

Grok lives on the VM as a persistent agent, running via **[grok-cli](https://github.com/superagent-ai/grok-cli)** (xAI API at `api.x.ai/v1`, OpenAI-compatible) or the forthcoming **Grok Build** CLI once it reaches general availability.

**Researcher role (proactive):**
- Executes bash commands and file operations directly on the VM
- Hunts for new datasets across bioRxiv, EBI, GEO, ClinicalTrials.gov, PubChem, OpenTargets, Zenodo
- Uses xAI's DeepSearch to scan X and the live web for emerging data and findings
- Registers discovered sources with the coordinator for validation

**Reviewer role (reactive):**
- Monitors recent publications and preprint servers for findings relevant to current experiments
- Only fires on **novel results** — suppressed when findings replicate known literature
- Surfaces contradicting evidence and related recent work for researcher review

This dual-role design means Grok is not just a passive critic but an **active lab member** — expanding the data surface area of the platform continuously while also keeping results anchored in the current state of the literature.

---

## Outputs & Publishing

| Channel | Content |
|---|---|
| **GitHub** | All pipelines, code, analysis notebooks, and reproducibility artifacts |
| **Discord (Live)** | Real-time agent logs — reasoning traces, intermediate results, critique exchanges |
| **PDF Reports** | Formal findings documents with methodology, results, and reviewer notes |

The Discord stream is designed to be human-readable: anyone, regardless of technical background, can follow what the agents are doing and why.

---

## Scientific Capabilities

OpenCure Labs is currently capable of or actively building toward:

- [x] Sequencing data ingestion and QC (TCGA/GEO)
- [x] Somatic mutation calling and annotation
- [x] Neoantigen prediction pipelines
- [x] Protein structure modeling
- [x] Molecular docking and binding affinity scoring
- [x] QSAR model training and evaluation
- [x] Automated scientific report generation
- [x] Autonomous critique and iterative refinement
- [ ] Full end-to-end neoantigen → vaccine candidate workflow
- [ ] Multi-omics integration (transcriptomics + proteomics)
- [ ] Active learning loops for compound optimization

---

## Roadmap

**Phase 1 — Foundation** *(current)*
- Coordinator architecture (NemoClaw/LabClaw)
- Data ingestion from TCGA, ClinVar, ChEMBL
- Local RTX 5070 compute environment
- Discord live logging

**Phase 2 — Scale**
- Vast.ai burst compute integration
- Dual reviewer agent deployment (Claude Opus 4.6 + Grok 4.2)
- Automated PDF report generation
- GitHub Actions–based pipeline CI/CD

**Phase 3 — Autonomy**
- Closed-loop experiment design and iteration
- Active learning for compound optimization
- Multi-omics data fusion
- Threadripper Pro + dual 5090 local cluster upgrade

---

## Philosophy

OpenCure Labs is built on three principles:

**Open Science by Default.** All code, data sources, methodology, and agent reasoning are public. Science advances faster when it's visible.

**Autonomous but Accountable.** Agents run independently, but every result passes through structured critique before publication. Speed and rigor are not in tension.

**Infrastructure as Research.** The platform itself is a research output. Building reliable, reproducible, agent-native scientific workflows is as valuable as any single finding it produces.

---

## Getting Started

For the full step-by-step guide, see **[docs/QUICKSTART.md](docs/QUICKSTART.md)**.

### Quick Setup (Fresh Ubuntu VM)

```bash
# Clone the repository
git clone https://github.com/OpenCureLabs/OpenCureLabs.git
cd OpenCureLabs

# Run the automated setup script (installs everything)
sudo bash scripts/setup.sh

# Configure your API keys
nano .env

# Launch the tmux control panel
bash dashboard/lab.sh
```

The setup script installs system packages, Python dependencies, scientific models
(pyensembl, MHCflurry), PostgreSQL, Ollama, and runs verification checks.
See [docs/QUICKSTART.md](docs/QUICKSTART.md) for manual setup and troubleshooting.

### Prerequisites

- Ubuntu 22.04+ or WSL2
- Python 3.11+
- Root access
- ~5 GB free disk space
- Anthropic API key (Claude Opus 4.6 reviewer)
- xAI API key (Grok researcher)
- CUDA 12.x (optional — for local GPU compute)
- Vast.ai account (optional — for burst compute)
- Discord webhook URL (optional — for live logging)

### Running the Coordinator (NVIDIA NeMo Agent Toolkit)

```bash
# Install the NeMo Agent Toolkit CLI
pip install nvidia-nat

# Set your NVIDIA API key (for NIM inference)
export NVIDIA_API_KEY="your_key_here"  # from build.nvidia.com

# Run the coordinator workflow
nat run --config_file coordinator/labclaw_workflow.yaml --input "analyze TCGA BRCA cohort"
```

### Running the Grok Researcher Agent

```bash
# Install grok-cli
bun add -g @vibe-kit/grok-cli

# Configure xAI API key
export XAI_API_KEY="your_key_here"

# Start Grok on the VM (interactive or autonomous)
grok --prompt "search bioRxiv for new neoantigen prediction datasets published this week and report findings"

# Or run with high tool-use depth for long autonomous sessions
grok --max-tool-rounds 200 --prompt "monitor EBI and GEO for new BRCA sequencing accessions and register to coordinator"
```

---

## Contributing

OpenCure Labs is an open-science project. Contributions are welcome from computational biologists, AI/ML engineers, and open science enthusiasts.

**Read the full guide: [CONTRIBUTING.md](CONTRIBUTING.md)**

Quick entry points:

- **Run a pipeline** — clone, run the neoantigen test, report what happened
- **Implement a skill** — pick an unimplemented skill from [LABCLAW.md](LABCLAW.md) and build it
- **Add a data connector** — integrate a new scientific database (OpenTargets, PubChem, etc.)
- **Improve scientific accuracy** — domain experts: review pipeline logic and open issues
- **Write tests** — add synthetic data test cases for existing skills
- **Documentation** — tutorials, worked examples, setup guides

Please open an issue before starting significant work so we can coordinate.

---

*OpenCure Labs — built in public, run by agents, reviewed by science.*

# Changelog

All notable changes to OpenCure Labs will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## 0.1.0 (2026-03-20)

### Feat

- Neoantigen prediction pipeline with MHC binding analysis
- LabClaw scientific skill layer with domain routing and guardrails
- TCGA, ClinVar, ChEMBL, and GEO data connectors
- Cancer, rare disease, and drug response agent configurations
- NeMo AgentIQ coordinator with labclaw_react workflow
- Claude Opus scientific critic and Grok literature reviewer
- Vast.ai burst GPU compute dispatcher
- Profile-driven static security scanner (ruff, bandit, pip-audit, detect-secrets)
- Pre-commit and post-commit hook pipeline (docs check, security scan, kanban, wiki sync)
- FastAPI dashboard with real-time agent monitoring
- Zellij terminal multiplexer control panel
- Discord webhook integration for agent logs and discovery feed *(removed in 0.3.0)*
- GitHub kanban board automation via post-commit hooks
- GitHub Wiki auto-sync from docs/
- PostgreSQL schema for agent runs, pipeline results, and critique logs
- Automated setup script with scientific model downloads
- CI pipeline with tests, ruff, and bandit
- Commitizen conventional commits enforcement

## v0.44.1 (2026-03-24)

### Fix

- **dashboard**: hide Vast.ai UI for local modes (1/3/6/12)

## v0.44.0 (2026-03-24)

### Feat

- **dashboard**: drop 100-batch mode; 1/3/6/12 run local, 999 is sole Vast.ai path

## v0.43.4 (2026-03-24)

### Fix

- **dashboard**: Alt+C reliably stops Genesis loop

## v0.43.3 (2026-03-24)

### Fix

- **compute**: improve Vast.ai host reliability and SSH robustness

## v0.43.2 (2026-03-24)

### Fix

- **compute**: seed pool from orphaned instances + retry stale offers

## v0.43.1 (2026-03-24)

### Fix

- **compute**: fall back to provisioning when a pool instance fails SSH

## v0.43.0 (2026-03-23)

### Feat

- **compute**: teardown Vast.ai pool instances at Genesis run end

## v0.42.4 (2026-03-23)

### Fix

- **compute**: persist instances across batches in continuous mode

## v0.42.3 (2026-03-23)

### Fix

- **compute**: raise provision wait timeout 300s→900s for RTX 5090 cold start

## v0.42.2 (2026-03-23)

### Fix

- **compute**: retry SSH check 3× before declaring instance dead

## v0.42.1 (2026-03-23)

### Fix

- **ci**: resolve ruff lint failures blocking CI

## v0.42.0 (2026-03-23)

### Feat

- LLM validation tests, Grok prompt fixes, CI gate

## v0.41.1 (2026-03-23)

### Fix

- reuse existing Vast.ai instances in genesis dispatch

## v0.41.0 (2026-03-23)

### Feat

- add log analyzer for pipeline error detection

## v0.40.5 (2026-03-23)

### Fix

- **security**: remove GitHub publisher — eliminates git push attack vector

## v0.40.4 (2026-03-23)

### Fix

- resolve AUTO_RESOLVE protein sequences via UniProt before dispatch

## v0.40.3 (2026-03-23)

### Fix

- skip local-data tasks (neoantigen/QC) in public database mode

## v0.40.2 (2026-03-23)

### Fix

- pre-public cleanup — remove hardcoded password, fix pyensembl releases

## v0.40.1 (2026-03-23)

### Fix

- **ci**: free disk space before GPU image build

## v0.40.0 (2026-03-23)

### Feat

- synthetic data isolation guardrail — block publishing of synthetic results

## v0.39.6 (2026-03-23)

### Fix

- parameterize pipeline tasks and add synthetic data fallbacks

## v0.39.5 (2026-03-22)

### Fix

- **ci**: bandit severity threshold to medium, disable fail-fast

## v0.39.4 (2026-03-22)

### Fix

- **ci**: add pytest-asyncio, fix lint errors, configure ruff per-file-ignores

## v0.39.3 (2026-03-22)

### Fix

- **ci**: pin deps + use uv to resolve pyarrow/dateutil conflicts

## v0.39.2 (2026-03-22)

### Fix

- rename Critiques to Reviews (Grok) in findings dashboard

## v0.39.1 (2026-03-22)

### Fix

- verify Ed25519 signature against raw body bytes

## v0.39.0 (2026-03-22)

### Feat

- add Ed25519 result signing and two-tier Grok review

### Refactor

- remove synthetic data generators from production code

## v0.38.3 (2026-03-22)

### Fix

- add vet data collection + gate synthetic fallback behind LABCLAW_ALLOW_SYNTHETIC

## v0.38.2 (2026-03-22)

### Fix

- Run All continuous mode + veterinary agent routing

## v0.38.1 (2026-03-22)

### Fix

- crash protection, heartbeat TTL, CUDA filtering, reviewer sweep

## v0.38.0 (2026-03-22)

### Feat

- 4-layer Vast.ai orphan protection — watchdog, self-destruct, budget floor, emergency stop

## v0.37.0 (2026-03-22)

### Feat

- sweep filters by contributor_id — only reviews your own results

## v0.36.2 (2026-03-22)

### Fix

- sweep loads .env for API keys + sets User-Agent to avoid Cloudflare 403

## v0.36.1 (2026-03-22)

### Fix

- remove misleading '3 agents' from Genesis banner — actual count chosen later

## v0.36.0 (2026-03-22)

### Feat

- Genesis mode now includes veterinary tasks (20 runs across 5 domains)

## v0.35.1 (2026-03-22)

### Fix

- move Run All to bottom of task submenu

## v0.35.0 (2026-03-22)

### Feat

- add Run All option to each domain's task submenu

## v0.34.1 (2026-03-22)

### Fix

- clear screen on Back to prevent stacking headers

## v0.34.0 (2026-03-22)

### Feat

- add ⬅ Back navigation + All Species option to research launcher

## v0.33.2 (2026-03-22)

### Fix

- Alt+S syntax error — heredoc can't chain with &&

## v0.33.1 (2026-03-22)

### Fix

- prevent orphaned Vast.ai instances on destroy failure

## v0.33.0 (2026-03-22)

### Feat

- species dashboard + reviewer sweep + Alt+S fix

## v0.32.3 (2026-03-22)

### Fix

- **config**: add vet skill keys to research_tasks.yaml distribution

## v0.32.2 (2026-03-22)

### Fix

- **task_generator**: remove duplicate RARE_DISEASE_VARIANTS, add canine/feline to DEFAULT_DISTRIBUTION

## v0.32.1 (2026-03-22)

### Fix

- **batch**: add canine/feline domain choices to dispatcher CLI

## v0.32.0 (2026-03-22)

### Feat

- **website**: species filter row + vet empty states + species badge on cards

## v0.31.0 (2026-03-22)

### Feat

- **r2/d1**: add species field to results pipeline

## v0.30.0 (2026-03-22)

### Feat

- **compute**: graceful shutdown, worker/pool improvements, MHC predictor fix

## v0.29.0 (2026-03-22)

### Feat

- **docker**: bake canine/feline Ensembl 112 annotations into GPU image

## v0.28.0 (2026-03-22)

### Feat

- multi-species support (dog/cat) — DLA/FLA MHC, OMIA, Ensembl VEP, NetMHCpan

## v0.27.0 (2026-03-22)

### Feat

- solo mode — private My Data analysis with opt-in R2 contribution

## v0.26.0 (2026-03-22)

### Feat

- publish Vast.ai batch results to R2 global dataset

## v0.25.0 (2026-03-22)

### Feat

- discovery feed website deployed to Cloudflare Pages

## v0.24.0 (2026-03-22)

### Feat

- Cloudflare R2+D1 global result store via ingest Worker

## v0.23.3 (2026-03-21)

### Fix

- obabel SMILES flag must be concatenated with -: (no space)

## v0.23.2 (2026-03-21)

### Fix

- restore closing triple-quote in __init__.py docstring

## v0.23.1 (2026-03-21)

### Fix

- restore closing bracket in pyproject.toml dev deps

## v0.23.0 (2026-03-21)

### Fix

- batch_id scoping, gnina→vina fallback, robust ligand prep, auto box center

## v0.21.1 (2026-03-21)

### Fix

- fully lazy imports in qsar.py, UniProt reviewed filter, AlphaFold loop break

## v0.21.0 (2026-03-21)

### Feat

- Docker image + auto-download data for reliable batch dispatch
- live progress during wait_for_ready
- **compute**: install from pre-built wheel instead of cloning full repo
- batch-scale Vast.ai dispatch — 100+ tasks across instance pool

### Fix

- AlphaFold fallback uses UniProt accession, lazy rdkit imports, wider error msgs
- graceful DB fallback on remote instances, increase stderr limit
- auto-import skill modules when registry is empty
- install pydantic+psycopg2+requests in onstart before wheel
- _poll_instance must unwrap Vast.ai {instances: {}} envelope
- lower requires-python to >=3.10 for Vast.ai compatibility
- sync pool_manager DB state against Vast.ai API on init
- **compute**: auto-attach SSH key to new Vast.ai instances
- **compute**: use valid wheel filename for pip install
- **vast**: register SSH key + harden onstart script
- validate batch inputs, cap tasks at 500 / instances at 20
- prompt batch count/pool size before Genesis confirmation
- eliminate SQL string construction in pool_manager (B608)

## v0.19.0 (2026-03-21)

### Feat

- Budget tab — live AI spend tracking across all providers

## v0.18.0 (2026-03-21)

### Feat

- pull budget from Vast.ai account balance instead of manual cap

## v0.17.0 (2026-03-21)

### Feat

- Genesis continuous loop with throughput chooser and .env sourcing

## v0.16.2 (2026-03-21)

### Fix

- make Genesis Mode run tasks sequentially instead of in parallel batches

## v0.16.1 (2026-03-21)

### Fix

- expose Pydantic args_schema to specialist tools so LLM sends correct field names

## v0.16.0 (2026-03-21)

### Feat

- Vast.ai instance monitoring + LABCLAW_COMPUTE env var

## v0.15.0 (2026-03-21)

### Feat

- Genesis Mode — run all 12 tasks across all domains

## v0.14.0 (2026-03-21)

### Feat

- Alt+c stop agents keybind + dashboard --reload mode

## v0.13.0 (2026-03-21)

### Feat

- **dashboard**: new logo — robot hand + DNA helix

## v0.12.1 (2026-03-21)

### Fix

- **dashboard**: clarify helpbar labels for Alt+s and Alt+x

## v0.12.0 (2026-03-21)

### Feat

- **agents**: track coordinator and specialist runs in database

## v0.11.2 (2026-03-21)

### Fix

- **dashboard**: remove auto-commit/push from shutdown

## v0.11.1 (2026-03-21)

### Fix

- **dashboard**: harden score_bar against dict/non-numeric scores

## v0.11.0 (2026-03-21)

### Feat

- **dashboard**: add continuous run mode to research launcher

## v0.10.0 (2026-03-21)

### Feat

- **dashboard**: add data mode, agent count, Vast.ai options to research launcher

## v0.9.0 (2026-03-21)

### Feat

- add follow-up prompts to research menu

## v0.8.0 (2026-03-21)

### Feat

- gum-powered interactive research menu (Alt+S)

## v0.7.2 (2026-03-21)

### Fix

- Zellij keybindings, dashboard score_bar, and stop.sh

## v0.7.1 (2026-03-20)

### Fix

- **zellij**: Alt+n switches tabs, add Alt+r research, fix helpbar

## v0.7.0 (2026-03-20)

### Feat

- add 88 tests (71% coverage), connection pooling, pin nvidia-nat

## v0.6.1 (2026-03-20)

### Fix

- **dashboard**: soften green (#57F287 → #3fb950), bust logo cache (/logo-v2.png)

## v0.6.0 (2026-03-20)

### Feat

- **dashboard**: add 5 D3.js interactive charts + new logo

## v0.5.0 (2026-03-20)

### Feat

- dashboard improvements, rate limiting, and deployment infrastructure

## v0.4.0 (2026-03-20)

### Feat

- **nat-plugin**: add schema hints, param normalization, and agent_run_id for orchestrator

## v0.3.1 (2026-03-20)

### Fix

- **qsar**: replace pickle with joblib — resolves Bandit B301

## v0.3.0 (2026-03-20)

### Feat

- production-grade hardening — rate limiting, DB indexes, expanded tests

## v0.20.0 (2026-03-21)

### Feat

- Docker image + auto-download data for reliable batch dispatch
- live progress during wait_for_ready
- **compute**: install from pre-built wheel instead of cloning full repo
- batch-scale Vast.ai dispatch — 100+ tasks across instance pool

### Fix

- graceful DB fallback on remote instances, increase stderr limit
- auto-import skill modules when registry is empty
- install pydantic+psycopg2+requests in onstart before wheel
- _poll_instance must unwrap Vast.ai {instances: {}} envelope
- lower requires-python to >=3.10 for Vast.ai compatibility
- sync pool_manager DB state against Vast.ai API on init
- **compute**: auto-attach SSH key to new Vast.ai instances
- **compute**: use valid wheel filename for pip install
- **vast**: register SSH key + harden onstart script
- validate batch inputs, cap tasks at 500 / instances at 20
- prompt batch count/pool size before Genesis confirmation
- eliminate SQL string construction in pool_manager (B608)

## v0.19.0 (2026-03-21)

### Feat

- Budget tab — live AI spend tracking across all providers

## v0.18.0 (2026-03-21)

### Feat

- pull budget from Vast.ai account balance instead of manual cap

## v0.17.0 (2026-03-21)

### Feat

- Genesis continuous loop with throughput chooser and .env sourcing

## v0.16.2 (2026-03-21)

### Fix

- make Genesis Mode run tasks sequentially instead of in parallel batches

## v0.16.1 (2026-03-21)

### Fix

- expose Pydantic args_schema to specialist tools so LLM sends correct field names

## v0.16.0 (2026-03-21)

### Feat

- Vast.ai instance monitoring + LABCLAW_COMPUTE env var

## v0.15.0 (2026-03-21)

### Feat

- Genesis Mode — run all 12 tasks across all domains

## v0.14.0 (2026-03-21)

### Feat

- Alt+c stop agents keybind + dashboard --reload mode

## v0.13.0 (2026-03-21)

### Feat

- **dashboard**: new logo — robot hand + DNA helix

## v0.12.1 (2026-03-21)

### Fix

- **dashboard**: clarify helpbar labels for Alt+s and Alt+x

## v0.12.0 (2026-03-21)

### Feat

- **agents**: track coordinator and specialist runs in database

## v0.11.2 (2026-03-21)

### Fix

- **dashboard**: remove auto-commit/push from shutdown

## v0.11.1 (2026-03-21)

### Fix

- **dashboard**: harden score_bar against dict/non-numeric scores

## v0.11.0 (2026-03-21)

### Feat

- **dashboard**: add continuous run mode to research launcher

## v0.10.0 (2026-03-21)

### Feat

- **dashboard**: add data mode, agent count, Vast.ai options to research launcher

## v0.9.0 (2026-03-21)

### Feat

- add follow-up prompts to research menu

## v0.8.0 (2026-03-21)

### Feat

- gum-powered interactive research menu (Alt+S)

## v0.7.2 (2026-03-21)

### Fix

- Zellij keybindings, dashboard score_bar, and stop.sh

## v0.7.1 (2026-03-20)

### Fix

- **zellij**: Alt+n switches tabs, add Alt+r research, fix helpbar

## v0.7.0 (2026-03-20)

### Feat

- add 88 tests (71% coverage), connection pooling, pin nvidia-nat

## v0.6.1 (2026-03-20)

### Fix

- **dashboard**: soften green (#57F287 → #3fb950), bust logo cache (/logo-v2.png)

## v0.6.0 (2026-03-20)

### Feat

- **dashboard**: add 5 D3.js interactive charts + new logo

## v0.5.0 (2026-03-20)

### Feat

- dashboard improvements, rate limiting, and deployment infrastructure

## v0.4.0 (2026-03-20)

### Feat

- **nat-plugin**: add schema hints, param normalization, and agent_run_id for orchestrator

## v0.3.1 (2026-03-20)

### Fix

- **qsar**: replace pickle with joblib — resolves Bandit B301

## v0.3.0 (2026-03-20)

### Feat

- production-grade hardening — rate limiting, DB indexes, expanded tests

## v0.2.0 (2026-03-20)

### Feat

- hierarchical multi-agent architecture with post-execution orchestration

## v0.1.0 (2026-03-20)

### Feat

- add versioning, commit enforcement, and dev workflow improvements
- wiki auto-sync + labclaw_react workflow + close issues #31-#35
- pre-commit docs check + post-commit kanban updater refs #35
- dual Discord webhooks — #agent-logs (LabClaw) + #results (Discovery Feed) *(removed in 0.3.0)*
- add 3 clickable tabs, status bar hints, Alt+q quit, fix python3
- replace tmux with Zellij for lab control panel
- add VS Code Tunnel setup script for remote access
- Codespaces devcontainer, CI pipeline, opencure burst CLI
- **eval**: end-to-end coordinator eval mode (#30)
- **pipelines**: add pipeline orchestration scripts (#29)
- **tests**: comprehensive integration test suite for all skills and connectors (#27)
- **dashboard**: WebSocket live updates, filters, export endpoints (#16)
- add reviewer wrappers, Vast.ai dispatcher, PDF publisher (#25, #28)
- **skills**: implement structure, docking, QSAR, pathogenicity, QC, reports (#17-#21, #15)
- **connectors**: implement TCGA/GEO, ChEMBL, ClinVar/OMIM connectors (#22, #23, #24)
- switch coordinator LLM to Gemini 2.0 Flash-Lite — closes #26
- add mouse support, quit button, keyboard shortcuts to tmux
- auto-start web dashboard in lab.sh
- add findings CLI and localhost dashboard
- add tmux control panel (lab.sh) and shutdown script (stop.sh)
- implement real neoantigen prediction pipeline
- implement agentiq_labclaw package — skills, guardrails, DB, publishers, connectors
- initial OpenCure Labs bootstrap

### Fix

- replace deprecated @app.on_event with lifespan context manager
- UnboundLocalError for _ws_clients in WebSocket broadcast
- move help bar to external script to avoid KDL parse errors
- python→python3 in dashboard launcher, add descriptive help bar
- resolve numpy/pyarrow version conflicts, install nvidia-nat 1.5.0
- remove sudo from lab.sh warnings, suppress list-sessions noise
- use zellij -s (create session) instead of --session (attach)
- pin pyarrow>=17.0 for numpy 2.x ABI compatibility
- add missing runtime deps to requirements.txt, fix setup.sh install order
- add version param to SSHD devcontainer feature
- pre-install numpy<2.0 before deps, add SSHD to devcontainer
- pin numpy<2.0 and skip test_full_pipeline without models
- suppress pip-audit spinner noise in pre-commit hook
- correct install instructions in README
- pane titles showing hostname instead of labels

### Refactor

- move lab.sh and stop.sh to dashboard/, update all refs
- move dashboard and findings CLI to dashboard/

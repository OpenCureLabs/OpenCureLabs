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
- Discord webhook integration for agent logs and discovery feed
- GitHub kanban board automation via post-commit hooks
- GitHub Wiki auto-sync from docs/
- PostgreSQL schema for agent runs, pipeline results, and critique logs
- Automated setup script with scientific model downloads
- CI pipeline with tests, ruff, and bandit
- Commitizen conventional commits enforcement

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
- dual Discord webhooks — #agent-logs (LabClaw) + #results (Discovery Feed)
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

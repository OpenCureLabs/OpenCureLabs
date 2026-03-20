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

# scripts/ — Operational Scripts

Utility scripts for setup, maintenance, CI, data ingestion, and Vast.ai
operations. **Application entrypoints live in [`dashboard/`](../dashboard/),
not here** — see the decision table below.

---

## Which script do I run?

| I want to… | Run this | Notes |
|---|---|---|
| Set up a fresh dev machine | [`scripts/setup.sh`](setup.sh) | Run with `sudo`. Adds packages, venv, models, Postgres. Idempotent. |
| Set up a production droplet | [`deploy/setup-droplet.sh`](../deploy/setup-droplet.sh) | DigitalOcean / Caddy / systemd path. |
| Launch the local control panel | [`dashboard/lab.sh`](../dashboard/lab.sh) | Zellij multi-pane session. |
| Start a research batch interactively | [`dashboard/run_research.sh`](../dashboard/run_research.sh) | Called automatically by the `MAIN` pane of `lab.sh`. |
| Run a one-off pipeline on my own file | [`scripts/solo_run.sh`](solo_run.sh) | Auto-detects VCF/FASTA/PDB/SDF/FASTQ. |
| Stop everything | [`dashboard/stop.sh`](../dashboard/stop.sh) | Kills the Zellij session + child workers. |
| Stop just the agent workers | [`dashboard/stop_agents.sh`](../dashboard/stop_agents.sh) | Leaves dashboard / Postgres alone. |
| Rotate / archive old logs | [`scripts/rotate_logs.sh`](rotate_logs.sh) | Safe to run from cron. `--dry-run` available. |
| Push a release | [`scripts/release.sh`](release.sh) | Commitizen-based version bump + tag. |
| Refresh parameter banks | [`scripts/refresh_param_banks.py`](refresh_param_banks.py) | Regenerate task seeds for the central queue. |
| Check param-bank drift (Python ⊆ TS) | [`scripts/check_param_bank_drift.py`](check_param_bank_drift.py) | Enforced in CI. Fails if Python adds entries not in `workers/ingest/tasks.ts`. |
| Seed the D1 task queue | [`scripts/seed_d1_queue.py`](seed_d1_queue.py) | Requires `OPENCURELABS_ADMIN_KEY`. |
| Backfill historical D1 / critiques | `scripts/backfill_*.py` | Maintenance — verify before running in prod. |
| Health-check the coordinator LLM | [`scripts/llm_health_check.py`](llm_health_check.py) | Quick sanity check on `GENAI_API_KEY`. |
| Analyse a failed run log | [`scripts/log_analyzer.py`](log_analyzer.py) | Pattern-matches known failure modes. |
| Watchdog Vast.ai instances | [`scripts/vast_watchdog.sh`](vast_watchdog.sh) | Idle-detect + auto-stop. |
| Sync the GitHub wiki | [`scripts/sync-wiki.sh`](sync-wiki.sh) | Triggered by the post-commit hook. |

---

## Git hooks (do not invoke directly)

| File | Hook | Purpose |
|---|---|---|
| [`pre-commit-docs-check.sh`](pre-commit-docs-check.sh) | pre-commit | Blocks commits that change code without touching docs when required. |
| [`commit-msg-hook.sh`](commit-msg-hook.sh) | commit-msg | Enforces Commitizen conventional-commit format. |
| [`post-commit-kanban.sh`](post-commit-kanban.sh) | post-commit | Updates the GitHub Project kanban board. |

The security pre-commit gate is installed separately by
[`scripts/setup.sh`](setup.sh) and lives at
[`security/pre-commit-hook.sh`](../security/pre-commit-hook.sh). **Never use
`git commit --no-verify`** — see
[`CONTRIBUTING.md`](../CONTRIBUTING.md#never-bypass-the-security-gate).

---

## Cron / systemd recommendations

```cron
# Daily log rotation at 03:30 UTC
30 3 * * *  cd /root/opencurelabs && bash scripts/rotate_logs.sh >> logs/rotate.log 2>&1
```

For production deployments the reviewer sweep, refresh, and dispatcher run as
systemd units — see [`deploy/`](../deploy/) for the unit files.

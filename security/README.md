# OpenCure Labs Security Scanner

Pre-commit static analysis gate. Blocks commits on CRITICAL or HIGH findings.

## Quick Start

```bash
# Run full scan:
python security/security_scan.py --profile security/profiles/opencurelabs.yaml

# Scan with auto-fix:
python security/security_scan.py --profile security/profiles/opencurelabs.yaml --autofix safe

# Save baseline:
python security/security_scan.py --profile security/profiles/opencurelabs.yaml \
  --baseline-save security/baselines/initial.json

# Compare against baseline:
python security/security_scan.py --profile security/profiles/opencurelabs.yaml \
  --baseline-compare security/baselines/initial.json

# With Discord notification (requires DISCORD_WEBHOOK_URL in .env):
python security/security_scan.py --profile security/profiles/opencurelabs.yaml --discord
```

## Architecture

```
security_scan.py
│
├── Ruff           — code quality linting
├── Bandit         — security-focused static analysis
├── pip-audit      — dependency vulnerability scanning
├── detect-secrets — hardcoded secret detection
│
├── Auto-Fix       — Tier 1 safe fixes (ruff --fix)
├── Reporting      — Markdown + JSON reports
├── Baseline       — Drift detection between scans
└── Discord        — Webhook notification on CRITICAL/HIGH
```

## Pre-Commit Hook

The scanner runs automatically before every `git commit`. Install:

```bash
cp security/pre-commit-hook.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

The hook:
- Runs all 4 static analysis tools
- Auto-fixes safe Tier 1 issues (ruff lint)
- **Blocks the commit** if grade is D or F (any CRITICAL or HIGH findings)
- Posts to Discord if `DISCORD_WEBHOOK_URL` is set

To bypass in an emergency: `git commit --no-verify`

## Flags

| Flag | Description |
|---|---|
| `--profile PATH` | **Required.** YAML scan profile |
| `--autofix {safe,low,none}` | Auto-fix mode (default: `none`) |
| `--baseline-save PATH` | Save results as baseline JSON |
| `--baseline-compare PATH` | Compare results against saved baseline |
| `--discord` | Send Discord notification on CRITICAL/HIGH |

## Grading

| Grade | Criteria |
|---|---|
| A+ | No findings |
| A | INFO-only findings |
| B | LOW findings only |
| C | 1-3 MEDIUM or 6+ LOW |
| D | HIGH findings or 4+ MEDIUM |
| F | Any CRITICAL finding |

## Auto-Fix Tiers

| Tier | Category | Action |
|---|---|---|
| **Tier 1** (safe) | Ruff lint issues | Auto-fixed with `--autofix safe` |
| **Tier 2** (human) | Bandit, Dependencies, Secrets | Never auto-fixed — requires manual review |

## Directory Structure

```
security/
├── README.md                 # This file
├── security_scan.py          # Static analysis scanner
├── pre-commit-hook.sh        # Git pre-commit hook
├── profiles/
│   └── opencurelabs.yaml     # Scan profile
└── reports/                  # Generated reports (gitignored)
```

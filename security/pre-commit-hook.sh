#!/usr/bin/env bash
# OpenCure Labs — Pre-commit gate
# Runs documentation check + security scan before allowing commits.
# Install: cp security/pre-commit-hook.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SCANNER="${SCRIPT_DIR}/security/security_scan.py"
PROFILE="${SCRIPT_DIR}/security/profiles/opencurelabs.yaml"
DOCS_CHECK="${SCRIPT_DIR}/scripts/pre-commit-docs-check.sh"

# ── Step 1: Documentation check ─────────────────────────────────────────────
if [[ -f "$DOCS_CHECK" ]]; then
    bash "$DOCS_CHECK"
else
    echo "⚠️  Documentation checker not found, skipping."
fi

# ── Step 2: Fast test gate ────────────────────────────────────────────────────
# Runs unit tests (skipping integration/gpu) with fail-fast so broken code
# never enters the repo. Takes ~30s locally.
echo "🧪 Running fast test gate..."
PYTHON="${SCRIPT_DIR}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then PYTHON="python3"; fi
if "$PYTHON" -m pytest tests/ -x -q -m "not integration and not gpu" --tb=line --override-ini="addopts=" 2>/dev/null; then
    echo "✅ Tests passed."
else
    echo ""
    echo "❌ Tests failed — commit blocked."
    echo "   Run 'pytest -x --tb=short' to see the full failure."
    echo ""
    exit 1
fi

# ── Step 3: Security scan ────────────────────────────────────────────────────

if [[ ! -f "$SCANNER" ]]; then
    echo "⚠️  Security scanner not found at ${SCANNER}, skipping pre-commit check."
    exit 0
fi

if [[ ! -f "$PROFILE" ]]; then
    echo "⚠️  Scan profile not found at ${PROFILE}, skipping pre-commit check."
    exit 0
fi

echo "🛡️  Running OpenCure Labs security scan..."

# Collect staged files for targeted secret scanning (avoids full-repo scan hang)
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)
FILES_ARG=""
if [[ -n "$STAGED_FILES" ]]; then
    FILES_ARG="--files $STAGED_FILES"
fi

# Run scanner with auto-fix (safe tier only)
# --files passes only staged files to detect-secrets (fast, avoids hang)
# Redirect stderr to suppress pip-audit spinner noise in non-TTY contexts
# shellcheck disable=SC2086
if python3 "$SCANNER" --profile "$PROFILE" --autofix safe $FILES_ARG 2>/dev/null; then
    echo "✅ Security scan passed — commit allowed."
    exit 0
else
    echo ""
    echo "❌ Security scan failed (grade D or F)."
    echo "   CRITICAL or HIGH findings must be resolved before committing."
    echo "   Review the report in security/reports/ for details."
    echo ""
    echo "   To bypass in an emergency (NOT recommended):"
    echo "     git commit --no-verify"
    echo ""
    exit 1
fi

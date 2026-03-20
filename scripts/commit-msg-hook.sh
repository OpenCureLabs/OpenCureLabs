#!/usr/bin/env bash
# OpenCure Labs — Commit message linter (conventional commits)
# Installed by scripts/setup.sh alongside the pre-commit hook.
# Blocks commits that don't follow the conventional commits format.
# Bypass in emergencies: git commit --no-verify
set -euo pipefail

COMMIT_MSG_FILE="$1"

# Check if commitizen is available
if ! command -v cz &>/dev/null; then
    echo "⚠️  commitizen not installed — skipping commit message check"
    echo "   Install: pip install commitizen"
    exit 0
fi

# Validate commit message against conventional commits format
if ! cz check --commit-msg-file "$COMMIT_MSG_FILE" 2>/dev/null; then
    echo ""
    echo "❌ Commit message does not follow Conventional Commits format."
    echo ""
    echo "   Expected format:  type(scope): description"
    echo ""
    echo "   Types: feat, fix, docs, test, chore, refactor, ci, style, perf, build, revert"
    echo ""
    echo "   Examples:"
    echo "     feat: add structure prediction skill"
    echo "     fix: correct MHC binding threshold"
    echo "     docs: update QUICKSTART with GPU setup"
    echo "     chore: bump dependencies"
    echo ""
    echo "   To bypass (NOT recommended): git commit --no-verify"
    echo ""
    exit 1
fi

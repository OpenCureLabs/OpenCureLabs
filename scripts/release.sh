#!/usr/bin/env bash
# OpenCure Labs — Release Script
# Bumps version based on conventional commits, updates CHANGELOG.md, and tags.
#
# Usage:
#   bash scripts/release.sh              # auto-detect bump type from commits
#   bash scripts/release.sh --dry-run    # preview what would happen
#
# Requires: commitizen (pip install commitizen)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# Activate venv if available
if [[ -f "$PROJECT_DIR/.venv/bin/activate" ]]; then
    # shellcheck source=/dev/null
    source "$PROJECT_DIR/.venv/bin/activate"
fi

# Check commitizen is available
if ! command -v cz &>/dev/null; then
    echo "❌ commitizen not installed. Run: pip install commitizen"
    exit 1
fi

# Check for uncommitted changes
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "❌ Uncommitted changes detected. Commit or stash before releasing."
    exit 1
fi

DRY_RUN=""
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN="--dry-run" ;;
    esac
done

echo "══════════════════════════════════════════════════════════════"
echo "  OpenCure Labs — Release"
echo "══════════════════════════════════════════════════════════════"
echo ""

CURRENT_VERSION=$(cz version --project 2>/dev/null || echo "unknown")
echo "  Current version: $CURRENT_VERSION"
echo ""

if [[ -n "$DRY_RUN" ]]; then
    echo "  🔍 Dry run — no changes will be made"
    echo ""
    cz bump --dry-run --changelog 2>&1 || echo "  ℹ️  No version bump needed (no feat/fix commits since last tag)"
else
    echo "  🚀 Bumping version..."
    echo ""
    if cz bump --changelog --yes 2>&1; then
        NEW_VERSION=$(cz version --project 2>/dev/null || echo "unknown")
        echo ""
        echo "  ✅ Bumped: $CURRENT_VERSION → $NEW_VERSION"
        echo "  📝 CHANGELOG.md updated"
        echo "  🏷️  Tagged: v$NEW_VERSION"
        echo ""
        echo "  Next step: push to origin"
        echo "    git push origin main --tags"
    else
        echo ""
        echo "  ℹ️  No version bump needed (no feat/fix commits since last tag)"
    fi
fi

echo ""
echo "══════════════════════════════════════════════════════════════"

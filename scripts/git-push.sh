#!/usr/bin/env bash
# OpenCure Labs — Push wrapper with post-push kanban + wiki sync
#
# Use instead of bare `git push` to ensure GitHub project board and wiki
# are updated after a successful push.
#
# Usage:
#   bash scripts/git-push.sh              # pushes current branch
#   bash scripts/git-push.sh origin main  # passes args through
#
# Install as alias:
#   git config alias.ship '!bash scripts/git-push.sh'
#
# Then use: git ship
set -uo pipefail

# ── Colors ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
YELLOW='\033[0;33m'
NC='\033[0m'

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [[ -z "$REPO_ROOT" ]]; then
    echo -e "${RED}❌ Not inside a git repository.${NC}"
    exit 1
fi

# ── Step 1: Push ─────────────────────────────────────────────────────────────
echo -e "${CYAN}🚀 Pushing...${NC}"
if ! git push "$@"; then
    echo ""
    echo -e "${RED}❌ Push failed — kanban and wiki sync skipped.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Push successful.${NC}"

# ── Step 2: Kanban board sync ────────────────────────────────────────────────
KANBAN_SCRIPT="$REPO_ROOT/scripts/post-commit-kanban.sh"
if [[ -x "$KANBAN_SCRIPT" ]]; then
    echo ""
    bash "$KANBAN_SCRIPT" || true
else
    echo -e "${YELLOW}⚠️  Kanban sync script not found, skipping.${NC}"
fi

# ── Step 3: Wiki sync ───────────────────────────────────────────────────────
# The kanban script already calls sync-wiki.sh as its Phase 2,
# but if it was skipped above, run wiki sync directly.
WIKI_SCRIPT="$REPO_ROOT/scripts/sync-wiki.sh"
if [[ ! -x "$KANBAN_SCRIPT" && -x "$WIKI_SCRIPT" ]]; then
    echo ""
    bash "$WIKI_SCRIPT" || true
fi

echo ""
echo -e "${GREEN}✅ Push complete — kanban and wiki synced.${NC}"

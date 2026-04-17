#!/usr/bin/env bash
# OpenCure Labs — Post-commit GitHub kanban board updater
# Parses commit message for issue references and moves them on the project board.
#
# Supported patterns in commit messages:
#   closes #31       → moves issue #31 to Done
#   fixes #31        → moves issue #31 to Done
#   resolves #31     → moves issue #31 to Done
#   refs #31         → moves issue #31 to In Progress
#   wip #31          → moves issue #31 to In Progress
#   #31              → moves issue #31 to In Progress (bare reference)
#
# Install: cp scripts/post-commit-kanban.sh .git/hooks/post-commit && chmod +x .git/hooks/post-commit
set -uo pipefail

# ── Colors ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Config ───────────────────────────────────────────────────────────────────
ORG="OpenCureLabs"
REPO="OpenCureLabs"
PROJECT_NUMBER=1
PROJECT_ID="PVT_kwDOEAl0ns4BSKQY"
STATUS_FIELD="PVTSSF_lADOEAl0ns4BSKQYzg_xrMI"
TODO_ID="f75ad846"
IN_PROGRESS_ID="47fc9ee4"
DONE_ID="98236657"

# ── Check requirements ───────────────────────────────────────────────────────
if ! command -v gh &>/dev/null; then
    exit 0  # gh not available, skip silently
fi

if ! gh auth status &>/dev/null 2>&1; then
    exit 0  # not authenticated, skip silently
fi

# ── Parse commit message ─────────────────────────────────────────────────────
COMMIT_MSG=$(git log -1 --pretty=%B 2>/dev/null || true)

if [[ -z "$COMMIT_MSG" ]]; then
    exit 0
fi

# Extract issue numbers with their action keywords
DONE_ISSUES=()
PROGRESS_ISSUES=()

# Match: closes #N, fixes #N, resolves #N (case-insensitive)
while IFS= read -r num; do
    [[ -n "$num" ]] && DONE_ISSUES+=("$num")
done < <(echo "$COMMIT_MSG" | grep -oiE '(closes?|fixe?s?|resolved?s?)\s+#([0-9]+)' | grep -oE '[0-9]+')

# Match: refs #N, wip #N
while IFS= read -r num; do
    [[ -n "$num" ]] && PROGRESS_ISSUES+=("$num")
done < <(echo "$COMMIT_MSG" | grep -oiE '(refs?|wip)\s+#([0-9]+)' | grep -oE '[0-9]+')

# Match bare #N references (not already captured by closes/fixes/refs)
while IFS= read -r num; do
    [[ -n "$num" ]] || continue
    # Skip if already in DONE or PROGRESS lists
    skip=false
    for d in "${DONE_ISSUES[@]+"${DONE_ISSUES[@]}"}"; do
        [[ "$d" == "$num" ]] && skip=true && break
    done
    for p in "${PROGRESS_ISSUES[@]+"${PROGRESS_ISSUES[@]}"}"; do
        [[ "$p" == "$num" ]] && skip=true && break
    done
    [[ "$skip" == "false" ]] && PROGRESS_ISSUES+=("$num")
done < <(echo "$COMMIT_MSG" | grep -oE '#[0-9]+' | grep -oE '[0-9]+')

# ── Nothing to do? ──────────────────────────────────────────────────────────
if [[ ${#DONE_ISSUES[@]} -eq 0 && ${#PROGRESS_ISSUES[@]} -eq 0 ]]; then
    exit 0
fi

echo -e "${CYAN}📋 Updating kanban board...${NC}"

# ── Helper: find project item ID for an issue ────────────────────────────────
get_item_id() {
    local issue_num=$1
    local response
    response=$(gh api graphql -f query="
    {
      organization(login: \"$ORG\") {
        repository(name: \"$REPO\") {
          issue(number: $issue_num) {
            projectItems(first: 10) {
              nodes {
                id
                project { id }
              }
            }
          }
        }
      }
    }" 2>&1) || {
        echo -e "  ${YELLOW}⚠️${NC} #${issue_num}: GraphQL query failed" >&2
        return 1
    }

    # Surface GraphQL errors instead of silently returning empty
    if echo "$response" | jq -e '.errors' >/dev/null 2>&1; then
        local err_msg
        err_msg=$(echo "$response" | jq -r '.errors[0].message' 2>/dev/null || echo "unknown")
        echo -e "  ${YELLOW}⚠️${NC} #${issue_num}: GraphQL error — $err_msg" >&2
        return 1
    fi

    echo "$response" | jq -r ".data.organization.repository.issue.projectItems.nodes[] | select(.project.id == \"$PROJECT_ID\") | .id" 2>/dev/null
}

# ── Helper: move item to status ─────────────────────────────────────────────
move_item() {
    local item_id=$1
    local status_option_id=$2
    local status_name=$3
    local issue_num=$4

    if gh project item-edit \
        --project-id "$PROJECT_ID" \
        --id "$item_id" \
        --field-id "$STATUS_FIELD" \
        --single-select-option-id "$status_option_id" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} #${issue_num} → ${status_name}"
    else
        echo -e "  ${YELLOW}⚠️${NC} #${issue_num} → failed to update"
    fi
}

# ── Process done issues ─────────────────────────────────────────────────────
for num in "${DONE_ISSUES[@]+"${DONE_ISSUES[@]}"}"; do
    ITEM_ID=$(get_item_id "$num")
    if [[ -n "$ITEM_ID" ]]; then
        move_item "$ITEM_ID" "$DONE_ID" "Done" "$num"
    else
        echo -e "  ${YELLOW}⚠️${NC} #${num} not found on kanban board"
    fi
done

# ── Process in-progress issues ───────────────────────────────────────────────
for num in "${PROGRESS_ISSUES[@]+"${PROGRESS_ISSUES[@]}"}"; do
    ITEM_ID=$(get_item_id "$num")
    if [[ -n "$ITEM_ID" ]]; then
        move_item "$ITEM_ID" "$IN_PROGRESS_ID" "In Progress" "$num"
    else
        echo -e "  ${YELLOW}⚠️${NC} #${num} not found on kanban board"
    fi
done

echo -e "${CYAN}📋 Kanban update complete.${NC}"

# ── Phase 2: Wiki sync ───────────────────────────────────────────────────────
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
WIKI_SYNC="${REPO_ROOT}/scripts/sync-wiki.sh"
if [[ -n "$REPO_ROOT" && -x "$WIKI_SYNC" ]]; then
    "$WIKI_SYNC" || true  # Don't fail the hook if wiki sync fails
fi

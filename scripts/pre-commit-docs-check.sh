#!/usr/bin/env bash
# OpenCure Labs — Pre-commit documentation gate
# Ensures that code changes are accompanied by documentation updates.
#
# Rules:
#   1. New/modified Python files → must have corresponding doc updates OR
#      a commit message containing "docs:", "refactor:", "fix:", "chore:", or "test:"
#   2. New skills/ or pipelines/ changes → docs/SKILLS.md or docs/ must be touched
#   3. .env.example changes → docs/QUICKSTART.md must be touched
#   4. Database schema changes → docs/DATABASE.md must be touched
#
# Exempt prefixes in commit message (checked via $1 or .git/COMMIT_EDITMSG):
#   docs:, fix:, chore:, test:, refactor:, ci:, style:, wip
set -euo pipefail

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
NC='\033[0m'

# ── Get staged files ─────────────────────────────────────────────────────────
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)

if [[ -z "$STAGED_FILES" ]]; then
    exit 0
fi

# ── Check for exempt commit message prefixes ─────────────────────────────────
# In pre-commit hook, the commit message isn't available yet.
# We check COMMIT_EDITMSG if it exists (from commit -m) or skip this check.
COMMIT_MSG_FILE="${GIT_DIR:-.git}/COMMIT_EDITMSG"
EXEMPT=false
if [[ -f "$COMMIT_MSG_FILE" ]]; then
    FIRST_LINE=$(head -1 "$COMMIT_MSG_FILE" 2>/dev/null || true)
    if echo "$FIRST_LINE" | grep -qiE '^(docs:|fix:|chore:|test:|refactor:|ci:|style:|wip)'; then
        EXEMPT=true
    fi
fi

if [[ "$EXEMPT" == "true" ]]; then
    echo -e "${GREEN}📝 Commit type exempt from doc check.${NC}"
    exit 0
fi

# ── Categorize staged files ──────────────────────────────────────────────────
HAS_CODE=false
HAS_DOCS=false
HAS_SKILLS=false
HAS_PIPELINES=false
HAS_ENV_EXAMPLE=false
HAS_SCHEMA=false
HAS_SKILLS_DOC=false
HAS_QUICKSTART_DOC=false
HAS_DATABASE_DOC=false
WARNINGS=()

while IFS= read -r file; do
    case "$file" in
        docs/*|*.md|CLAUDE.md|LABCLAW.md)
            HAS_DOCS=true
            [[ "$file" == "docs/SKILLS.md" ]] && HAS_SKILLS_DOC=true
            [[ "$file" == "docs/QUICKSTART.md" ]] && HAS_QUICKSTART_DOC=true
            [[ "$file" == "docs/DATABASE.md" ]] && HAS_DATABASE_DOC=true
            ;;
        *.py|*.yaml|*.yml)
            HAS_CODE=true
            ;;
    esac

    case "$file" in
        skills/*) HAS_SKILLS=true ;;
        pipelines/*) HAS_PIPELINES=true ;;
        .env.example) HAS_ENV_EXAMPLE=true ;;
        db/schema.sql|db/migrations/*) HAS_SCHEMA=true ;;
    esac
done <<< "$STAGED_FILES"

# ── Validation rules ────────────────────────────────────────────────────────

# Rule 1: Code changes should include doc updates for features
if [[ "$HAS_CODE" == "true" && "$HAS_DOCS" == "false" ]]; then
    WARNINGS+=("Code files changed but no documentation updated.")
fi

# Rule 2: Skills/pipelines changes need docs/SKILLS.md
if [[ "$HAS_SKILLS" == "true" && "$HAS_SKILLS_DOC" == "false" ]]; then
    WARNINGS+=("skills/ changed but docs/SKILLS.md not updated.")
fi

# Rule 3: .env.example changes need docs/QUICKSTART.md
if [[ "$HAS_ENV_EXAMPLE" == "true" && "$HAS_QUICKSTART_DOC" == "false" ]]; then
    WARNINGS+=("'.env.example' changed but docs/QUICKSTART.md not updated.")
fi

# Rule 4: Schema changes need docs/DATABASE.md
if [[ "$HAS_SCHEMA" == "true" && "$HAS_DATABASE_DOC" == "false" ]]; then
    WARNINGS+=("Database schema changed but docs/DATABASE.md not updated.")
fi

# ── Output ───────────────────────────────────────────────────────────────────
if [[ ${#WARNINGS[@]} -gt 0 ]]; then
    echo ""
    echo -e "${YELLOW}📝 Documentation Review${NC}"
    echo -e "${YELLOW}───────────────────────${NC}"
    for w in "${WARNINGS[@]}"; do
        echo -e "  ${YELLOW}⚠️  $w${NC}"
    done
    echo ""
    echo -e "  ${YELLOW}Consider updating relevant docs before committing.${NC}"
    echo -e "  ${YELLOW}Use a commit prefix (docs:, fix:, chore:, test:, refactor:)${NC}"
    echo -e "  ${YELLOW}to skip this check for non-feature commits.${NC}"
    echo ""
    # Warning only — don't block the commit
    # Change 'exit 0' to 'exit 1' to enforce strictly
    exit 0
else
    echo -e "${GREEN}📝 Documentation check passed.${NC}"
    exit 0
fi

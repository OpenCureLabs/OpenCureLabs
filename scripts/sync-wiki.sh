#!/usr/bin/env bash
# OpenCure Labs — Wiki sync: docs/ → GitHub Wiki
#
# Copies and sanitizes docs/ markdown files into the .wiki/ git repo,
# then commits and pushes to the wiki.
#
# Usage:
#   ./scripts/sync-wiki.sh          # full sync
#   ./scripts/sync-wiki.sh --check  # dry-run: show what would change
#
# The wiki repo is cloned to .wiki/ at the project root (gitignored).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WIKI_DIR="$REPO_ROOT/.wiki"
WIKI_REMOTE="https://github.com/OpenCureLabs/OpenCureLabs.wiki.git"
DRY_RUN=false

if [[ "${1:-}" == "--check" ]]; then
    DRY_RUN=true
fi

# ── Colors ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Clone wiki repo if not present ───────────────────────────────────────────
if [[ ! -d "$WIKI_DIR/.git" ]]; then
    if $DRY_RUN; then
        echo -e "${YELLOW}Wiki repo not cloned yet. Run without --check first.${NC}"
        exit 0
    fi
    echo -e "${CYAN}📖 Cloning wiki repo...${NC}"
    git clone "$WIKI_REMOTE" "$WIKI_DIR" 2>/dev/null || {
        echo -e "${YELLOW}⚠️  Wiki clone failed — is the wiki enabled on the repo?${NC}"
        exit 1
    }
fi

# ── Sanitization function ────────────────────────────────────────────────────
sanitize() {
    # Replace internal paths with generic placeholders
    sed \
        -e 's|/path/to/OpenCureLabs|/path/to/opencurelabs|g' \
        -e 's|postgresql://postgres:postgres@localhost:5433/opencurelabs|postgresql://user:pass@localhost:5432/opencurelabs|g' \
        -e 's|https://vscode.dev/tunnel/opencure-wsl/path/to/OpenCureLabs|https://vscode.dev/tunnel/<host>/<path>|g'
}

# ── Page mapping ─────────────────────────────────────────────────────────────
# Source file → Wiki page name
declare -A PAGE_MAP=(
    ["docs/QUICKSTART.md"]="Getting-Started.md"
    ["docs/ARCHITECTURE.md"]="Architecture.md"
    ["docs/API-REFERENCE.md"]="API-Reference.md"
    ["docs/SKILLS.md"]="Scientific-Skills.md"
    ["docs/DATABASE.md"]="Database-Schema.md"
    ["docs/DEVOPS.md"]="Operations.md"
    ["LABCLAW.md"]="LabClaw-Specification.md"
    ["CONTRIBUTING.md"]="Contributing.md"
)

# Files to exclude from wiki (internal agent context, env templates, etc.)
EXCLUDE_FILES=(
    "CLAUDE.md"
    ".env.example"
    "AGENT_INSTRUCTIONS.md"
)

# ── Generate Home.md from README ─────────────────────────────────────────────
generate_home() {
    local readme="$REPO_ROOT/README.md"
    if [[ ! -f "$readme" ]]; then
        echo "# OpenCure Labs" > "$WIKI_DIR/Home.md"
        return
    fi
    # Copy README but strip CI badge (internal) and add wiki note
    {
        echo "<!-- Auto-generated from README.md — do not edit directly -->"
        echo ""
        cat "$readme" | sanitize
    } > "$WIKI_DIR/Home.md"
}

# ── Generate _Sidebar.md ────────────────────────────────────────────────────
generate_sidebar() {
    cat > "$WIKI_DIR/_Sidebar.md" << 'SIDEBAR'
### OpenCure Labs Wiki

- **[Home](Home)**
- **[Getting Started](Getting-Started)**
- **[Architecture](Architecture)**
- **[LabClaw Specification](LabClaw-Specification)**

---

#### Reference
- [API Reference](API-Reference)
- [Scientific Skills](Scientific-Skills)
- [Database Schema](Database-Schema)
- [Operations](Operations)

---

#### Community
- [Contributing](Contributing)
- [GitHub](https://github.com/OpenCureLabs/OpenCureLabs)
- [Discord](https://discord.gg/opencurelabs)
SIDEBAR
}

# ── Sync pages ───────────────────────────────────────────────────────────────
sync_pages() {
    local changed=0

    # Process mapped files
    for src in "${!PAGE_MAP[@]}"; do
        local src_path="$REPO_ROOT/$src"
        local dest_name="${PAGE_MAP[$src]}"
        local dest_path="$WIKI_DIR/$dest_name"

        if [[ ! -f "$src_path" ]]; then
            echo -e "  ${YELLOW}⚠️  $src not found, skipping${NC}"
            continue
        fi

        # Generate sanitized content
        local content
        content=$(cat "$src_path" | sanitize)

        # Add auto-generated header
        local full_content
        full_content="<!-- Auto-generated from $src — do not edit directly -->"$'\n\n'"$content"

        # Compare with existing wiki page
        if [[ -f "$dest_path" ]]; then
            local existing
            existing=$(cat "$dest_path")
            if [[ "$full_content" == "$existing" ]]; then
                continue  # No changes
            fi
        fi

        if $DRY_RUN; then
            echo -e "  ${CYAN}→${NC} $src → $dest_name (would update)"
        else
            echo "$full_content" > "$dest_path"
            echo -e "  ${GREEN}✓${NC} $src → $dest_name"
        fi
        ((changed++)) || true
    done

    # Generate Home and Sidebar
    if ! $DRY_RUN; then
        generate_home
        generate_sidebar
        echo -e "  ${GREEN}✓${NC} Home.md (from README.md)"
        echo -e "  ${GREEN}✓${NC} _Sidebar.md"
    fi

    echo "$changed"
}

# ── Main ─────────────────────────────────────────────────────────────────────
echo -e "${CYAN}📖 Syncing docs/ → wiki...${NC}"

if $DRY_RUN; then
    echo -e "${YELLOW}Dry run — no changes will be made${NC}"
    sync_pages
    exit 0
fi

# Pull latest wiki
cd "$WIKI_DIR"
git pull --rebase --quiet 2>/dev/null || true

# Sync all pages
CHANGED=$(sync_pages)

# Commit and push if there are changes
cd "$WIKI_DIR"
git add -A
if git diff --cached --quiet; then
    echo -e "${CYAN}📖 Wiki already up to date.${NC}"
else
    git commit -m "sync: auto-update from docs/" --quiet
    git push --quiet 2>/dev/null && {
        echo -e "${GREEN}📖 Wiki pushed successfully.${NC}"
    } || {
        echo -e "${YELLOW}⚠️  Wiki push failed — check SSH access.${NC}"
    }
fi

#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  OpenCure Labs — VS Code Tunnel Setup
#  Sets up a persistent VS Code Tunnel so you can connect from anywhere
#  via https://vscode.dev/tunnel/<name>
#
#  Usage:   sudo bash scripts/tunnel-setup.sh [--name <tunnel-name>]
#
#  What this does:
#    1. Installs the VS Code CLI (if not present)
#    2. Authenticates via GitHub device flow (one-time)
#    3. Installs the tunnel as a systemd service (auto-starts on boot)
#
#  After setup:
#    - Open https://vscode.dev/tunnel/<name> from any browser
#    - Full VS Code with terminal, extensions, port forwarding
#    - Check status:  code tunnel status
#    - View logs:     code tunnel service log
#    - Stop:          code tunnel service uninstall
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Parse flags ──────────────────────────────────────────────────────────────
TUNNEL_NAME="opencure-wsl"
for arg in "$@"; do
    case "$arg" in
        --name) shift; TUNNEL_NAME="$1"; shift ;;
        --name=*) TUNNEL_NAME="${arg#*=}" ;;
    esac
done

# ── Colors ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✅ $1${NC}"; }
info() { echo -e "  ${BOLD}→${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠️  $1${NC}"; }

echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  OpenCure Labs — VS Code Tunnel Setup${NC}"
echo -e "${BOLD}  Tunnel name: ${BLUE}${TUNNEL_NAME}${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
echo ""

# ── Step 1: Install VS Code CLI ─────────────────────────────────────────────
CODE_BIN="/usr/local/bin/code"

if [[ -x "$CODE_BIN" ]] && "$CODE_BIN" tunnel --help &>/dev/null; then
    ok "VS Code CLI already installed: $CODE_BIN"
else
    info "Downloading VS Code CLI..."
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  CLI_ARCH="cli-linux-x64" ;;
        aarch64) CLI_ARCH="cli-linux-arm64" ;;
        armv7l)  CLI_ARCH="cli-linux-armhf" ;;
        *)       echo "Unsupported architecture: $ARCH"; exit 1 ;;
    esac

    curl -fsSL "https://update.code.visualstudio.com/latest/${CLI_ARCH}/stable" \
        -o /tmp/vscode-cli.tar.gz
    tar -xzf /tmp/vscode-cli.tar.gz -C /usr/local/bin
    rm /tmp/vscode-cli.tar.gz
    chmod +x "$CODE_BIN"
    ok "VS Code CLI installed: $CODE_BIN"
fi

# ── Step 2: Authenticate (interactive — requires GitHub device flow) ─────────
info "Checking tunnel authentication..."

# Try to get status — if it works, we're already authenticated
if "$CODE_BIN" tunnel status &>/dev/null 2>&1; then
    ok "Already authenticated"
else
    echo ""
    echo -e "${YELLOW}  You need to authenticate with GitHub (one-time).${NC}"
    echo -e "${YELLOW}  A browser URL and code will appear below.${NC}"
    echo -e "${YELLOW}  Open the URL, enter the code, and authorize.${NC}"
    echo ""
    "$CODE_BIN" tunnel --accept-server-license-terms --name "$TUNNEL_NAME" &
    TUNNEL_PID=$!

    # Wait for user to complete auth, then stop the foreground tunnel
    echo ""
    echo -e "  ${BOLD}Press Enter after you've completed GitHub authentication...${NC}"
    read -r
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
    ok "Authentication complete"
fi

# ── Step 3: Set tunnel name ──────────────────────────────────────────────────
info "Setting tunnel name to: $TUNNEL_NAME"
"$CODE_BIN" tunnel rename "$TUNNEL_NAME" 2>/dev/null || true
ok "Tunnel name set: $TUNNEL_NAME"

# ── Step 4: Install as system service ────────────────────────────────────────
info "Installing tunnel as system service..."

# Uninstall existing service (if any) to get a clean state
"$CODE_BIN" tunnel service uninstall 2>/dev/null || true

"$CODE_BIN" tunnel service install --accept-server-license-terms --name "$TUNNEL_NAME"
ok "Tunnel service installed"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  ✅ VS Code Tunnel is running!${NC}"
echo ""
echo -e "  ${BOLD}Connect from anywhere:${NC}"
echo -e "    ${BLUE}https://vscode.dev/tunnel/${TUNNEL_NAME}${NC}"
echo ""
echo -e "  ${BOLD}Commands:${NC}"
echo -e "    code tunnel status          — check tunnel status"
echo -e "    code tunnel service log     — view service logs"
echo -e "    code tunnel service uninstall — stop and remove service"
echo -e "    code tunnel rename <name>   — change tunnel name"
echo -e "${BOLD}══════════════════════════════════════════════════════════════${NC}"
echo ""

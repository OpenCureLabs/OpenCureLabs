#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  XPC Labs — tmux Control Panel
#  Launches the full XPC Labs environment in a single 6-pane tmux session.
#
#  Usage:  ./scripts/lab.sh          (from anywhere)
#          bash /root/xpc-labs/scripts/lab.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT="/root/xpc-labs"
SESSION="xpclabs"
LOGFILE="$PROJECT/logs/agent.log"
VENV="source $PROJECT/.venv/bin/activate"
PG_PORT=5433

# ── Dependency check ─────────────────────────────────────────────────────────
if ! command -v tmux &>/dev/null; then
    echo "[XPC Labs] tmux not found — installing..."
    apt-get update -qq && apt-get install -y -qq tmux
fi

# ── Ensure log file exists ───────────────────────────────────────────────────
mkdir -p "$PROJECT/logs"
touch "$LOGFILE"

# ── Ensure PostgreSQL is running ─────────────────────────────────────────────
if ! pg_isready -p "$PG_PORT" -q 2>/dev/null; then
    echo "[XPC Labs] Starting PostgreSQL on port $PG_PORT..."
    service postgresql start 2>/dev/null || true
    sleep 1
fi

# ── Reattach if session already exists ───────────────────────────────────────
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "[XPC Labs] Session '$SESSION' already running — reattaching."
    exec tmux attach-session -t "$SESSION"
fi

# ══════════════════════════════════════════════════════════════════════════════
#  Build 6-pane layout
#
#  ┌──────────────┬──────────────┐
#  │ COORDINATOR  │    GROK      │
#  ├──────────────┼──────────────┤
#  │    LOGS      │  POSTGRES    │
#  ├──────────────┼──────────────┤
#  │   SYSTEM     │   SHELL      │
#  └──────────────┴──────────────┘
# ══════════════════════════════════════════════════════════════════════════════

tmux new-session -d -s "$SESSION" -x 200 -y 50

# ── Prevent shells/programs from overriding pane titles ──────────────────────
tmux set-option -g -t "$SESSION" allow-rename off
tmux set-option -g -t "$SESSION" set-titles off

# ── Status bar theme ─────────────────────────────────────────────────────────
tmux set-option -t "$SESSION" status on
tmux set-option -t "$SESSION" status-position bottom
tmux set-option -t "$SESSION" status-style "bg=#1a1b26,fg=#7aa2f7"
tmux set-option -t "$SESSION" status-left-length 40
tmux set-option -t "$SESSION" status-right-length 60
tmux set-option -t "$SESSION" status-left  "#[fg=#1a1b26,bg=#7aa2f7,bold]  XPC Labs #[fg=#7aa2f7,bg=#3b4261] #[fg=#c0caf5,bg=#3b4261] #S #[fg=#3b4261,bg=#1a1b26] "
tmux set-option -t "$SESSION" status-right "#[fg=#3b4261,bg=#1a1b26]#[fg=#c0caf5,bg=#3b4261]  #(cd $PROJECT && git branch --show-current 2>/dev/null || echo 'n/a') #[fg=#7aa2f7,bg=#3b4261]#[fg=#1a1b26,bg=#7aa2f7,bold] %Y-%m-%d %H:%M "
tmux set-option -t "$SESSION" window-status-current-format "#[fg=#c0caf5,bg=#3b4261,bold] #W "
tmux set-option -t "$SESSION" window-status-format "#[fg=#565f89] #W "

# ── Pane borders ─────────────────────────────────────────────────────────────
tmux set-option -g pane-border-style "fg=#3b4261"
tmux set-option -g pane-active-border-style "fg=#7aa2f7"
tmux set-option -g pane-border-status top
tmux set-option -g pane-border-format "#[fg=#1a1b26,bg=#7aa2f7,bold] #{pane_index}: #{pane_title} #[default]"

# ── Reload keybinding: Ctrl+b R ──────────────────────────────────────────────
tmux bind-key -T prefix R source-file ~/.tmux.conf \; display-message "Config reloaded" 2>/dev/null || true
tmux bind-key -T prefix R run-shell "bash $PROJECT/scripts/lab.sh" \; display-message "XPC Labs reloaded"

# ── Window name ──────────────────────────────────────────────────────────────
tmux rename-window -t "$SESSION" "lab"

# ── Create panes and send commands ───────────────────────────────────────────

# Pane 0: COORDINATOR (top-left) — already exists from new-session
tmux send-keys -t "$SESSION:0.0" "cd $PROJECT && $VENV && clear && echo '── COORDINATOR ── ready for nat commands'" C-m

# Pane 1: GROK (top-right)
tmux split-window -h -t "$SESSION:0.0"
tmux send-keys -t "$SESSION:0.1" "cd $PROJECT/workspace && clear && echo '── GROK ── workspace ready'" C-m

# Pane 2: LOGS (middle-left)
tmux split-window -v -t "$SESSION:0.0"
tmux send-keys -t "$SESSION:0.2" "tail -f $LOGFILE" C-m

# Pane 3: POSTGRES (middle-right)
tmux split-window -v -t "$SESSION:0.1"
tmux send-keys -t "$SESSION:0.3" "watch -n 5 'psql -p $PG_PORT -d xpclabs -c \"SELECT id, agent_name, status, started_at FROM agent_runs ORDER BY started_at DESC LIMIT 10;\" 2>/dev/null || echo \"PostgreSQL not available on port $PG_PORT\"'" C-m

# Pane 4: SYSTEM (bottom-left)
tmux split-window -v -t "$SESSION:0.2"
tmux send-keys -t "$SESSION:0.4" "htop" C-m

# Pane 5: SHELL (bottom-right)
tmux split-window -v -t "$SESSION:0.3"
tmux send-keys -t "$SESSION:0.5" "cd $PROJECT && $VENV && clear && echo '── SHELL ── general purpose'" C-m

# ── Set pane titles AFTER commands to prevent shell overrides ────────────────
sleep 0.3
tmux select-pane -t "$SESSION:0.0" -T "COORDINATOR"
tmux select-pane -t "$SESSION:0.1" -T "GROK"
tmux select-pane -t "$SESSION:0.2" -T "LOGS"
tmux select-pane -t "$SESSION:0.3" -T "POSTGRES"
tmux select-pane -t "$SESSION:0.4" -T "SYSTEM"
tmux select-pane -t "$SESSION:0.5" -T "SHELL"

# ── Focus on COORDINATOR pane ────────────────────────────────────────────────
tmux select-pane -t "$SESSION:0.0"

# ── Attach ───────────────────────────────────────────────────────────────────
echo "[XPC Labs] Launching tmux session '$SESSION'..."
exec tmux attach-session -t "$SESSION"

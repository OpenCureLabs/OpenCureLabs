#!/usr/bin/env bash
# Wrapper: kill any existing run_research.sh panes, then exec into a new one.
# This script's name intentionally does NOT contain "run_research" so
# pgrep -f 'run_research.sh' won't match it before the exec.

for pid in $(pgrep -f 'run_research\.sh'); do
    [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null
done
sleep 0.3
exec bash "$(dirname "$0")/run_research.sh"

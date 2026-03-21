#!/usr/bin/env bash
# OpenCure Labs — Run Research Task (floating pane via Alt+R)
cd /root/opencurelabs || exit 1
source .venv/bin/activate 2>/dev/null

echo -e '\033[1;96m── Run Research Task ──\033[0m'
echo
read -rp 'Task: ' task

if [[ -z "$task" ]]; then
    echo -e '\033[91mNo task entered. Aborting.\033[0m'
    echo
    echo -e '\033[2mPress Enter to close\033[0m'
    read
    exit 0
fi

echo
echo -e "\033[93mRunning:\033[0m nat run --config_file coordinator/labclaw_workflow.yaml --input \"$task\""
echo
nat run --config_file coordinator/labclaw_workflow.yaml --input "$task" 2>&1 | tee -a logs/agent.log
echo
echo -e '\033[2mPress Enter to close\033[0m'
read

#!/bin/bash
# PostToolUse Hook - activity log
export PYTHONIOENCODING=utf-8
export LANG=en_US.UTF-8

INPUT=$(cat)

# Extract tool name, skip interactive tools
TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")
case "$TOOL_NAME" in
    AskUserQuestion|ExitPlanMode|EnterPlanMode|EnterWorktree|TaskCreate|TaskUpdate|TaskList|TaskGet|"")
        exit 0
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 0
echo "$INPUT" | python3 agent.py log-tool >/dev/null 2>/dev/null
exit 0

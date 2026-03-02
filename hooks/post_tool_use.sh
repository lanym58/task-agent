#!/bin/bash
# PostToolUse Hook - activity log
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# Find python command
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "")
[ -z "$PY" ] && { echo "{}"; exit 0; }

INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")
case "$TOOL_NAME" in
    AskUserQuestion|ExitPlanMode|EnterPlanMode|EnterWorktree|TaskCreate|TaskUpdate|TaskList|TaskGet|"")
        echo "{}"
        exit 0
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || { echo "{}"; exit 0; }
echo "$INPUT" | "$PY" agent.py log-tool >/dev/null 2>/dev/null
echo "{}"
exit 0

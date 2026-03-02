#!/bin/bash
# PostToolUse Hook - 异步活动日志记录
# 每次工具调用完成后触发，记录操作到 activity_log
INPUT=$(cat)

# 跳过交互类工具，这些工具不需要记录且可能引发 hook error
TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null)
case "$TOOL_NAME" in
    AskUserQuestion|ExitPlanMode|EnterPlanMode|"")
        exit 0
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 0
# 同时重定向 stdout 和 stderr，避免污染 hook 响应
echo "$INPUT" | python3 agent.py log-tool >/dev/null 2>/dev/null
exit 0

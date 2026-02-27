#!/bin/bash
# PostToolUse Hook - 异步活动日志记录
# 每次工具调用完成后触发，记录操作到 activity_log
# 不阻塞 Claude Code 执行
INPUT=$(cat)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 切换到 agent 目录以确保正确的工作目录
cd "$SCRIPT_DIR/.." || { echo "{}"; exit 0; }
echo "$INPUT" | python3 agent.py log-tool 2>/dev/null
# PostToolUse 钩子需要返回 JSON（即使是空的）
echo "{}"
exit 0

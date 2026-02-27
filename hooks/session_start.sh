#!/bin/bash
# SessionStart Hook - 断点续传上下文注入
# 每次 Claude Code 会话启动时自动触发
# 检测未完成任务，生成续传报告注入 Claude 上下文
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT="$SCRIPT_DIR/../agent.py"
# 切换到 agent 目录以确保正确的工作目录
cd "$SCRIPT_DIR/.." || exit 0
# 直接使用 python 生成 JSON 响应
python3 -c "
import sys
import subprocess
import json

# 获取 context 输出
result = subprocess.run([sys.executable, 'agent.py', 'context'], capture_output=True, text=True)
output = result.stdout.strip()

if output:
    print(json.dumps({'inject': output}))
else:
    print('{}')
" 2>/dev/null
exit 0

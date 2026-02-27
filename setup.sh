#!/bin/bash
# Task Agent 一键安装部署脚本
set -e

# Fix encoding for Windows (Git Bash)
export PYTHONIOENCODING=utf-8

AGENT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(pwd)"

echo "══════════════════════════════════════════════════"
echo "  Task Agent 安装部署"
echo "══════════════════════════════════════════════════"

# 1. 创建数据目录
echo "→ 创建数据目录 ~/.task-agent/"
mkdir -p ~/.task-agent

# 2. 设置脚本可执行权限
echo "→ 设置可执行权限"
chmod +x "$AGENT_DIR/agent.py"
chmod +x "$AGENT_DIR/hooks/"*.sh

# 3. 创建 agent 命令链接
echo "→ 创建 agent 命令链接"
mkdir -p ~/.local/bin
ln -sf "$AGENT_DIR/agent.py" ~/.local/bin/agent

# 4. 确保 ~/.local/bin 在 PATH 中
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    echo "→ 添加 ~/.local/bin 到 PATH"
    SHELL_RC=""
    if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "$(which zsh 2>/dev/null)" ]; then
        SHELL_RC="$HOME/.zshrc"
    else
        SHELL_RC="$HOME/.bashrc"
    fi
    if [ -n "$SHELL_RC" ] && ! grep -q 'export PATH="$HOME/.local/bin:$PATH"' "$SHELL_RC" 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
        echo "  已添加到 $SHELL_RC"
    fi
    export PATH="$HOME/.local/bin:$PATH"
fi

# 5. 配置 Claude Code Hooks
echo "→ 配置 Claude Code Hooks"
CLAUDE_SETTINGS_DIR="$PROJECT_DIR/.claude"
CLAUDE_SETTINGS="$CLAUDE_SETTINGS_DIR/settings.local.json"
mkdir -p "$CLAUDE_SETTINGS_DIR"

# Use python to merge hooks into existing settings
# Use environment variables to avoid encoding issues with Chinese paths
CLAUDE_SETTINGS_PATH="$CLAUDE_SETTINGS" AGENT_DIR_PATH="$AGENT_DIR" python3 -c "
import json, os

settings_path = os.environ['CLAUDE_SETTINGS_PATH']
agent_dir = os.environ['AGENT_DIR_PATH']

hooks_config = {
    'hooks': {
        'SessionStart': [
            {
                'matcher': '*',
                'hooks': [
                    {
                        'type': 'command',
                        'command': os.path.join(agent_dir, 'hooks', 'session_start.sh')
                    }
                ]
            }
        ],
        'PostToolUse': [
            {
                'matcher': '*',
                'hooks': [
                    {
                        'type': 'command',
                        'command': os.path.join(agent_dir, 'hooks', 'post_tool_use.sh')
                    }
                ]
            }
        ]
    }
}

# Load existing settings if present
settings = {}
if os.path.exists(settings_path):
    with open(settings_path, 'r', encoding='utf-8') as f:
        settings = json.load(f)

# Merge hooks (preserve existing hooks, add ours)
if 'hooks' not in settings:
    settings['hooks'] = {}

for hook_type, hook_list in hooks_config['hooks'].items():
    if hook_type not in settings['hooks']:
        settings['hooks'][hook_type] = []
    # Check if our hook is already there (extract command from nested hooks)
    existing_cmds = []
    for entry in settings['hooks'][hook_type]:
        if 'hooks' in entry:
            for h in entry['hooks']:
                if 'command' in h:
                    existing_cmds.append(h['command'])
    for hook_entry in hook_list:
        if 'hooks' in hook_entry:
            for h in hook_entry['hooks']:
                if 'command' in h and h['command'] not in existing_cmds:
                    settings['hooks'][hook_type].append(hook_entry)
                    break

with open(settings_path, 'w', encoding='utf-8') as f:
    json.dump(settings, f, indent=2)

print('  Hooks 配置已写入:', settings_path)
"

# 6. 初始化数据库
echo "→ 初始化数据库"
python3 "$AGENT_DIR/agent.py" init

# 7. 验证安装
echo ""
echo "══════════════════════════════════════════════════"
echo "  ✅ 安装完成!"
echo "══════════════════════════════════════════════════"
echo ""
echo "  命令位置: $(which agent 2>/dev/null || echo ~/.local/bin/agent)"
echo "  数据库:   {项目目录}/.task-agent/{git用户名}/tasks.db"
echo "  Hooks:    已配置 SessionStart + PostToolUse"
echo ""
echo "  快速开始:"
echo "    agent status              # 查看状态"
echo '    agent task new "任务标题"   # 创建任务'
echo "    agent resume              # 断点续传"
echo ""

# Run status check
agent status 2>/dev/null || python3 "$AGENT_DIR/agent.py" status

# Task Agent - 智能体任务追踪系统

> 为 AI 编程助手设计的任务管理工具 - 支持断点续传、进度追踪和自动化工作流

[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

Task Agent 是一个专为 AI 编程助手（如 Claude Code）设计的任务追踪系统。通过优雅的 Hook 机制，实现会话断点续传、任务进度管理和自动化里程碑记录，让 AI 协作开发更加高效可靠。

## ✨ 核心特性

### 🔄 断点续传
- 会话中断后自动恢复上下文，无缝继续未完成的工作
- SessionStart Hook 自动检测未完成任务并注入续传报告
- 智能识别当前进行中的步骤和待办事项

### 📋 任务管理
- 创建、查看、更新、删除任务
- 将复杂任务拆分为可管理的步骤
- 实时进度追踪（任务级 + 步骤级）
- 多状态支持：pending、in_progress、completed、failed、cancelled、skipped

### 📝 活动日志
- PostToolUse Hook 自动记录每次工具操作
- 追踪工作轨迹，便于回顾和调试
- 异步记录，不阻塞 AI 执行流程

### 🎯 里程碑系统
- `xiaocheng` 一键提交 + 推送 + 记录里程碑
- 自动统计代码变更（文件数、增删行数）
- Git commit hash 和分支信息关联
- 里程碑历史查询

### 🔧 零依赖
- 纯 Python 实现，仅使用标准库
- SQLite 数据存储，轻量可靠
- 单文件架构，易于部署和维护

## 🚀 快速开始

### 环境要求

- Python 3.7+
- Git（用于里程碑功能和项目识别）
- Bash 兼容环境（Git Bash / WSL / Linux / macOS）

### 安装

> **重要：必须在目标项目目录下执行安装命令！**
>
> Hooks 配置会写入**当前工作目录**的 `.claude/settings.local.json`

```bash
# 1. 进入你的项目目录
cd /your/project

# 2. 执行安装脚本
bash E:/ProjectCode/2026/AI开发/agents/task-agent/setup.sh
```

安装脚本会自动：
1. 创建 `~/.task-agent/` 数据目录
2. 链接 `agent` 命令到 `~/.local/bin/`
3. 配置 Claude Code Hooks（SessionStart + PostToolUse）
4. 初始化 SQLite 数据库
5. 自动添加 `~/.local/bin` 到 PATH（如需要）

### 验证安装

```bash
# 查看 agent 命令位置
which agent  # 应该显示 ~/.local/bin/agent

# 查看当前状态
agent status
```

## 安装

> **重要：必须在目标项目目录下执行安装命令！**
>
> Hooks 配置会写入**当前工作目录**的 `.claude/settings.local.json`，所以请先 `cd` 到你的项目目录。

```bash
# 1. 进入你的项目目录
cd /your/project

# 2. 执行安装脚本
bash E:/ProjectCode/2026/AI开发/agents/task-agent/setup.sh
```

安装脚本会自动：
1. 创建 `~/.task-agent/` 数据目录
2. 链接 `agent` 命令到 `~/.local/bin/`
3. 配置 Claude Code Hooks（SessionStart + PostToolUse）
4. 初始化 SQLite 数据库

## 📖 使用指南

### 基本工作流

```bash
# 1. 创建任务
agent task new "重构用户认证模块" -d "将session认证迁移到JWT"

# 2. 添加步骤
agent step batch 1 "分析现有认证代码" "设计JWT认证方案" "实现Token刷新" "编写单元测试"

# 3. 执行步骤
agent step start 1
# ... 工作中 ...
agent step progress 1 50 -s "已分析2个核心文件"
agent step done 1 -s "梳理了3个核心认证文件"

# 4. 继续下一步
agent step start 2
agent step progress 2 60 -s "完成middleware编写"

# [会话中断 → 重新启动 Claude Code → 自动恢复上下文]

# 5. 完成任务
agent task done 1 -s "JWT认证迁移完成"
```

### 小成（里程碑）工作流

```bash
# 完成一个重要阶段后
agent xiaocheng -m "完成JWT认证基础实现"

# 这将自动：
# 1. Git add + commit 所有变更
# 2. Push 到远程仓库
# 3. 记录里程碑（包含 commit hash、分支、变更统计）
# 4. 归档当前任务
```

### 断点续传

当 Claude Code 会话重新启动时，SessionStart Hook 会自动：
1. 检测未完成的任务
2. 生成续传报告
3. 注入到 Claude 上下文中

你也可以手动查看续传信息：

```bash
agent resume
```

输出示例：
```
═══════════════════════════════════════
  Task #1: 重构用户认证模块
  状态: in_progress | 整体进度: 50%
───────────────────────────────────────
### 已完成的步骤:
1. ✅ 分析现有认证代码 [100%]
   摘要: 梳理了3个核心认证文件

### 当前进度中:
2. 🔄 设计JWT认证方案 [60%]
   摘要: 完成middleware编写

### 待完成的步骤:
3. ⬜ 实现Token刷新 [0%]
4. ⬜ 编写单元测试 [0%]

### 继续指引:
请继续完成 Step 2 (设计JWT认证方案) 的剩余工作。
完成后执行: agent step done 2 -s "完成摘要"
```

## 📚 命令参考

### 快捷命令

| 命令 | 说明 |
|------|------|
| `agent resume` | 生成断点续传报告 |
| `agent restart` | 归档当前任务，重新开始 |
| `agent xiaocheng -m "总结"` | 小成：提交+推送+里程碑+归档 |
| `agent status` | 当前活跃任务概览 |
| `agent log [task_id]` | 查看活动日志 |
| `agent milestones` | 查看里程碑历史 |

### 任务管理

| 命令 | 说明 |
|------|------|
| `agent task new "标题" [-d 描述]` | 创建新任务 |
| `agent task list [--status 状态]` | 列出任务（默认显示活跃任务） |
| `agent task show <id>` | 查看任务详情 |
| `agent task done <id> [-s 总结]` | 完成任务 |
| `agent task fail <id> [-s 原因]` | 标记任务失败 |
| `agent task cancel <id>` | 取消任务 |
| `agent task delete <id>` | 删除任务 |

### 步骤管理

| 命令 | 说明 |
|------|------|
| `agent step add <task_id> "标题" [-d 描述]` | 添加步骤 |
| `agent step batch <task_id> "步骤1" "步骤2" ...` | 批量添加步骤 |
| `agent step start <step_id>` | 开始步骤 |
| `agent step progress <step_id> <0-100> [-s 总结]` | 更新进度 |
| `agent step done <step_id> [-s 总结]` | 完成步骤 |
| `agent step fail <step_id> [-s 原因]` | 标记步骤失败 |
| `agent step skip <step_id> [-s 原因]` | 跳过步骤 |

### 状态图标

- ⬜ Pending（待处理）
- 🔄 In Progress（进行中）
- ✅ Completed（已完成）
- ❌ Failed（失败）
- ⏭️ Skipped（跳过）
- 🚫 Cancelled（已取消）

## 🏗️ 架构设计

### 数据流

```
┌─────────────────────────────────────────────────────────────┐
│                     Claude Code 会话                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐              ┌──────────────┐            │
│  │ SessionStart │              │ PostToolUse  │            │
│  │    Hook      │              │    Hook      │            │
│  └──────┬───────┘              └──────┬───────┘            │
│         │                              │                     │
│         │ 注入续传报告                 │ 记录活动             │
│         ↓                              ↓                     │
└─────────┼──────────────────────────────┼─────────────────────┘
          │                              │
          ↓                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      Task Agent                             │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────┐  ┌─────────┐  ┌────────────┐  ┌─────────────┐ │
│  │  Tasks  │  │  Steps  │  │   Log      │  │ Milestones  │ │
│  └─────────┘  └─────────┘  └────────────┘  └─────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │           SQLite Database (Per Project + User)       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 目录结构

```
~/.task-agent/                      # 数据目录（全局）
└── {git用户名}/
    └── tasks.db                    # 任务数据库（按项目隔离）

{项目目录}/
├── .claude/
│   └── settings.local.json         # Hooks 配置
└── .task-agent/                    # 项目级数据（可选）
    └── {git用户名}/
        └── tasks.db                # 项目数据库（优先使用）
```

### Hook 配置

Task Agent 会在项目目录的 `.claude/settings.local.json` 中自动配置以下 Hooks：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/task-agent/hooks/session_start.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/task-agent/hooks/post_tool_use.sh"
          }
        ]
      }
    ]
  }
}
```

## 💾 数据存储

- **数据库格式**: SQLite
- **数据库位置**: `{项目目录}/.task-agent/{git用户名}/tasks.db`
- **隔离机制**: 按项目目录 + Git 用户名隔离
- **并发安全**: 使用 WAL 模式，支持多进程并发访问

### 数据表结构

| 表名 | 说明 |
|------|------|
| `tasks` | 任务主表 |
| `steps` | 步骤表（关联任务） |
| `activity_log` | 活动日志（追踪所有操作） |
| `milestones` | 里程碑记录（Git 提交关联） |

## 🔐 隐私与安全

- 所有数据存储在本地，不上传到云端
- 数据库按项目和用户隔离，多用户协作时互不干扰
- Hooks 仅在 Claude Code 执行时触发，不收集任何个人信息

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发环境

```bash
# 克隆仓库
git clone https://github.com/yourusername/task-agent.git
cd task-agent

# 测试安装
bash setup.sh

# 创建测试任务
agent task new "测试任务"
```

### 代码规范

- 使用 Python 3.7+ 语法
- 遵循 PEP 8 代码规范
- 添加必要的注释和文档字符串
- 保持单文件架构，避免外部依赖

## 📝 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🙏 致谢

- 感谢 [Anthropic](https://www.anthropic.com) 提供 Claude Code
- 感谢所有贡献者和用户的反馈

---

**Made with ❤️ for AI-assisted development**

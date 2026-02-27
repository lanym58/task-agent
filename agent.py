#!/usr/bin/env python3
"""Task Agent - 智能体任务追踪系统

断点续传 + 任务进度管理，与 Claude Code 协作。
单文件实现，零外部依赖（仅 Python 标准库）。
"""

import os
# Fix encoding for Windows
if os.name == 'nt':
    os.environ['PYTHONIOENCODING'] = 'utf-8'

import argparse
import json
import sqlite3
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path


# ─── Helper Functions ────────────────────────────────────────────────────────

def get_git_user():
    """Get git user name for database separation."""
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True, cwd=os.getcwd(),
            encoding='utf-8', errors='ignore'
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return "default"


def get_project_root():
    """Get git project root directory, fallback to cwd."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=os.getcwd(),
            encoding='utf-8', errors='ignore'
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return os.getcwd()


def get_db_path():
    """Get database path: {project_root}/.task-agent/{git_user}/tasks.db"""
    project_root = get_project_root()
    git_user = get_git_user()
    db_dir = Path(project_root) / ".task-agent" / git_user
    return db_dir / "tasks.db", db_dir


# ─── Constants ───────────────────────────────────────────────────────────────

DB_PATH, DB_DIR = get_db_path()

TASK_STATUSES = ("pending", "in_progress", "completed", "failed", "cancelled")
STEP_STATUSES = ("pending", "in_progress", "completed", "failed", "skipped")

STATUS_ICONS = {
    "pending": "\u2b1c",
    "in_progress": "\U0001f504",
    "completed": "\u2705",
    "failed": "\u274c",
    "skipped": "\u23ed\ufe0f",
    "cancelled": "\U0001f6ab",
}


# ─── Database ────────────────────────────────────────────────────────────────

class Database:
    """SQLite database manager with crash-safe writes."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'pending',
        progress INTEGER DEFAULT 0,
        summary TEXT,
        project_dir TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        step_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'pending',
        progress INTEGER DEFAULT 0,
        summary TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        step_id INTEGER,
        event_type TEXT NOT NULL,
        event_data TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS milestones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        title TEXT,
        summary TEXT NOT NULL,
        commit_hash TEXT,
        branch TEXT,
        files_changed INTEGER DEFAULT 0,
        insertions INTEGER DEFAULT 0,
        deletions INTEGER DEFAULT 0,
        project_dir TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    """

    def __init__(self):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    def execute(self, sql, params=(), commit=True):
        cur = self.conn.execute(sql, params)
        if commit:
            self.conn.commit()
        return cur

    def fetchone(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def close(self):
        self.conn.close()


# ─── TaskManager ─────────────────────────────────────────────────────────────

class TaskManager:
    """Task and step lifecycle management."""

    def __init__(self, db: Database):
        self.db = db

    # ── Task CRUD ──

    def create_task(self, title, description=None, project_dir=None):
        cur = self.db.execute(
            "INSERT INTO tasks (title, description, project_dir) VALUES (?, ?, ?)",
            (title, description, project_dir),
        )
        task_id = cur.lastrowid
        self._log(task_id, None, "status_change", f"Task created: {title}")
        return task_id

    def get_task(self, task_id):
        return self.db.fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))

    def list_tasks(self, status_filter=None, project_dir=None):
        sql = "SELECT * FROM tasks WHERE 1=1"
        params = []
        if status_filter == "active":
            sql += " AND status IN ('pending', 'in_progress')"
        elif status_filter == "completed":
            sql += " AND status = 'completed'"
        elif status_filter and status_filter != "all":
            sql += " AND status = ?"
            params.append(status_filter)
        if project_dir:
            sql += " AND project_dir = ?"
            params.append(project_dir)
        sql += " ORDER BY updated_at DESC"
        return self.db.fetchall(sql, params)

    def update_task_status(self, task_id, status, summary=None):
        if status not in TASK_STATUSES:
            raise ValueError(f"Invalid status: {status}. Must be one of {TASK_STATUSES}")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if summary:
            self.db.execute(
                "UPDATE tasks SET status=?, summary=?, updated_at=? WHERE id=?",
                (status, summary, now, task_id),
            )
        else:
            self.db.execute(
                "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                (status, now, task_id),
            )
        self._log(task_id, None, "status_change", f"Task status → {status}")

    def delete_task(self, task_id):
        self.db.execute("DELETE FROM activity_log WHERE task_id = ?", (task_id,))
        self.db.execute("DELETE FROM steps WHERE task_id = ?", (task_id,))
        self.db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def get_active_task(self, project_dir=None):
        """Get the current in_progress task, optionally filtered by project."""
        if project_dir:
            task = self.db.fetchone(
                "SELECT * FROM tasks WHERE status='in_progress' AND project_dir=? "
                "ORDER BY updated_at DESC LIMIT 1",
                (project_dir,),
            )
            if task:
                return task
        return self.db.fetchone(
            "SELECT * FROM tasks WHERE status='in_progress' ORDER BY updated_at DESC LIMIT 1"
        )

    def get_pending_task(self, project_dir=None):
        if project_dir:
            task = self.db.fetchone(
                "SELECT * FROM tasks WHERE status='pending' AND project_dir=? "
                "ORDER BY created_at ASC LIMIT 1",
                (project_dir,),
            )
            if task:
                return task
        return self.db.fetchone(
            "SELECT * FROM tasks WHERE status='pending' ORDER BY created_at ASC LIMIT 1"
        )

    # ── Step CRUD ──

    def add_step(self, task_id, title, description=None):
        max_num = self.db.fetchone(
            "SELECT COALESCE(MAX(step_number), 0) as n FROM steps WHERE task_id=?",
            (task_id,),
        )
        step_number = max_num["n"] + 1
        cur = self.db.execute(
            "INSERT INTO steps (task_id, step_number, title, description) VALUES (?, ?, ?, ?)",
            (task_id, step_number, title, description),
        )
        self._log(task_id, cur.lastrowid, "status_change", f"Step {step_number} added: {title}")
        return cur.lastrowid

    def batch_add_steps(self, task_id, titles):
        step_ids = []
        for title in titles:
            sid = self.add_step(task_id, title)
            step_ids.append(sid)
        return step_ids

    def get_step(self, step_id):
        return self.db.fetchone("SELECT * FROM steps WHERE id = ?", (step_id,))

    def get_steps(self, task_id):
        return self.db.fetchall(
            "SELECT * FROM steps WHERE task_id=? ORDER BY step_number", (task_id,)
        )

    def start_step(self, step_id):
        step = self.get_step(step_id)
        if not step:
            raise ValueError(f"Step {step_id} not found")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.db.execute(
            "UPDATE steps SET status='in_progress', updated_at=? WHERE id=?",
            (now, step_id),
        )
        # Also ensure the parent task is in_progress
        task = self.get_task(step["task_id"])
        if task and task["status"] == "pending":
            self.db.execute(
                "UPDATE tasks SET status='in_progress', updated_at=? WHERE id=?",
                (now, step["task_id"]),
            )
        self._log(step["task_id"], step_id, "status_change",
                  f"Step {step['step_number']} started: {step['title']}")

    def update_step_progress(self, step_id, progress, summary=None):
        step = self.get_step(step_id)
        if not step:
            raise ValueError(f"Step {step_id} not found")
        progress = max(0, min(100, progress))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if summary:
            self.db.execute(
                "UPDATE steps SET progress=?, summary=?, status='in_progress', updated_at=? WHERE id=?",
                (progress, summary, now, step_id),
            )
        else:
            self.db.execute(
                "UPDATE steps SET progress=?, status='in_progress', updated_at=? WHERE id=?",
                (progress, now, step_id),
            )
        self._recalc_task_progress(step["task_id"])
        self._log(step["task_id"], step_id, "progress",
                  f"Step {step['step_number']} → {progress}%"
                  + (f": {summary}" if summary else ""))

    def complete_step(self, step_id, summary=None):
        step = self.get_step(step_id)
        if not step:
            raise ValueError(f"Step {step_id} not found")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.db.execute(
            "UPDATE steps SET status='completed', progress=100, summary=?, updated_at=? WHERE id=?",
            (summary or step["summary"], now, step_id),
        )
        self._recalc_task_progress(step["task_id"])
        self._log(step["task_id"], step_id, "status_change",
                  f"Step {step['step_number']} completed"
                  + (f": {summary}" if summary else ""))

    def fail_step(self, step_id, summary=None):
        step = self.get_step(step_id)
        if not step:
            raise ValueError(f"Step {step_id} not found")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.db.execute(
            "UPDATE steps SET status='failed', summary=?, updated_at=? WHERE id=?",
            (summary or step["summary"], now, step_id),
        )
        self._recalc_task_progress(step["task_id"])
        self._log(step["task_id"], step_id, "status_change",
                  f"Step {step['step_number']} failed"
                  + (f": {summary}" if summary else ""))

    def skip_step(self, step_id, summary=None):
        step = self.get_step(step_id)
        if not step:
            raise ValueError(f"Step {step_id} not found")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.db.execute(
            "UPDATE steps SET status='skipped', summary=?, updated_at=? WHERE id=?",
            (summary or step["summary"], now, step_id),
        )
        self._recalc_task_progress(step["task_id"])
        self._log(step["task_id"], step_id, "status_change",
                  f"Step {step['step_number']} skipped"
                  + (f": {summary}" if summary else ""))

    # ── Progress Calculation ──

    def _recalc_task_progress(self, task_id):
        steps = self.get_steps(task_id)
        if not steps:
            return
        total = sum(s["progress"] for s in steps)
        progress = total // len(steps)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.db.execute(
            "UPDATE tasks SET progress=?, updated_at=? WHERE id=?",
            (progress, now, task_id),
        )

    # ── Restart ──

    def restart(self, project_dir=None):
        """Archive current active task and prepare for new one."""
        task = self.get_active_task(project_dir)
        if not task:
            return None
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Cancel all pending/in_progress steps
        self.db.execute(
            "UPDATE steps SET status='skipped', updated_at=? "
            "WHERE task_id=? AND status IN ('pending', 'in_progress')",
            (now, task["id"]),
        )
        # Cancel the task
        self.db.execute(
            "UPDATE tasks SET status='cancelled', updated_at=? WHERE id=?",
            (now, task["id"]),
        )
        self._log(task["id"], None, "status_change", "Task archived via restart")
        return task

    # ── Xiaocheng (Milestone) ──

    def xiaocheng(self, summary=None, project_dir=None):
        """Commit, push, record milestone, archive task."""
        task = self.get_active_task(project_dir)
        result = {"task": task, "git": {}, "milestone_id": None}

        # 1. Check git status
        try:
            git_status = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, cwd=project_dir,
                encoding='utf-8', errors='ignore'
            )
            has_changes = bool(git_status.stdout.strip())
        except Exception:
            has_changes = False

        if has_changes:
            # 2. Commit
            commit_msg = f"xiaocheng: {summary}" if summary else "xiaocheng: milestone checkpoint"
            try:
                subprocess.run(["git", "add", "-A"], capture_output=True, cwd=project_dir)
                commit_result = subprocess.run(
                    ["git", "commit", "-m", commit_msg],
                    capture_output=True, text=True, cwd=project_dir,
                    encoding='utf-8', errors='ignore'
                )
                result["git"]["committed"] = commit_result.returncode == 0
            except Exception:
                result["git"]["committed"] = False

            # Get commit hash
            try:
                hash_result = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, cwd=project_dir,
                    encoding='utf-8', errors='ignore'
                )
                result["git"]["commit_hash"] = hash_result.stdout.strip()
            except Exception:
                result["git"]["commit_hash"] = None

            # Get branch
            try:
                branch_result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True, text=True, cwd=project_dir,
                    encoding='utf-8', errors='ignore'
                )
                result["git"]["branch"] = branch_result.stdout.strip()
            except Exception:
                result["git"]["branch"] = None

            # Get diff stats
            try:
                stat_result = subprocess.run(
                    ["git", "diff", "--stat", "HEAD~1", "HEAD"],
                    capture_output=True, text=True, cwd=project_dir,
                    encoding='utf-8', errors='ignore'
                )
                result["git"]["stat"] = stat_result.stdout.strip()
                # Parse stats from last line
                lines = stat_result.stdout.strip().split("\n")
                if lines:
                    last = lines[-1]
                    import re
                    fc = re.search(r"(\d+) files? changed", last)
                    ins = re.search(r"(\d+) insertions?", last)
                    dels = re.search(r"(\d+) deletions?", last)
                    result["git"]["files_changed"] = int(fc.group(1)) if fc else 0
                    result["git"]["insertions"] = int(ins.group(1)) if ins else 0
                    result["git"]["deletions"] = int(dels.group(1)) if dels else 0
            except Exception:
                result["git"]["files_changed"] = 0
                result["git"]["insertions"] = 0
                result["git"]["deletions"] = 0

            # 3. Push
            try:
                push_result = subprocess.run(
                    ["git", "push"],
                    capture_output=True, text=True, cwd=project_dir,
                    encoding='utf-8', errors='ignore'
                )
                result["git"]["pushed"] = push_result.returncode == 0
                result["git"]["push_msg"] = push_result.stderr.strip()
            except Exception:
                result["git"]["pushed"] = False
        else:
            result["git"]["no_changes"] = True
            # Still get branch info
            try:
                branch_result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True, text=True, cwd=project_dir,
                    encoding='utf-8', errors='ignore'
                )
                result["git"]["branch"] = branch_result.stdout.strip()
                hash_result = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, cwd=project_dir
                )
                result["git"]["commit_hash"] = hash_result.stdout.strip()
            except Exception:
                pass

        # 4. Record milestone
        milestone_summary = summary or (task["title"] if task else "milestone checkpoint")
        cur = self.db.execute(
            "INSERT INTO milestones (task_id, title, summary, commit_hash, branch, "
            "files_changed, insertions, deletions, project_dir) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task["id"] if task else None,
                task["title"] if task else None,
                milestone_summary,
                result["git"].get("commit_hash"),
                result["git"].get("branch"),
                result["git"].get("files_changed", 0),
                result["git"].get("insertions", 0),
                result["git"].get("deletions", 0),
                project_dir,
            ),
        )
        result["milestone_id"] = cur.lastrowid

        # 5. Complete/archive current task
        if task:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.db.execute(
                "UPDATE steps SET status='completed', progress=100, updated_at=? "
                "WHERE task_id=? AND status IN ('pending', 'in_progress')",
                (now, task["id"]),
            )
            self.db.execute(
                "UPDATE tasks SET status='completed', progress=100, summary=?, updated_at=? WHERE id=?",
                (milestone_summary, now, task["id"]),
            )
            self._log(task["id"], None, "status_change", f"Task completed via xiaocheng: {milestone_summary}")

        return result

    # ── Activity Log ──

    def _log(self, task_id, step_id, event_type, event_data):
        self.db.execute(
            "INSERT INTO activity_log (task_id, step_id, event_type, event_data) "
            "VALUES (?, ?, ?, ?)",
            (task_id, step_id, event_type, event_data),
        )

    def log_tool_use(self, tool_name, tool_input_summary, task_id=None, step_id=None):
        """Record a tool use event from PostToolUse hook."""
        if task_id is None:
            active = self.get_active_task()
            if active:
                task_id = active["id"]
                # Find the current in_progress step
                active_step = self.db.fetchone(
                    "SELECT id FROM steps WHERE task_id=? AND status='in_progress' "
                    "ORDER BY step_number DESC LIMIT 1",
                    (task_id,),
                )
                if active_step:
                    step_id = active_step["id"]
        if task_id:
            self._log(task_id, step_id, "tool_use", f"{tool_name} {tool_input_summary}")

    def get_activity_log(self, task_id=None, limit=20):
        if task_id:
            return self.db.fetchall(
                "SELECT * FROM activity_log WHERE task_id=? ORDER BY created_at DESC LIMIT ?",
                (task_id, limit),
            )
        return self.db.fetchall(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,)
        )

    # ── Milestones ──

    def get_milestones(self, limit=10):
        return self.db.fetchall(
            "SELECT * FROM milestones ORDER BY created_at DESC LIMIT ?", (limit,)
        )


# ─── Renderer ────────────────────────────────────────────────────────────────

class Renderer:
    """Output formatting for terminal and context injection."""

    @staticmethod
    def progress_bar(percent, width=38):
        filled = int(width * percent / 100)
        bar = "\u2588" * filled + "\u2591" * (width - filled)
        return f"{bar} {percent}%"

    @staticmethod
    def step_line(step, compact=False):
        icon = STATUS_ICONS.get(step["status"], "\u2b1c")
        num = step["step_number"]
        title = step["title"]
        pct = step["progress"]
        summary_part = ""
        if step["summary"]:
            s = step["summary"]
            summary_part = f" | {s[:40]}{'...' if len(s)>40 else ''}"
        if compact:
            return f"  {icon} {num}. {title} [{pct}%]{summary_part}"
        return f"  {icon} {num}. {title:<30s} {pct:>3d}%{summary_part}"

    def render_status(self, task, steps):
        """Terminal-friendly status display."""
        lines = []
        lines.append("\u2550" * 54)
        lines.append(f"  Task #{task['id']}: {task['title']}")
        lines.append(f"  Status: {task['status']} | Progress: {task['progress']}%")
        lines.append(f"  {self.progress_bar(task['progress'])}")
        lines.append("\u2500" * 54)
        for s in steps:
            lines.append(self.step_line(s))
        lines.append("\u2550" * 54)
        return "\n".join(lines)

    def render_resume_report(self, task, steps, activity_logs):
        """Generate resume/context report for session restart."""
        lines = []
        lines.append("[Task Agent - \u65ad\u70b9\u7eed\u4f20]")
        lines.append("")
        lines.append("\u4f60\u6709\u4e00\u4e2a\u672a\u5b8c\u6210\u7684\u4efb\u52a1\u9700\u8981\u7ee7\u7eed\uff1a")
        lines.append("")
        lines.append(f"## Task #{task['id']}: {task['title']}")
        lines.append(f"\u72b6\u6001: {task['status']} | \u6574\u4f53\u8fdb\u5ea6: {task['progress']}%")
        if task["project_dir"]:
            lines.append(f"\u9879\u76ee\u76ee\u5f55: {task['project_dir']}")
        if task["description"]:
            lines.append(f"\u63cf\u8ff0: {task['description']}")
        lines.append("")

        # Group steps by status
        completed = [s for s in steps if s["status"] == "completed"]
        in_progress = [s for s in steps if s["status"] == "in_progress"]
        pending = [s for s in steps if s["status"] in ("pending",)]
        failed = [s for s in steps if s["status"] == "failed"]

        if completed:
            lines.append("### \u5df2\u5b8c\u6210\u7684\u6b65\u9aa4:")
            for s in completed:
                lines.append(f"{s['step_number']}. \u2705 {s['title']} [100%]")
                if s["summary"]:
                    lines.append(f"   \u6458\u8981: {s['summary']}")
            lines.append("")

        if in_progress:
            lines.append("### \u5f53\u524d\u8fdb\u884c\u4e2d:")
            for s in in_progress:
                lines.append(f"{s['step_number']}. \U0001f504 {s['title']} [{s['progress']}%]")
                if s["summary"]:
                    lines.append(f"   \u6458\u8981: {s['summary']}")
            lines.append("")

        if pending:
            lines.append("### \u5f85\u5b8c\u6210\u7684\u6b65\u9aa4:")
            for s in pending:
                lines.append(f"{s['step_number']}. \u2b1c {s['title']} [0%]")
            lines.append("")

        if failed:
            lines.append("### \u5931\u8d25\u7684\u6b65\u9aa4:")
            for s in failed:
                lines.append(f"{s['step_number']}. \u274c {s['title']}")
                if s["summary"]:
                    lines.append(f"   \u539f\u56e0: {s['summary']}")
            lines.append("")

        if activity_logs:
            lines.append(f"### \u6700\u8fd1\u6d3b\u52a8\u8bb0\u5f55\uff08\u6700\u540e{len(activity_logs)}\u6761\uff09:")
            for log in reversed(activity_logs):
                time_str = log["created_at"]
                if time_str and len(time_str) >= 16:
                    time_str = time_str[11:16]  # HH:MM
                lines.append(f"  [{time_str}] {log['event_data']}")
            lines.append("")

        # Continue guidance
        lines.append("### \u7ee7\u7eed\u6307\u5f15:")
        if in_progress:
            s = in_progress[0]
            lines.append(
                f"\u8bf7\u7ee7\u7eed\u5b8c\u6210 Step {s['step_number']} ({s['title']}) \u7684\u5269\u4f59\u5de5\u4f5c\u3002"
            )
            lines.append(f"\u5b8c\u6210\u540e\u6267\u884c: agent step done {s['id']} -s \"\u5b8c\u6210\u6458\u8981\"")
        elif pending:
            s = pending[0]
            lines.append(f"\u8bf7\u5f00\u59cb\u6267\u884c Step {s['step_number']} ({s['title']})\u3002")
            lines.append(f"\u5f00\u59cb\u6267\u884c: agent step start {s['id']}")
        else:
            lines.append("\u6240\u6709\u6b65\u9aa4\u5df2\u5b8c\u6210\uff0c\u8bf7\u6267\u884c: agent task done " + str(task["id"]) + " -s \"\u5b8c\u6210\u6458\u8981\"")

        # Show remaining steps after the current one
        if in_progress and pending:
            remaining = [f"Step {s['step_number']}" for s in pending]
            lines.append(f"\u7136\u540e\u7ee7\u7eed\u63a8\u8fdb: {', '.join(remaining)}\u3002")
        elif pending and len(pending) > 1:
            remaining = [f"Step {s['step_number']}" for s in pending[1:]]
            lines.append(f"\u7136\u540e\u7ee7\u7eed\u63a8\u8fdb: {', '.join(remaining)}\u3002")

        return "\n".join(lines)

    def render_restart(self, task):
        """Render restart confirmation."""
        lines = []
        lines.append("\u2550" * 54)
        if task:
            completed_steps = 0
            total_steps = 0
            # Count from db would be better but we have task info
            lines.append(f"  \u5df2\u5f52\u6863\u4efb\u52a1 Task #{task['id']}: {task['title']}")
            lines.append(f"  \u5b8c\u6210\u8fdb\u5ea6: {task['progress']}%")
            lines.append(f"  \u5f52\u6863\u65f6\u95f4: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            lines.append("  \u5f53\u524d\u6ca1\u6709\u6d3b\u8dc3\u4efb\u52a1\u3002")
        lines.append("\u2500" * 54)
        lines.append("  \u73b0\u5728\u53ef\u4ee5\u5f00\u59cb\u65b0\u4efb\u52a1:")
        lines.append('  agent task new "\u4efb\u52a1\u6807\u9898" -d "\u63cf\u8ff0"')
        lines.append("\u2550" * 54)
        return "\n".join(lines)

    def render_xiaocheng(self, result):
        """Render xiaocheng milestone report."""
        lines = []
        lines.append("\u2550" * 54)
        lines.append("  \U0001f389 \u5c0f\u6210\uff01")
        lines.append("\u2550" * 54)

        git = result["git"]
        lines.append("  Git:")
        if git.get("no_changes"):
            lines.append("    \u65e0\u672a\u63d0\u4ea4\u7684\u53d8\u66f4")
        else:
            lines.append(f"    Commit: {git.get('commit_hash', 'N/A')}")
            lines.append(f"    Branch: {git.get('branch', 'N/A')}")
            fc = git.get("files_changed", 0)
            ins = git.get("insertions", 0)
            dels = git.get("deletions", 0)
            lines.append(f"    Files: {fc} changed | +{ins} -{dels} lines")
            if git.get("pushed"):
                lines.append(f"    Push: \u2705 {git.get('push_msg', 'OK')}")
            else:
                lines.append(f"    Push: \u274c {git.get('push_msg', 'failed')}")

        lines.append("")
        lines.append(f"  Milestone #{result['milestone_id']}:")
        task = result.get("task")
        if task:
            lines.append(f"    Task: #{task['id']} {task['title']} \u2192 completed")
        lines.append("")
        lines.append("  \u91cc\u7a0b\u7891\u5df2\u8bb0\u5f55\u3002\u53ef\u4ee5\u5f00\u59cb\u65b0\u4efb\u52a1:")
        lines.append('    agent task new "\u4efb\u52a1\u6807\u9898" -d "\u63cf\u8ff0"')
        lines.append("\u2550" * 54)
        return "\n".join(lines)

    def render_milestones(self, milestones):
        """Render milestone history."""
        lines = []
        lines.append("\u2550" * 54)
        lines.append("  \u91cc\u7a0b\u7891\u5386\u53f2")
        lines.append("\u2500" * 54)
        for m in milestones:
            time_str = m["created_at"][:16] if m["created_at"] else "N/A"
            commit = m["commit_hash"] or "N/A"
            branch = m["branch"] or "N/A"
            lines.append(f"  #{m['id']}  {time_str}  {commit}  {branch}")
            lines.append(f"      {m['summary']}")
        if not milestones:
            lines.append("  \u6682\u65e0\u91cc\u7a0b\u7891\u8bb0\u5f55")
        lines.append("\u2550" * 54)
        return "\n".join(lines)


# ─── ActivityLogger ──────────────────────────────────────────────────────────

class ActivityLogger:
    """Parse PostToolUse hook input and log tool activity."""

    # Tools to track and how to summarize their input
    TOOL_SUMMARIES = {
        "Read": lambda inp: inp.get("file_path", ""),
        "Edit": lambda inp: inp.get("file_path", ""),
        "Write": lambda inp: inp.get("file_path", ""),
        "Glob": lambda inp: inp.get("pattern", ""),
        "Grep": lambda inp: f'"{inp.get("pattern", "")}" in {inp.get("path", ".")}',
        "Bash": lambda inp: (inp.get("command", ""))[:80],
        "WebFetch": lambda inp: inp.get("url", "")[:60],
        "WebSearch": lambda inp: inp.get("query", ""),
        "Task": lambda inp: inp.get("description", ""),
    }

    @staticmethod
    def parse_hook_input(json_str):
        """Parse PostToolUse hook JSON input."""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None, None

        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except json.JSONDecodeError:
                tool_input = {}

        summarizer = ActivityLogger.TOOL_SUMMARIES.get(tool_name)
        if summarizer and isinstance(tool_input, dict):
            summary = summarizer(tool_input)
        else:
            summary = ""

        return tool_name, summary


# ─── CLI ─────────────────────────────────────────────────────────────────────

def get_project_dir():
    """Get current working directory as project dir."""
    return os.getcwd()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="agent",
        description="Task Agent - \u667a\u80fd\u4f53\u4efb\u52a1\u8ffd\u8e2a\u7cfb\u7edf",
    )
    sub = parser.add_subparsers(dest="command")

    # ── init ──
    sub.add_parser("init", help="\u521d\u59cb\u5316\u6570\u636e\u5e93")

    # ── resume ──
    sub.add_parser("resume", help="\u751f\u6210\u65ad\u70b9\u7eed\u4f20\u62a5\u544a")

    # ── context (for SessionStart hook) ──
    sub.add_parser("context", help="\u8f93\u51fa\u7eed\u4f20\u4e0a\u4e0b\u6587\uff08Hook\u7528\uff09")

    # ── restart ──
    sub.add_parser("restart", help="\u5f52\u6863\u5f53\u524d\u4efb\u52a1\uff0c\u91cd\u65b0\u5f00\u59cb")

    # ── xiaocheng ──
    p = sub.add_parser("xiaocheng", help="\u5c0f\u6210\uff1a\u63d0\u4ea4+\u63a8\u9001+\u91cc\u7a0b\u7891+\u5f52\u6863")
    p.add_argument("-m", "--message", help="\u53d8\u66f4\u603b\u7ed3")

    # ── status ──
    sub.add_parser("status", help="\u5f53\u524d\u6d3b\u8dc3\u4efb\u52a1\u6982\u89c8")

    # ── log ──
    p = sub.add_parser("log", help="\u67e5\u770b\u6d3b\u52a8\u65e5\u5fd7")
    p.add_argument("task_id", nargs="?", type=int, help="\u4efb\u52a1ID")
    p.add_argument("-n", "--limit", type=int, default=20, help="\u663e\u793a\u6761\u6570")

    # ── milestones ──
    p = sub.add_parser("milestones", help="\u67e5\u770b\u91cc\u7a0b\u7891\u5386\u53f2")
    p.add_argument("-n", "--limit", type=int, default=10, help="\u663e\u793a\u6761\u6570")

    # ── log-tool (internal, for PostToolUse hook) ──
    sub.add_parser("log-tool", help="\u8bb0\u5f55\u5de5\u5177\u6d3b\u52a8\uff08Hook\u5185\u90e8\u7528\uff09")

    # ── task ──
    task_parser = sub.add_parser("task", help="\u4efb\u52a1\u7ba1\u7406")
    task_sub = task_parser.add_subparsers(dest="task_command")

    p = task_sub.add_parser("new", help="\u521b\u5efa\u65b0\u4efb\u52a1")
    p.add_argument("title", help="\u4efb\u52a1\u6807\u9898")
    p.add_argument("-d", "--description", help="\u4efb\u52a1\u63cf\u8ff0")

    p = task_sub.add_parser("list", help="\u5217\u51fa\u4efb\u52a1")
    p.add_argument("--status", default="active",
                    choices=["active", "completed", "all", "pending", "in_progress", "failed", "cancelled"],
                    help="\u72b6\u6001\u8fc7\u6ee4")

    p = task_sub.add_parser("show", help="\u67e5\u770b\u4efb\u52a1\u8be6\u60c5")
    p.add_argument("task_id", type=int, help="\u4efb\u52a1ID")

    p = task_sub.add_parser("done", help="\u5b8c\u6210\u4efb\u52a1")
    p.add_argument("task_id", type=int, help="\u4efb\u52a1ID")
    p.add_argument("-s", "--summary", help="\u5b8c\u6210\u6458\u8981")

    p = task_sub.add_parser("fail", help="\u6807\u8bb0\u4efb\u52a1\u5931\u8d25")
    p.add_argument("task_id", type=int, help="\u4efb\u52a1ID")
    p.add_argument("-s", "--summary", help="\u5931\u8d25\u539f\u56e0")

    p = task_sub.add_parser("cancel", help="\u53d6\u6d88\u4efb\u52a1")
    p.add_argument("task_id", type=int, help="\u4efb\u52a1ID")

    p = task_sub.add_parser("delete", help="\u5220\u9664\u4efb\u52a1")
    p.add_argument("task_id", type=int, help="\u4efb\u52a1ID")

    # ── step ──
    step_parser = sub.add_parser("step", help="\u6b65\u9aa4\u7ba1\u7406")
    step_sub = step_parser.add_subparsers(dest="step_command")

    p = step_sub.add_parser("add", help="\u6dfb\u52a0\u6b65\u9aa4")
    p.add_argument("task_id", type=int, help="\u4efb\u52a1ID")
    p.add_argument("title", help="\u6b65\u9aa4\u6807\u9898")
    p.add_argument("-d", "--description", help="\u6b65\u9aa4\u63cf\u8ff0")

    p = step_sub.add_parser("batch", help="\u6279\u91cf\u6dfb\u52a0\u6b65\u9aa4")
    p.add_argument("task_id", type=int, help="\u4efb\u52a1ID")
    p.add_argument("titles", nargs="+", help="\u6b65\u9aa4\u6807\u9898\u5217\u8868")

    p = step_sub.add_parser("start", help="\u5f00\u59cb\u6267\u884c\u6b65\u9aa4")
    p.add_argument("step_id", type=int, help="\u6b65\u9aa4ID")

    p = step_sub.add_parser("progress", help="\u66f4\u65b0\u6b65\u9aa4\u8fdb\u5ea6")
    p.add_argument("step_id", type=int, help="\u6b65\u9aa4ID")
    p.add_argument("percent", type=int, help="\u8fdb\u5ea6\u767e\u5206\u6bd4 (0-100)")
    p.add_argument("-s", "--summary", help="\u8fdb\u5ea6\u6458\u8981")

    p = step_sub.add_parser("done", help="\u5b8c\u6210\u6b65\u9aa4")
    p.add_argument("step_id", type=int, help="\u6b65\u9aa4ID")
    p.add_argument("-s", "--summary", help="\u5b8c\u6210\u6458\u8981")

    p = step_sub.add_parser("fail", help="\u6807\u8bb0\u6b65\u9aa4\u5931\u8d25")
    p.add_argument("step_id", type=int, help="\u6b65\u9aa4ID")
    p.add_argument("-s", "--summary", help="\u5931\u8d25\u539f\u56e0")

    p = step_sub.add_parser("skip", help="\u8df3\u8fc7\u6b65\u9aa4")
    p.add_argument("step_id", type=int, help="\u6b65\u9aa4ID")
    p.add_argument("-s", "--summary", help="\u8df3\u8fc7\u539f\u56e0")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    db = Database()
    tm = TaskManager(db)
    renderer = Renderer()
    project_dir = get_project_dir()

    try:
        # ── init ──
        if args.command == "init":
            print("\u2705 \u6570\u636e\u5e93\u5df2\u521d\u59cb\u5316:", DB_PATH)

        # ── context (SessionStart hook) ──
        elif args.command == "context":
            task = tm.get_active_task(project_dir)
            if not task:
                task = tm.get_pending_task(project_dir)
            if task:
                steps = tm.get_steps(task["id"])
                logs = tm.get_activity_log(task["id"], limit=5)
                print(renderer.render_resume_report(task, steps, logs))
            # Silent exit if no task

        # ── resume ──
        elif args.command == "resume":
            task = tm.get_active_task(project_dir)
            if not task:
                task = tm.get_pending_task(project_dir)
            if task:
                steps = tm.get_steps(task["id"])
                logs = tm.get_activity_log(task["id"], limit=5)
                print(renderer.render_resume_report(task, steps, logs))
            else:
                print("\u5f53\u524d\u6ca1\u6709\u6d3b\u8dc3\u6216\u5f85\u5904\u7406\u7684\u4efb\u52a1\u3002")

        # ── restart ──
        elif args.command == "restart":
            task = tm.restart(project_dir)
            print(renderer.render_restart(task))

        # ── xiaocheng ──
        elif args.command == "xiaocheng":
            result = tm.xiaocheng(summary=args.message, project_dir=project_dir)
            print(renderer.render_xiaocheng(result))

        # ── status ──
        elif args.command == "status":
            task = tm.get_active_task(project_dir)
            if not task:
                task = tm.get_pending_task(project_dir)
            if task:
                steps = tm.get_steps(task["id"])
                print(renderer.render_status(task, steps))
            else:
                print("\u5f53\u524d\u6ca1\u6709\u6d3b\u8dc3\u4efb\u52a1\u3002")
                print('\u4f7f\u7528 agent task new "\u4efb\u52a1\u6807\u9898" \u521b\u5efa\u65b0\u4efb\u52a1\u3002')

        # ── log ──
        elif args.command == "log":
            logs = tm.get_activity_log(args.task_id, args.limit)
            if logs:
                for log in logs:
                    t = log["created_at"]
                    if t and len(t) >= 16:
                        t = t[:16]
                    tid = log["task_id"] or "-"
                    print(f"  [{t}] T{tid} | {log['event_type']}: {log['event_data']}")
            else:
                print("  \u6682\u65e0\u6d3b\u52a8\u65e5\u5fd7\u3002")

        # ── milestones ──
        elif args.command == "milestones":
            milestones = tm.get_milestones(args.limit)
            print(renderer.render_milestones(milestones))

        # ── log-tool (PostToolUse hook internal) ──
        elif args.command == "log-tool":
            input_data = sys.stdin.read()
            if input_data.strip():
                tool_name, summary = ActivityLogger.parse_hook_input(input_data)
                if tool_name:
                    tm.log_tool_use(tool_name, summary)

        # ── task ──
        elif args.command == "task":
            if not args.task_command:
                parser.parse_args(["task", "-h"])
                sys.exit(0)

            if args.task_command == "new":
                task_id = tm.create_task(args.title, args.description, project_dir)
                print(f"\u2705 \u4efb\u52a1\u5df2\u521b\u5efa: Task #{task_id}: {args.title}")
                print(f'   \u6dfb\u52a0\u6b65\u9aa4: agent step add {task_id} "\u6b65\u9aa4\u6807\u9898"')
                print(f'   \u6279\u91cf\u6dfb\u52a0: agent step batch {task_id} "\u6b65\u9aa41" "\u6b65\u9aa42" ...')

            elif args.task_command == "list":
                tasks = tm.list_tasks(args.status)
                if tasks:
                    for t in tasks:
                        icon = STATUS_ICONS.get(t["status"], "\u2b1c")
                        print(f"  {icon} #{t['id']}  {t['title']:<35s}  {t['status']:<12s}  {t['progress']:>3d}%")
                else:
                    print("  \u6ca1\u6709\u627e\u5230\u4efb\u52a1\u3002")

            elif args.task_command == "show":
                task = tm.get_task(args.task_id)
                if task:
                    steps = tm.get_steps(task["id"])
                    print(renderer.render_status(task, steps))
                    if task["description"]:
                        print(f"\n  \u63cf\u8ff0: {task['description']}")
                    if task["summary"]:
                        print(f"  \u6458\u8981: {task['summary']}")
                    print(f"  \u9879\u76ee: {task['project_dir'] or 'N/A'}")
                    print(f"  \u521b\u5efa: {task['created_at']}")
                    print(f"  \u66f4\u65b0: {task['updated_at']}")
                else:
                    print(f"\u274c \u4efb\u52a1 #{args.task_id} \u4e0d\u5b58\u5728")

            elif args.task_command == "done":
                task = tm.get_task(args.task_id)
                if not task:
                    print(f"\u274c \u4efb\u52a1 #{args.task_id} \u4e0d\u5b58\u5728")
                    sys.exit(1)
                tm.update_task_status(args.task_id, "completed", args.summary)
                # Mark remaining steps as completed
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                db.execute(
                    "UPDATE steps SET status='completed', progress=100, updated_at=? "
                    "WHERE task_id=? AND status IN ('pending', 'in_progress')",
                    (now, args.task_id),
                )
                db.execute(
                    "UPDATE tasks SET progress=100, updated_at=? WHERE id=?",
                    (now, args.task_id),
                )
                print(f"\u2705 Task #{args.task_id} \u5df2\u5b8c\u6210")

            elif args.task_command == "fail":
                task = tm.get_task(args.task_id)
                if not task:
                    print(f"\u274c \u4efb\u52a1 #{args.task_id} \u4e0d\u5b58\u5728")
                    sys.exit(1)
                tm.update_task_status(args.task_id, "failed", args.summary)
                print(f"\u274c Task #{args.task_id} \u5df2\u6807\u8bb0\u4e3a\u5931\u8d25")

            elif args.task_command == "cancel":
                task = tm.get_task(args.task_id)
                if not task:
                    print(f"\u274c \u4efb\u52a1 #{args.task_id} \u4e0d\u5b58\u5728")
                    sys.exit(1)
                tm.update_task_status(args.task_id, "cancelled")
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                db.execute(
                    "UPDATE steps SET status='skipped', updated_at=? "
                    "WHERE task_id=? AND status IN ('pending', 'in_progress')",
                    (now, args.task_id),
                )
                print(f"\U0001f6ab Task #{args.task_id} \u5df2\u53d6\u6d88")

            elif args.task_command == "delete":
                task = tm.get_task(args.task_id)
                if not task:
                    print(f"\u274c \u4efb\u52a1 #{args.task_id} \u4e0d\u5b58\u5728")
                    sys.exit(1)
                tm.delete_task(args.task_id)
                print(f"\U0001f5d1\ufe0f  Task #{args.task_id} \u5df2\u5220\u9664")

        # ── step ──
        elif args.command == "step":
            if not args.step_command:
                parser.parse_args(["step", "-h"])
                sys.exit(0)

            if args.step_command == "add":
                step_id = tm.add_step(args.task_id, args.title, getattr(args, "description", None))
                step = tm.get_step(step_id)
                print(f"\u2705 \u6b65\u9aa4\u5df2\u6dfb\u52a0: Step #{step_id} (#{step['step_number']}): {args.title}")
                print(f"   \u5f00\u59cb\u6267\u884c: agent step start {step_id}")

            elif args.step_command == "batch":
                step_ids = tm.batch_add_steps(args.task_id, args.titles)
                print(f"\u2705 \u5df2\u6dfb\u52a0 {len(step_ids)} \u4e2a\u6b65\u9aa4:")
                for sid in step_ids:
                    step = tm.get_step(sid)
                    print(f"   #{sid} ({step['step_number']}): {step['title']}")
                print(f"\n   \u5f00\u59cb\u6267\u884c: agent step start {step_ids[0]}")

            elif args.step_command == "start":
                try:
                    tm.start_step(args.step_id)
                    step = tm.get_step(args.step_id)
                    print(f"\U0001f504 Step #{args.step_id} \u5df2\u5f00\u59cb: {step['title']}")
                except ValueError as e:
                    print(f"\u274c {e}")
                    sys.exit(1)

            elif args.step_command == "progress":
                try:
                    tm.update_step_progress(args.step_id, args.percent, args.summary)
                    step = tm.get_step(args.step_id)
                    print(f"\U0001f504 Step #{args.step_id} \u8fdb\u5ea6: {args.percent}%")
                    if args.summary:
                        print(f"   {args.summary}")
                    # Show task overall progress
                    task = tm.get_task(step["task_id"])
                    if task:
                        print(f"   \u4efb\u52a1\u6574\u4f53\u8fdb\u5ea6: {task['progress']}%")
                except ValueError as e:
                    print(f"\u274c {e}")
                    sys.exit(1)

            elif args.step_command == "done":
                try:
                    tm.complete_step(args.step_id, args.summary)
                    step = tm.get_step(args.step_id)
                    print(f"\u2705 Step #{args.step_id} \u5df2\u5b8c\u6210: {step['title']}")
                    if args.summary:
                        print(f"   {args.summary}")
                    task = tm.get_task(step["task_id"])
                    if task:
                        print(f"   \u4efb\u52a1\u6574\u4f53\u8fdb\u5ea6: {task['progress']}%")
                except ValueError as e:
                    print(f"\u274c {e}")
                    sys.exit(1)

            elif args.step_command == "fail":
                try:
                    tm.fail_step(args.step_id, args.summary)
                    print(f"\u274c Step #{args.step_id} \u5df2\u6807\u8bb0\u4e3a\u5931\u8d25")
                except ValueError as e:
                    print(f"\u274c {e}")
                    sys.exit(1)

            elif args.step_command == "skip":
                try:
                    tm.skip_step(args.step_id, args.summary)
                    print(f"\u23ed\ufe0f Step #{args.step_id} \u5df2\u8df3\u8fc7")
                except ValueError as e:
                    print(f"\u274c {e}")
                    sys.exit(1)

        else:
            parser.print_help()

    finally:
        db.close()


if __name__ == "__main__":
    main()

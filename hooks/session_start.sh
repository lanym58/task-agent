#!/bin/bash
# SessionStart Hook - context injection
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "")
[ -z "$PY" ] && { echo "{}"; exit 0; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || { echo "{}"; exit 0; }
"$PY" -c "
import sys, subprocess, json, os
py = sys.executable
result = subprocess.run([py, 'agent.py', 'context'], capture_output=True, text=True,
                        env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'})
output = result.stdout.strip()
if output:
    print(json.dumps({'inject': output}, ensure_ascii=False))
else:
    print('{}')
" 2>/dev/null || echo "{}"
exit 0

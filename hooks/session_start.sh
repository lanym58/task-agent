#!/bin/bash
# SessionStart Hook - context injection
export PYTHONIOENCODING=utf-8
export LANG=en_US.UTF-8

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 0
python3 -c "
import sys, subprocess, json
result = subprocess.run([sys.executable, 'agent.py', 'context'], capture_output=True, text=True)
output = result.stdout.strip()
if output:
    print(json.dumps({'inject': output}))
else:
    print('{}')
" 2>/dev/null
exit 0

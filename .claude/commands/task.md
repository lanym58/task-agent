Read the current task context and continue working:

<context>
$BASH(agent context 2>/dev/null || echo "No active task. Use: agent task new \"title\"")
</context>

If there is an active task, continue executing it from where it left off. If there is no active task, ask the user what task to create.

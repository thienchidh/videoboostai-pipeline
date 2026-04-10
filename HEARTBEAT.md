# HEARTBEAT.md — videopipeline

**PROJECT_NAME:** videopipeline
**WORKING_DIR:** /home/openclaw-personal/.openclaw/workspace-videopipeline
**TELEGRAM_TOPIC:** -1003736681617:topic:12147

---

## Core Rules (never break)

- Max 2 sub-agents per heartbeat
- Max 1 planner run per 2 giờ
- Heavy research max 1x per 30 min — not every beat
- Stuck "doing" task > 45 min → reset to "todo"
- Notification debounce: max 1 send per 5 minutes
- Nothing urgent? → **HEARTBEAT_OK** immediately

---

## ⚠️ LOCK ACQUISITION (first!)

```bash
LOCK_FILE=".tasks/.lock"
MAX_AGE=300  # 5 minutes

if [ -f "$LOCK_FILE" ]; then
  AGE=$(( $(date +%s) - $(date +%s -r "$LOCK_FILE") ))
  if [ $AGE -lt $MAX_AGE ]; then
    echo "Locked by another process ($AGE s < $MAX_AGE s)"
    exit 0  # Skip this heartbeat
  fi
fi
trap "rm -f $LOCK_FILE" EXIT
date > "$LOCK_FILE"
```

**ALWAYS acquire lock before any operation. ALWAYS release on exit.**

---

## Decision Tree (24/7 Optimized)

```
1. ACQUIRE LOCK → if fail → HEARTBEAT_OK
2. IF sessions still running → HEARTBEAT_OK + RELEASE LOCK
3. IF todo tasks exist AND active workers < 2 → spawn workers
4. IF task_board > 50 tasks OR done > 20 → ARCHIVE
5. IF actionable == 0 (all blocked/empty) → PLANNER MODE
6. IF < 3 actionable tasks → PLANNER MODE
7. IF git diff OR new commits → light scan
8. ELSE → HEARTBEAT_OK
RELEASE LOCK at end
```

**Actionable = tasks where status in (todo, doing) AND NOT blocked_by**

---

## Spawn Workers

Use sessions_spawn for real work. Never do heavy work in main session.

**ACP Harness (Claude Code for coding tasks):**
```
sessions_spawn(
  task="Task: [TASK-ID] [title] — read .tasks/task_board.json first",
  runtime="acp",
  agentId="codex",
  mode="run",
  timeoutSeconds=900,
  cwd="/home/openclaw-personal/.openclaw/workspace-videopipeline/",
  cleanup="delete"
)
```

### Task Claim (atomic, prevent duplicate work):
```bash
jq 'map(if .id == "VP-001" and .status == "todo" and .assigned_to == null
      then .status = "doing", .assigned_to = "agent-id", .claimed_at = "NOW"
      else . end)' .tasks/task_board.json > tmp && mv tmp .tasks/task_board.json
```

---

## Notification Logic (Critical Section)

### Step 1: Check for Status Changes
Read `.tasks/task_board.json`:
- Find tasks where `status` changed to `"done"` or `"failed"` since `last_notification_sent`

### Step 2: Debounce Check
Read `.tasks/.last_notification` (simple text file with ISO timestamp):
- If file exists and timestamp < 5 minutes ago → SKIP notification

### Step 3: Send Notification (only if debounce passed)

**For done tasks:**
```
✅ [videopipeline] Task [VP-xxx] completed: [1-line summary]
```

**For failed tasks (after 3 retries):**
```
⚠️ [videopipeline] Task [VP-xxx] failed after 3 retries: [reason]. Check logs.
```

### Step 4: Update Debounce Timestamp
```bash
date -Iseconds > .tasks/.last_notification
```

---

## Safety

- **NEVER** delete data or expose secrets
- **NEVER** commit secrets/API keys
- Use `trash` > `rm`

---

_Keep this lean. Detailed procedures → AGENTS.md_

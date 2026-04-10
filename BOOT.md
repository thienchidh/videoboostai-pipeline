# BOOT.md — videopipeline

## Boot Sequence

1. Read .tasks/task_board.json
2. Migrate schema if needed
3. Reset all "doing" → "todo"
4. Increment retry counts (max 3)
5. Resume only "todo" tasks — never start blindly

## Self-Healing

| Condition | Action |
|-----------|--------|
| Stuck task > 45 min | Reset to "todo" |
| Retry >= 3 | Mark "failed" |
| Schema mismatch | Migrate automatically |

## Log All Changes

Every state change to task_board.json must be logged with timestamp.

---

**This agent manages:** videopipeline - Video generation pipeline automation

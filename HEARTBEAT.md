# TradePass Heartbeat

## Schedule
- **Interval**: 20 minutes
- **Policy**: Execute top pending task from TASK_QUEUE.md, then terminate.

## On Each Wake
1. Read `STATE.md` → load context
2. Read `TASK_QUEUE.md` → top unchecked task
3. Execute task
4. Update `STATE.md` checkpoint
5. Mark task done in `TASK_QUEUE.md`
6. Terminate

## Control
- `paused`: Stop heartbeat until Jackson re-enables.
- `active`: Running every 20m.

*2026-04-10*

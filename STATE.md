# TradePass — STATE

**Project**: TradePass MVP  
**Stack**: Next.js (frontend), Python/Go (backend), PostgreSQL (target), SQLite (local mock)  
**Database Strategy**: Supabase-style (mocked locally via SQLite for MVP; swap to PostgreSQL on Supabase deploy)  
**Architecture**: Micro-SaaS — Spaced Repetition exam engine for NZ trade certifications  
**Target Market**: NZ Electricians (EWRB exams) → expand to other trades  

---

## Current Status

**Last Updated**: 2026-04-10  
**Heartbeat**: ACTIVE — 20-minute cycles  
**Current Task**: TASK 1 (in progress)

---

## Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Frontend | Next.js | SSR, API routes, fast deploy |
| Backend | Python (FastAPI) or Go | Go preferred for concurrency; Python for speed |
| Database | PostgreSQL (Supabase) | Production target |
| Local Mock | SQLite | MVP iteration without infra overhead |
| SR Algorithm | SuperMemo-2 | Proven, simple, 5-field variant |
| Auth | Supabase Auth (future) | Skip for MVP |
| Exam Domain | NZ EWRB Electricians | High failure rate, clear spec, ¥ paying |

---

## SuperMemo-2 Field Spec

| Field | Type | Notes |
|-------|------|-------|
| id | TEXT | UUID |
| question | TEXT | EWRB exam Q |
| answer | TEXT | Full answer |
| easiness_factor | REAL | Default 2.5 |
| interval | INTEGER | Days until next review |
| repetitions | INTEGER | Successful reviews count |
| next_review | TEXT | ISO8601 date |
| created_at | TEXT | ISO8601 |
| updated_at | TEXT | ISO8601 |

---

## EWRB Exam Specs (from TASK 1)

*See: research/EWRB_EXAM_SPECS.md*

---

## ON WAKEUP EXECUTION LOOP

```
1. Read STATE.md → load context
2. Read TASK_QUEUE.md → identify top pending task
3. Execute ONLY that task
4. Update STATE.md (checkpoint, notes)
5. Mark task complete in TASK_QUEUE.md
6. If more tasks pending → await next heartbeat
   If all complete → notify Jackson
7. Terminate process
```

---

## Checkpoint Log

| Date | Task | Status | Notes |
|------|------|--------|-------|
| 2026-04-10 | TASK 1 | **COMPLETE** | EWRB research: 50 Q / 2hr / 70% pass / AS/NZS 3000 Volt Drop #1 fail topic. Specs at research/EWRB_EXAM_SPECS.md |
| ... | ... | ... | ... |

---

*Source of truth — do not edit history, only append.*

# TradePass - STATE

**Project**: TradePass MVP
**Stack**: Next.js (frontend), Python/Go (backend), PostgreSQL (target), SQLite (local mock)
**Database Strategy**: Supabase-style (mocked locally via SQLite for MVP; swap to PostgreSQL on Supabase deploy)
**Architecture**: Micro-SaaS - Spaced Repetition exam engine for NZ trade certifications
**Target Market**: NZ Electricians (EWRB exams) → expand to other trades

---

## Current Status

**Last Updated**: 2026-04-11 19:04 UTC
**Heartbeat**: ACTIVE — 20-minute cycles
**Last Heartbeat**: 2026-04-11 06:06 UTC
**Current Task**: ALL TASKS COMPLETE. TradePass MVP fully shipped (10/10 tasks). No pending tasks. Awaiting next session direction.

**Completed Deliverables:**
- research/EWRB_EXAM_SPECS.md (exam research)
- research/seed_questions.json v2.0 (20 Qs with per-distractor explanations)
- schema/database.sql (8 tables + study_sessions + stripe_migration)
- backend/ (FastAPI + SQLite, SM-2 engine, all endpoints)
- design/stripe_freemium_design.md (Stripe integration design)
- docs/sm18_vs_sm2.md (algorithm recommendation)

**Backend Run**: `cd backend && pip install -r requirements.txt && python load_seed_data.py && python -m uvicorn main:app --reload --port 8000`

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
| 2026-04-10 | TASK 2 | **COMPLETE** | seed_questions.json: 20 exam-level Qs covering Volt Drop, Fault Loop Zs, AS/NZS 3000, Insulation Resistance, Max Demand, RCD/MCB protection. research/seed_questions.json |
| 2026-04-10 | TASK 3 | **COMPLETE** | PostgreSQL schema: 8 tables (topics, questions, users, user_progress, review_logs, exam_sessions, exam_answers) + topic_accuracy view + EWRB seed taxonomy. schema/database.sql |
| 2026-04-10 | TASK 4 | **COMPLETE** | FastAPI + SQLite backend: 20 Qs loaded, 11 topics, SM-2 review engine, due/new queues, user stats. Run: `cd backend && pip install -r requirements.txt && python -m uvicorn main:app --reload --port 8000`. Seed: `python load_seed_data.py`. backend/
| 2026-04-11 | TASK 5 | **COMPLETE** | Exam Simulation Mode already implemented in main.py. Full endpoint suite: exams/start, exams/{id}, exams/{id}/answer, exams/{id}/submit, exams/{id}/results. Auto-expiry, per-topic breakdown, 2hr EWRB-style timer.
| 2026-04-11 | TASK 6 | **COMPLETE** | seed_questions.json rebuilt: all 20 Qs now have structured per-distractor explanations (CORRECT reason + WHY EACH DISTRACTOR IS WRONG per option). Fixed tp-008 confused diversity calc explanation. AS/NZS 3000 clause references throughout. DB reloaded: 20 questions. Exposed via study/* endpoints and exam_results. research/seed_questions.json v2.0 |
| 2026-04-11 | TASK 7 | **COMPLETE** | Weakness Detection Engine: GET /api/weak-zones/{user_id} auto-flags topics <70% combined accuracy (exam 2x / review 1x weighted) as weak zones; 70-80% as caution; <2 attempts excluded from flagging. GET /api/weak-zones/{user_id}/review-queue returns prioritised due/new questions ordered by topic urgency. drill_priority list for next-session targeting. backend/main.py |
| 2026-04-11 | TASK 8 | **COMPLETE** | Progress Dashboard + Streaks: GET /api/study/dashboard/{user_id} (streak counter, total Qs, overall accuracy, SM-2 due today, exam pass rate, recent 5 exams, weakest/strongest topics ×3, study time estimate); GET /api/study/progress/{user_id} (per-topic mastery with SM-2 strength); GET /api/study/priority/{user_id} (urgency ranking with recommended_action per topic). PostgreSQL schema: study_sessions table added. backend/main.py + schema/database.sql |
| 2026-04-11 | TASK 9 | **COMPLETE (DESIGN)** | Stripe Freemium Integration design doc: freemium model (free: Topics 1–2 + 1 exam; premium ¥1,500/mo EWRB Complete), Stripe product/pricing (JPY ¥1,500/mo, ¥15,000/yr), Stripe Checkout architecture, webhook event routing, tier gate logic, API endpoints (create-checkout-session, webhooks/stripe, user/subscription, cancel-subscription), DB migration SQL, env vars, testing with Stripe CLI. Deliverables: design/stripe_freemium_design.md + schema/stripe_migration.sql. Implementation-ready checklist included.

---

*Source of truth - do not edit history, only append.*
| 2026-04-11 | TASK 10 | **COMPLETE** | SM-18 vs SM-2 evaluation: docs/sm18_vs_sm2.md. Verdict: stick with SM-2 for MVP. FSRS requires tuning data we don't have, long-cycle optimization doesn't compound for exam-prep users, 2-3 week delay for ~5-10% improvement. Post-launch upgrade path with trigger conditions (1k+ MAU, 50+ reviews/week, 3mo retention). |
| 2026-04-11 | HEARTBEAT | **OK** | No pending tasks. MVP fully shipped. Awaiting next direction. |
| 2026-04-11 05:15 UTC | HEARTBEAT | **OK** | No pending tasks. MVP fully shipped. |
| 2026-04-11 05:36 UTC | HEARTBEAT | **OK** | No pending tasks. MVP fully shipped. |
| 2026-04-11 03:54 UTC | HEARTBEAT | **OK** | No pending tasks. MVP fully shipped. |

---

*Source of truth - do not edit history, only append.*

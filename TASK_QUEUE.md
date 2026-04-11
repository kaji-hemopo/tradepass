# TradePass — TASK QUEUE

**Micro-SaaS MVP**: Spaced-repetition exam engine for NZ trade certifications (EWRB Electricians first).

---

## Backlog

- [x] **TASK 1**: Deep research into NZ EWRB Electrician's Theory and Regulations exams — DONE. See research/EWRB_EXAM_SPECS.md
  - Pass marks, time limits, high-failure topics (Volt Drop, AS/NZS 3000, etc.)
  - Deliverable: `research/EWRB_EXAM_SPECS.md`

- [x] **TASK 2**: Generate `research/seed_questions.json` — DONE
  - 20 highly accurate simulated EWRB exam questions covering Voltage Drop (4Qs), Fault Loop Zs (3Qs), AS/NZS 3000 (5Qs), Insulation Resistance (3Qs), Protection & Discrimination (2Qs), Maximum Demand (2Qs), Supply Systems (2Qs), Motor Starters (1Qs), Switchboards (1Qs), Circuit Design (1Qs)
  - Delivered: `research/seed_questions.json`

- [x] **TASK 3**: Design PostgreSQL schema (`schema/database.sql`) — DONE
  - SuperMemo-2 spaced repetition fields
  - Questions, exams, users, progress tables
  - Delivered: `schema/database.sql`

- [x] **TASK 4**: Initialize local backend (Python/FastAPI) — DONE
  - SQLite mock database (tradepass.db)
  - Load seed_questions.json (20 Qs loaded into 11 topics)
  - FastAPI app: topics, questions, SM-2 review, due/new queues, user stats endpoints
  - Delivered: `backend/` (main.py, database.py, sr.py, load_seed_data.py, requirements.txt)

---

## Backlog — Board Member Additions

*Initiatives that make TradePass actually competitive vs Stuvia/TradeLab, not just a flashcard CRUD.*

- [x] **TASK 5**: Add Exam Simulation Mode — DONE
  - Full exam simulation implemented: `POST /api/exams/start`, `GET /api/exams/{id}`, `POST /api/exams/{id}/answer`, `POST /api/exams/{id}/submit`, `GET /api/exams/{id}/results`
  - Timed mock exams with auto-expiry, pass/fail, per-topic breakdown, 2hr EWRB-style timer
  - Delivered: `backend/main.py` (Exam Simulation Mode section)

- [x] **TASK 6**: Explanation-Rich Answers — DONE
  - All 20 Qs rebuilt: structured per-distractor explanations (CORRECT reason + WHY EACH DISTRACTOR IS WRONG). AS/NZS 3000 clause references throughout. Fixed tp-008 confused diversity calc explanation. DB reloaded (20 questions). Exposed via study/* endpoints and exam_results.
  - research/seed_questions.json v2.0

- [x] **TASK 7**: Weakness Detection Engine — DONE
  - GET /api/weak-zones/{user_id}: auto-flags topics <70% combined accuracy as weak zones, 70-80% as caution, excludes <2 attempt topics. Weighted combined accuracy (exam 2x / review 1x).
  - GET /api/weak-zones/{user_id}/review-queue: returns prioritised due/new questions ordered by weak-topic urgency.
  - Delivered: `backend/main.py`

- [x] **TASK 8**: Progress Dashboard + Streaks — DONE
  - GET /api/study/dashboard/{user_id}: streak counter, total Qs, overall accuracy, SM-2 due today, exam pass rate, recent 5 exams, weakest/strongest topics (×3), study time estimate
  - GET /api/study/progress/{user_id}: per-topic mastery with SM-2 strength
  - GET /api/study/priority/{user_id}: urgency ranking with recommended_action per topic
  - schema/database.sql: study_sessions table added (PostgreSQL)
  - Delivered: backend/main.py + schema/database.sql

- [x] **TASK 9**: Stripe Freemium Integration (Design Only) — DONE
  - Design doc: `design/stripe_freemium_design.md` — full spec: freemium model (free: Topics 1–2 Voltage Drop + Fault Loop Zs + 1 exam; premium ¥1,500/mo EWRB Complete), Stripe JPY pricing (¥1,500/mo, ¥15,000/yr), Checkout + webhook architecture, tier gates, API endpoints, DB migration SQL, testing with Stripe CLI.
  - Migration: `schema/stripe_migration.sql` (PostgreSQL + SQLite Python helper)
  - Implementation-ready checklist in design doc

- [x] **TASK 10**: SM-18 vs SM-2 Algorithm Evaluation — DONE
  - Recommendation doc: `docs/sm18_vs_sm2.md` — verdict: stick with SM-2 for MVP. FSRS requires hundreds of review data points to tune, delivers ~5-10% improvement over months of daily use, costs 2-3 weeks to implement. Our exam-prep users won't live in the system long enough to realize the compound benefit. Post-launch upgrade path defined with trigger conditions (1k+ MAU, 50+ reviews/week, 3mo retention).
  - No code changes needed — current SM-2 implementation in `backend/sr.py` is correct and shippable.

---

*All tasks complete. TradePass MVP implementation is done.*

---

*Update this file as tasks complete. Top unchecked = next wakeup priority.*

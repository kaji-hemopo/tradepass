# TradePass — TASK QUEUE

**Micro-SaaS MVP**: Spaced-repetition exam engine for NZ trade certifications (EWRB Electricians first).

---

## Backlog

- [x] **TASK 1**: Deep research into NZ EWRB Electrician's Theory and Regulations exams — DONE. See research/EWRB_EXAM_SPECS.md
  - Pass marks, time limits, high-failure topics (Volt Drop, AS/NZS 3000, etc.)
  - Deliverable: `research/EWRB_EXAM_SPECS.md`

- [ ] **TASK 2**: Generate `research/seed_questions.json`
  - 20 highly accurate simulated EWRB exam questions
  - Must match actual exam format, difficulty, topics

- [ ] **TASK 3**: Design PostgreSQL schema (`schema/database.sql`)
  - SuperMemo-2 spaced repetition fields
  - Questions, exams, users, progress tables

- [ ] **TASK 4**: Initialize local backend (Python or Go)
  - SQLite mock database
  - Load seed_questions.json
  - Basic CRUD + SR review endpoint

---

## Backlog — Board Member Additions

*Initiatives that make TradePass actually competitive vs Stuvia/TradeLab, not just a flashcard CRUD.*

- [ ] **TASK 5**: Add Exam Simulation Mode
  - Timed 50-question mock exam (2hr timer, exact EWRB conditions)
  - Random question selection from full bank
  - Results screen: pass/fail, score %, topic breakdown
  - Why: Tradies need to know "can I pass the real thing?" — single biggest engagement driver

- [ ] **TASK 6**: Explanation-Rich Answers
  - Every question: full explanation (why correct answer, why others wrong)
  - Reference the specific AS/NZS 3000 clause or regulation
  - Why: Dump sites give answers; we give understanding. Reduces frustration, increases pass confidence

- [ ] **TASK 7**: Weakness Detection Engine
  - Track per-topic accuracy across reviews
  - Auto-flag topics below 70% as "weak zones"
  - Prioritize weak topics in next review sessions
  - Why: Voltage drop and fault loop are 40% of fails — targeted drilling beats random review

- [ ] **TASK 8**: Progress Dashboard + Streaks
  - Daily streak counter (gamification)
  - Topic mastery heatmap
  - Review forecast (next 7 days)
  - Why: Engagement loops keep users coming back. Stuvia has none of this

- [ ] **TASK 9**: Stripe Freemium Integration (Design Only)
  - Free tier: 50 questions (first 2 topics)
  - Premium tier unlock: ¥1,500/mo (~NZD $15/mo) — "EWRB Complete" ($149 EWRB exam >> $15 sub)
  - Upsell to full question bank + exam sim
  - Why: Low-risk digital product. Tradies pay for anything that gets them the ticket

- [ ] **TASK 10**: SM-18 vs SM-2 Algorithm Evaluation
  - SM-2 (current spec): simple, proven
  - SM-18/FSRS: more accurate scheduling, harder to implement
  - Recommendation doc: stick with SM-2 for MVP, note SM-18 as post-launch upgrade
  - Why: Don't let perfect be enemy of shipped. MVP needs working product, not optimal algorithm

---

## Ready for Heartbeat

Top pending: TASK 2 (seed questions). Then TASK 3 + TASK 4 parallelizable. TASK 5-10 are post-MVP enhancements.

---

*Update this file as tasks complete. Top unchecked = next wakeup priority.*

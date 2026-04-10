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

## Ready for Heartbeat

Above tasks ordered by dependency. TASK 1 must complete before TASK 2 (needs exam specs). TASK 3 and TASK 4 are parallelizable after TASK 1.

---

*Update this file as tasks complete. Top unchecked = next wakeup priority.*

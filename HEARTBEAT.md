# TradePass Heartbeat

## Schedule
- **Interval**: 20 minutes (via OpenClaw cron `2892d832`)
- **Policy**: Execute next task, update MEMORY.md, write next task to HEARTBEAT.md.

## Control
- `paused`: Stop heartbeat until Jackson re-enables.
- `active`: Running every 20m.

## Status: ACTIVE — TASK 38 READY

TASK 37 (Flagged Questions Review Queue) is **complete** as of 2026-04-11 16:57 JST.

---

## TASK 36: Weak Zone Deep Dive + Question History Review — ✅ COMPLETE (16:07 JST 2026-04-11)

- **`question_flags` table** added to database.py (user_id, question_id, flagged_at, UNIQUE). `CURRENT_TIMESTAMP` as SQLite-compatible default.
- **`GET /api/study/topic/{topic_id}/question-history/{user_id}`** — returns all questions user has seen in a topic, merged from exam_answers + review_logs. Shows question_id, question_text, difficulty, best_score, attempt_count, times_correct, times_incorrect, last_attempted, last_result. Exam data takes precedence when both sources have the same question. Backend restarted (PID 44757 on :8000). Smoke test: topic 1 → 1 question (tp-027, 9 attempts, 80% best score); topic 2 → 1 question (tp-033, 7 attempts, 66.7% best score) ✅.
- **`POST /api/study/questions/{question_id}/flag`** — `FlagRequest` model (user_id: str). Toggle INSERT/DELETE on question_flags. Returns `{"flagged": true|false}`. FlagRequest Pydantic model added to main.py. Smoke test: tp-027 toggle ON ✅, check ✅, toggle OFF ✅, check ✅.
- **`GET /api/study/questions/{question_id}/flag`** — returns `{"flagged": true|false}`.
- **Streamlit flag toggle**: added to both Study Session (question loop) and Focus Mode (focus loop) after the explanation expander. Calls flag endpoint on toggle, reruns to update button label. Button: "☆ Flag for Exam" / "⭐ Flagged — Unflag".
- **"📋 View Question History →" button** on Topic Trends page (col1, per topic row). Sets `qhist_topic_id` in session_state and navigates to `_qhist_modal` pseudo-page.
- **`_render_qhist_modal()`** function: shows topic name as title, fetches question-history endpoint, renders each question as expandable row with difficulty badge, Attempts/Last/Best columns, ✅/❌ counts, and flag toggle button. "← Back to Topic Trends" button returns.
- Streamlit restarted (PID 44970 on :8501). Syntax check passed. All backend endpoints smoke-tested ✅. README.md updated with new sections: Question History drill-down, Flag for Exam.
- No blockers.

---

## TASK 37: Flagged Questions Review Queue — ✅ COMPLETE (16:57 JST 2026-04-11)

- **`GET /api/study/flags/{user_id}`** confirmed working: returns question_id, question_text, difficulty, topic_name, flagged_at sorted by flagged_at DESC. Backend was stale (running PID 44779 without the endpoint) — restarted to PID 48582 ✅.
- **`POST /api/study/solo/{question_id}`** added — grades a single question in isolation. Accepts `user_id` + `quality` (0–5), writes review_log + upserts user_progress via SM-2, returns full result dict. Bug fixed: `conn.execute()` args must be tuple not positional.
- **`page_flagged()` enhanced**: "Study This Question →" button now sets `study_focus_question_id` session_state and navigates to Study Session with fresh setup.
- **Solo study flow**: Study Session setup phase detects focus question → fetches via `GET /api/questions/{question_id}` → loads as single-item session → skips to question phase. "Finish Session" grades inline via `POST /api/study/solo/{question_id}` → shows `solo_results` phase with SM-2 delta display, achievements, sound, share block.
- README.md updated with 📌 Flagged Questions Review Queue section. MEMORY.md updated. Streamlit PID 48616, Backend PID 48582.
- No blockers.

---

## TASK 38: Onboarding Wizard / First-Time User Experience

**Priority**: Medium
**Description**: Improve the first-time user experience with an optional guided onboarding flow that walks new users through the app's core features after registration, rather than dropping them straight onto the (empty) dashboard.

**Steps**:
1. **Backend**: No new endpoints needed.
2. **Streamlit `page_onboarding()`**: A full-screen onboarding wizard (3–4 steps) shown once after registration:
   - Step 1: "Welcome to TradePass!" — display name, quick value prop, "Next →"
   - Step 2: "Try your first Study Session" — explains SM-2 spaced repetition in 2 sentences, "Start Now →" button that pre-configures and launches Study Session with 5 new questions
   - Step 3: "Check your Progress" — launch Dashboard
   - Step 4: "You're ready!" — launch Dashboard
3. After completing or skipping, set `st.session_state["onboarding_done"] = True` and store in `st.query_params` so it's not shown again on refresh.
4. On login, check `onboarding_done` in session_state — if False or missing, redirect to onboarding page before Dashboard.
5. Smoke test: new registration → onboarding shown → complete → dashboard.
6. Update README.md.
7. Update MEMORY.md.
8. Update HEARTBEAT.md with next task.

*Updated: 2026-04-11 16:57 JST*

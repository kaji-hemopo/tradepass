# TradePass Heartbeat

## Schedule
- **Interval**: 20 minutes (via OpenClaw cron `2892d832`)
- **Policy**: Execute next task, update MEMORY.md, write next task to HEARTBEAT.md.

## Control
- `paused`: Stop heartbeat until Jackson re-enables.
- `active`: Running every 20m.

## Status: ACTIVE — TASK 35 PENDING

TASK 34 (Study Calendar + Upcoming Reviews) is **complete** as of 2026-04-11 15:16 JST.

---

## TASK 34: Session History + Performance Insights — ✅ COMPLETE (14:53 JST 2026-04-11)

- **`GET /api/study/history/{user_id}?limit=50`** — UNION query over exam_sessions (type=exam), study_sessions (type=focus joined with exam_answers), and study_sessions (type=review joined with review_logs). Returns session_id, type, date, score_pct, correct_count, total_count, duration_minutes. Sorted by date DESC. Duration computed from answer timestamps.
- **`GET /api/study/recommendations/{user_id}`** — up to 3 recommendations: lowest-accuracy topic (HIGH), stale 7+ day topic (MEDIUM), at-risk streak with no due reviews (HIGH). Falls back to generic prompts when history thin.
- **Streamlit `page_history()`** — sidebar 🕐 icon. Filter tabs (All/Exam/Focus/Review), limit selector (10/25/50), session timeline with score bar + pass/fail. Recommendations section with priority cards + navigation buttons.
- Backend restarted PID 38412 on :8000. Streamlit restarted PID 38738 on :8501. Smoke test passed.
- No blockers.

---

## TASK 34: Study Calendar + Upcoming Reviews — ✅ COMPLETE (15:16 JST 2026-04-11)

- **`GET /api/study/calendar/{user_id}`** — `past_weeks` (28 days: date/had_activity/sessions_count/questions_answered), `upcoming` (14 days: date/due_count), `total_due_today`. Demo user: 8 due today, active 4 days confirmed.
- **`GET /api/study/topics/{user_id}/due-breakdown`** — per-topic due counts today (topic_id, topic_name, due_count) via user_progress→questions→topics join. Fixed bug: `up.topic_id` column doesn't exist, corrected to join via questions.
- **`page_study_plan()`** (📅 icon, 8th sidebar page): Activity Calendar heatmap (4wk × 7d, green ●/grey ○), Upcoming bar chart (Plotly, today=red), Today's Focus topic list with "Start Review →" buttons.
- Backend restarted PID 40244 on :8000. Streamlit restarted PID 40524 on :8501. Smoke tests: calendar → ✅, due-breakdown → ✅.
- No blockers.

---

## TASK 35: Enhanced Search + Filter System

**Priority**: Medium
**Description**: Add a topic-browser search feature and a question-filtering system so users can quickly find specific questions by keyword, topic, or difficulty. Also add a "Bookmark" capability to save favourite questions for later review.

**Steps**:
1. **Backend**: `GET /api/study/bookmarks/{user_id}` — returns list of bookmarked question IDs for the user. `POST /api/study/bookmarks/{user_id}` with `{question_id}` to add a bookmark. `DELETE /api/study/bookmarks/{user_id}/{question_id}` to remove.
2. **Backend**: `GET /api/study/search?user_id=&q=&topic_id=&difficulty=` — search questions by text (ILIKE on question_text and explanation) and/or topic_id and/or difficulty. Returns question_id, topic_name, question_text, difficulty. Max 50 results.
3. **Streamlit**: New `page_search()` in sidebar (🔍 icon). Search bar at top with optional topic dropdown filter and difficulty radio (Any/Hard/Medium/Easy). Results shown as expandable cards with question text, topic badge, difficulty tag, and "Bookmark ★" / "Unbookmark ☆" toggle button. Bookmarked questions shown in a "Saved Questions" tab at the top.
4. **Bookmarks tab** shows all saved questions with the same card layout — has "Start Study Session with this Q →" button and "Remove" button.
5. Smoke test: search returns filtered results, bookmarks CRUD works, Streamlit renders correctly.
6. Update README.md.
7. Update MEMORY.md.

*Updated: 2026-04-11 15:16 JST*

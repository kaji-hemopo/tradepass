# TradePass — README

> NZ EWRB Electrical certification study app with SM-2 spaced repetition engine.
> FastAPI backend (port 8000) + Streamlit frontend (port 8501).

---

## Quick Start

### 1. Backend

```bash
cd TradePass/backend
pip install -r requirements.txt
python load_seed_data.py --demo   # loads 72 questions + seeds demo user
python main.py                    # starts FastAPI on :8000
```

**Or with environment overrides:**

```bash
PYTHON_ENV=development TRADEPASS_API_URL=http://localhost:8000 \
CORS_ORIGINS=http://localhost:8501 JWT_SECRET=your-secret \
python main.py
```

### 2. Frontend

```bash
cd TradePass
pip install -r backend/requirements.txt   # streamlit, requests, plotly
streamlit run app.py --server.port 8501    # starts Streamlit on :8501
```

Open **http://localhost:8501** in your browser.

---

## Demo Accounts

| Email | Password | Profile |
|-------|----------|---------|
| `demo@test.com` | `demo1234` | **Established user** — 9-day streak, 22 questions answered, 63% accuracy, 5 exam sessions, mixed weak/strong topics. |
| `power@test.com` | `power1234` | **Struggling new user** — 5-day streak, 33% accuracy, 11 weak topics, Focus Mode active. |

Use the **"🚀 Try Demo Account"** button on the login screen for instant access (defaults to `demo@test.com`). To preview a different profile, expand **"🗂 Compare Demo Profiles"** on the login page and click **"Load Successful Learner"** or **"Load Struggling Beginner"** — this pre-fills the credentials in the login form so you can sign in directly.

**Reset a demo account** (clear all history, keep the account): click **"🔄 Reset My Progress"** on the Profile page. This clears all study history and streak, returning the dashboard to its fresh-user empty state.

A new (unregistered) account starts with **zero history** — no due reviews, no topic data. Work through Study Session → Review → Focus Mode to build history.

## Questions: 72 total across 11 topics

The question bank covers all key exam areas including Voltage Drop, Fault Loop Impedance, AS/NZS 3000, Insulation Resistance, Maximum Demand, RCD/MCB Protection, Supply Systems, Motor Starters, Switchboards, Circuit Design, and Testing & Verification.

---

## What Each Section Does

### 📊 Dashboard
Landing page after login. Shows your **streak**, **total questions answered**, **overall accuracy**, and **cards due today**. A daily goal progress bar appears at the top (below streak metrics). A motivational message below the Quick Start widget reflects your current streak status. When you beat your personal longest streak, `st.balloons` fires with a congratulations banner. Scroll down for achievements, weakest/strongest topics, and recent exam results.

### 📖 Study Session
General study loop. Select a mode ("Review", "Focus Weak Zones", or "Mixed") and a card count (5–30). Questions are pulled from your SM-2 review queue, new questions you've never seen, and weak-topic drills. Rate each card "Knew it ✓" or "Didn't know ✗" — SM-2 grades your session and updates easiness factors.

### 🎯 Focus Mode
Drill a **single weak topic** with a short round (5–10 Qs). Topics are pre-sorted by urgency (priority score). Requires at least some study history to be available — new users get a "no weak topics" message until they've built a history. Best for targeting Switchboards, Insulation Resistance, or other low-accuracy topics.

### 📝 Exam Mode
Simulated timed exam (5–60 min, 5–30 questions). Questions drawn from never-attempted or low-accuracy topics first. Auto-submits when time expires. ≥70% = pass. Results include per-topic breakdown showing which areas cost you points.

### 📈 Topic Trends
Bar charts of current vs. best accuracy per topic. Priority chart color-codes topics by recommended action:
- 🔴 **exam** — never attempted
- 🟡 **review** — cards are due for review
- 🟢 **mastered** — >80% accuracy + strong easiness factor
- 🔵 **study** — general study recommended

### 🏆 Achievements
Badge system with 17 badges across 6 categories: Streak Milestones, Volume Milestones, Accuracy Milestones, Exam Milestones, Focus Milestones, and Coverage Milestones. View earned/locked status per badge with earned date. The dashboard shows a compact earned count + "View all →" link. When you earn a new badge during a session, `st.balloons` fires with a congratulations message. Earned badges display on the Dashboard banner; the full collection is in the dedicated Achievements page.

### 🧊 Streak Freeze (Lifeline)
Streak Freeze tokens protect your streak when you miss a day. When `streak_status == "at_risk"` and a freeze token is available, it is **automatically consumed** the next time you complete a study activity and a gap is detected — your streak is preserved and the token is spent. Users get **1 token on registration**. The Dashboard shows a 🧊 badge on the streak metric when a freeze is available. Profile page shows the current count, an explanation of how they work, and an **"Activate Streak Freeze Now"** button to manually consume a token. Backend: `POST /api/study/streaks/{user_id}/use-freeze` for manual activation; auto-consumed in `_update_streak()` when gap detected and `streak_freeze_tokens > 0`.

### 📅 Study Plan
Study calendar with three views: (1) **Activity Calendar** — 4-week heatmap grid showing active days (green ●) vs inactive (grey ○) with a week-by-week breakdown. (2) **Upcoming Reviews** — Plotly bar chart of cards due per day over the next 14 days, with today highlighted in red. (3) **Today's Focus** — per-topic breakdown of cards due today with "Start Review →" buttons that navigate directly to Study Session. Helps users plan their study schedule and see their streak at a glance on a calendar.

### 🔍 Search & Bookmarks
Search the question bank by keyword, topic, and/or difficulty. Bookmarks let you save favourite questions for later review. The **Saved Questions** tab lists all bookmarked questions with quick access to start a study session with that specific question. Bookmark toggle available on every search result card and on each saved question card.

### 📋 Question History (Weak Zone Drill-Down)
From the **Topic Trends** page, click **"📋 View Question History →"** next to any topic to open a detailed drill-down panel showing every question you've attempted in that topic. Each row shows: question text (truncated), difficulty badge, attempt count, last result (✅/❌), best score, and ✅/❌ counts. Flag individual questions for exam review using the **☆ Flag for Exam** button (⭐ Unflag to remove). The history combines data from both exam sessions and review sessions, merged per question.

### ⭐ Flag for Exam
Mark any question for exam prep review (separate from Bookmarks). The **☆ Flag for Exam** toggle appears on question cards in Study Session and Focus Mode. Starred questions can be reviewed before an exam. The flag state persists in the `question_flags` table and survives streak resets.

### 📌 Flagged Questions Review Queue
The **Flagged Questions** page (sidebar, between Search and Profile) shows all your ⭐-flagged exam-prep questions in one place. Each card shows the topic name, difficulty badge, and full question text. Actions per card:
- **⭐ Remove Flag** — unflags the question (live update, no page reload needed)
- **📖 Study This Question →** — opens a dedicated **Solo Study** session focused on just that one question: you see the question, reveal the answer, rate yourself (Knew it / Didn't know), and get instant SM-2 feedback (updated easiness factor + next review interval) inline without starting a full review session. Grading happens via `POST /api/study/solo/{question_id}`.

The list is sorted by most recently flagged. Empty state shown when no questions are flagged yet.

### 👤 Profile
Your account info, current/longest streak, daily goal progress bar, and today's question count + accuracy. A **daily goal slider** (1–100 questions/day, step 5) lets you adjust your daily target at any time — save calls `PUT /api/study/streaks/{user_id}/daily-goal`. Use the **"🔄 Reset My Progress"** button to clear all study history and restart as a fresh user — useful for demos.

---

## Key Flows

### New User → First Study Session

1. Register a new account (email + password + display name)
2. Dashboard shows all zeros (expected — no history yet)
3. Go to **Study Session** → pick Review mode → Start Session
4. Answer cards, rate yourself, finish session
5. SM-2 grades your answers and schedules cards for future review dates
6. Dashboard now shows activity

### Demo User → Full Demo Walkthrough

1. Click **🚀 Try Demo Account** on login screen
2. View **Dashboard** — streak, accuracy, due reviews
3. Run a **Study Session** (Review mode, 10 cards)
4. Check **Focus Mode** — pick "Switchboards" or another weak topic
5. Take a 15-question **Exam** (20 min timer)
6. Review **Topic Trends** for priority chart
7. Check **Profile** for streak and today's progress

---

## Architecture

```
TradePass/
├── backend/
│   ├── main.py          # FastAPI app — all /api/study/* + /api/auth/* endpoints
│   ├── database.py      # SQLite schema + SM-2 engine
│   ├── sr.py            # SM-2 spaced repetition logic
│   ├── auth.py          # JWT helpers
│   ├── load_seed_data.py # Question loader (--demo flag seeds demo user)
│   ├── seed_demo_user.py # Demo user data generator
│   └── tradepass.db     # SQLite database
├── app.py               # Streamlit frontend (port 8501)
└── docs/                # Design docs
```

**API base:** `http://localhost:8000` (override with `TRADEPASS_API_URL`)
**Auth:** Bearer JWT. Token stored in `session_state`. All `/api/study/*` endpoints require it.

---

## Environment Variables

| Variable | Default | Notes |
|---|---|---|
| `PYTHON_ENV` | `production` | `development` = verbose error pages |
| `TRADEPASS_API_URL` | `http://localhost:8000` | Frontend → Backend URL |
| `CORS_ORIGINS` | `http://localhost:8501,http://127.0.0.1:8501` | Comma-separated |
| `JWT_SECRET` | `dev-secret-change-in-prod` | Change before deploying |

---

## Topics Covered (11)

1. Voltage Drop
2. Fault Loop Impedance
3. AS/NZS 3000 Application
4. Insulation Resistance
5. Maximum Demand
6. RCD/MCB Protection
7. Supply Systems
8. Motors & Motor Starters
9. Switchboards
10. Protection & Discrimination
11. Circuit Design

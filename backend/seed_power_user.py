"""
TradePass — Power User Seeder
Creates power@test.com — a struggling new user with low accuracy,
short streak, and early history — to demonstrate Focus Mode and
personalised recommendations.

Run: python backend/seed_power_user.py
"""
import sys, uuid, json, random, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from database import get_connection, init_db
from auth import hash_password

POWER_EMAIL = "power@test.com"
POWER_PASSWORD = "power1234"
POWER_USER_ID = "power-user-001"
DAYS_AGO = 3  # recent account

def seed_power_user():
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    # ── Check if power user already exists ───────────────────────────────
    cur.execute("SELECT id FROM users WHERE email = ?", (POWER_EMAIL,))
    user_exists = cur.fetchone()

    # Also check if exam data was seeded (script may have been re-run after user created)
    cur.execute("SELECT COUNT(*) FROM exam_sessions WHERE user_id = ?", (POWER_USER_ID,))
    exam_count = cur.fetchone()[0] if user_exists else 0

    if user_exists and exam_count > 0:
        print(f"Power user {POWER_EMAIL} already fully seeded — skipping.")
        conn.close()
        return

    user_id = POWER_USER_ID

    if not user_exists:
        # ── Create power user ─────────────────────────────────────────────
        cur.execute(
            """
            INSERT INTO users (id, email, password_hash, display_name, timezone, is_premium, created_at)
            VALUES (?, ?, ?, ?, 'Asia/Tokyo', 0, datetime('now', ?))
            """,
            (user_id, POWER_EMAIL, hash_password(POWER_PASSWORD), "Power User", f"-{DAYS_AGO} days"),
        )

        # ── Study streak — short, struggling ───────────────────────────────
        cur.execute(
            """
            INSERT INTO study_streaks (user_id, current_streak, longest_streak, last_study_date, total_study_days)
            VALUES (?, 1, 1, date('now', '-1 day'), 2)
            """,
            (user_id,),
        )

        # ── Achievements — only one (first question) ───────────────────────
        achievements = [
            ("first_question", "First Steps", "Answered your first question"),
        ]
        for badge_key, badge_name, description in achievements:
            cur.execute(
                """
                INSERT OR IGNORE INTO achievements (user_id, badge_key, badge_name, description, earned_at)
                VALUES (?, ?, ?, ?, datetime('now', '-1 day'))
                """,
                (user_id, badge_key, badge_name, description),
            )
        print(f"Power user {POWER_EMAIL} created with base data.")
    else:
        print(f"Power user {POWER_EMAIL} exists — adding exam/SM2 data only.")

    # ── Get topic IDs ────────────────────────────────────────────────────
    cur.execute("SELECT id, slug FROM topics")
    topics = {row["slug"]: row["id"] for row in cur.fetchall()}
    if not topics:
        print("ERROR: No topics found. Run `python backend/load_seed_data.py` first.")
        conn.close()
        return

    cur.execute("SELECT id, topic_id FROM questions")
    questions = cur.fetchall()
    q_map = {row["topic_id"]: row["id"] for row in questions}

    # ── Seed a few poor exam sessions ─────────────────────────────────────
    # Session 1: 2 days ago — poor on Voltage Drop (30%) and Fault Loop (40%)
    # This gives the user two weak topics to focus on
    eid1 = "power-exam-01"
    cur.execute(
        """
        INSERT INTO exam_sessions
            (id, user_id, question_ids, topic_ids, total_questions, correct_count,
             score_percent, status, started_at, completed_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'completed',
                datetime('now', '-2 days', '-3 hours'),
                datetime('now', '-2 days', '-2 hours'),
                datetime('now', '-2 days'))
        """,
        (eid1, user_id,
         json.dumps([f"q-{i}" for i in range(10)]),
         json.dumps([topics["voltage-drop"], topics["fault-loop-zs"]]),
         10, 3, 30.0),
    )

    # Add exam answers for session 1
    topic_qs = {
        topics["voltage-drop"]: (7, 2),  # 7 questions, 2 correct = ~28%
        topics["fault-loop-zs"]: (3, 1),  # 3 questions, 1 correct = ~33%
    }
    q_idx = 0
    for tid, (total, correct) in topic_qs.items():
        for i in range(total):
            real_qid = q_map.get(tid, f"q-{tid}")
            is_corr = 1 if i < correct else 0
            cur.execute(
                """
                INSERT INTO exam_answers (id, exam_session_id, question_id, selected_answer_index, is_correct, topic_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"power-ea-1-{q_idx}", eid1, real_qid, 0, is_corr, tid),
            )
            q_idx += 1

    # Session 2: yesterday — poor on Insulation Resistance (40%)
    eid2 = "power-exam-02"
    cur.execute(
        """
        INSERT INTO exam_sessions
            (id, user_id, question_ids, topic_ids, total_questions, correct_count,
             score_percent, status, started_at, completed_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'completed',
                datetime('now', '-1 days', '-2 hours'),
                datetime('now', '-1 days', '-1 hour'),
                datetime('now', '-1 days'))
        """,
        (eid2, user_id,
         json.dumps([f"q-{i}" for i in range(5)]),
         json.dumps([topics["insulation-resistance"]]),
         5, 2, 40.0),
    )
    for i in range(5):
        real_qid = q_map.get(topics["insulation-resistance"], f"q-{topics['insulation-resistance']}")
        is_corr = 1 if i < 2 else 0
        cur.execute(
            """
            INSERT INTO exam_answers (id, exam_session_id, question_id, selected_answer_index, is_correct, topic_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (f"power-ea-2-{i}", eid2, real_qid, 0, is_corr, topics["insulation-resistance"]),
        )

    # ── SM-2 progress — all weak/overdue ────────────────────────────────
    # User has only answered a handful of questions, all with low EF
    sm2_progress = [
        # Slug, EF, interval, reps, due_offset, correct_count, total
        ("voltage-drop",         1.1, 0, 0, "-1 days",  2,  7),
        ("fault-loop-zs",       1.3, 0, 0, "-2 days",  1,  3),
        ("insulation-resistance", 1.2, 0, 0, "-1 days",  2,  5),
        ("as-nzs-3000",         1.0, 0, 0, "-3 days",  0,  2),  # never passed
        ("max-demand",          1.4, 1, 1, "+0 days",  2,  4),
    ]

    for p_idx, (slug, ef, interval, reps, due_offset, correct_count, total_reviews) in enumerate(sm2_progress):
        tid = topics.get(slug)
        if not tid or tid not in q_map:
            continue
        qid = q_map[tid]
        cur.execute(
            """
            INSERT INTO user_progress
                (id, user_id, question_id, easiness_factor, interval, repetitions,
                 next_review_date, total_reviews, correct_count, last_reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, date('now', ?), ?, ?, datetime('now', ?, '-1 day'))
            """,
            (
                f"power-up-{p_idx}", user_id, qid, ef, interval, reps,
                due_offset, total_reviews, correct_count, due_offset,
            ),
        )
        for r in range(min(total_reviews, 3)):
            quality = 4 if r < (correct_count * 4 // total_reviews) else 2
            cur.execute(
                """
                INSERT INTO review_logs
                    (id, user_id, question_id, quality, quality_numeric,
                     easiness_factor_before, easiness_factor_after,
                     interval_before, interval_after, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', ?, '-1 day', ?))
                """,
                (
                    f"power-rl-{p_idx}-{r}", user_id, qid, quality, quality,
                    ef - 0.1, ef, max(0, interval - 1), interval,
                    due_offset, f"-{r+1} hours",
                ),
            )

    conn.commit()

    # ── Verify with API ──────────────────────────────────────────────────
    r = requests.post(
        "http://localhost:8000/api/auth/login",
        json={"email": POWER_EMAIL, "password": POWER_PASSWORD},
        timeout=10,
    )
    if r.status_code != 200:
        print(f"Login failed: {r.text}")
        conn.close()
        return

    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    pri_resp = requests.get(
        f"http://localhost:8000/api/study/priority/{POWER_USER_ID}",
        headers=headers, timeout=10
    )
    scores = pri_resp.json()["topics"] if pri_resp.ok else []

    dash_resp = requests.get(
        f"http://localhost:8000/api/study/dashboard/{POWER_USER_ID}",
        headers=headers, timeout=10
    )
    dash = dash_resp.json() if dash_resp.ok else {}

    print(f"\n✅ Power user seeded: {POWER_EMAIL} / {POWER_PASSWORD}")
    print(f"   User ID: {user_id}")
    print(f"   Streak: {dash.get('streak_days', 0)} day(s) | Accuracy: {dash.get('overall_accuracy_pct', 0)}%")
    print(f"   Total questions answered: {dash.get('total_questions_answered', 0)}")
    print(f"\n   Topic priority scores (top 5):")
    for row in sorted(scores, key=lambda x: x["priority_score"], reverse=True)[:5]:
        print(f"     {row['topic_name']:<32} {row['priority_score']:.1f}  [{row['recommended_action']}]")

    weak = [r for r in scores if r["priority_score"] >= 40]
    if weak:
        print(f"\n   Focus mode: AVAILABLE ({len(weak)} weak topic(s) >= 40)")
    else:
        print(f"\n   Focus mode: NOTE — no topics >= 40 yet")

    conn.close()


if __name__ == "__main__":
    seed_power_user()

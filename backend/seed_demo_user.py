"""
TradePass — Demo User Seeder
Creates demo@test.com with rich study history so the first-login
experience is compelling (non-empty dashboard, working focus mode, etc.)

Run: python backend/seed_demo_user.py
   or: python backend/load_seed_data.py --demo
"""
import sys, uuid, json, random, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from database import get_connection, init_db
from auth import hash_password, create_access_token

DEMO_EMAIL = "demo@test.com"
DEMO_PASSWORD = "demo1234"
DEMO_USER_ID = "demo-user-001"
DAYS_AGO = 7

def seed_demo_user():
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    # ── Check if demo user already exists ───────────────────────────────────
    cur.execute("SELECT id FROM users WHERE email = ?", (DEMO_EMAIL,))
    user_exists = cur.fetchone()
    exam_count = 0
    if user_exists:
        cur.execute("SELECT COUNT(*) FROM exam_sessions WHERE user_id = ?", (DEMO_USER_ID,))
        exam_count = cur.fetchone()[0]

    if user_exists and exam_count > 0:
        print(f"Demo user {DEMO_EMAIL} already fully seeded — skipping.")
        conn.close()
        return

    user_id = DEMO_USER_ID

    if not user_exists:
        # ── Create demo user ────────────────────────────────────────────────
        cur.execute(
            """
            INSERT INTO users (id, email, password_hash, display_name, timezone, is_premium, created_at)
            VALUES (?, ?, ?, ?, 'Asia/Tokyo', 1, datetime('now', ?))
            """,
            (user_id, DEMO_EMAIL, hash_password(DEMO_PASSWORD), "Demo User", f"-{DAYS_AGO} days"),
        )
        print(f"Demo user {DEMO_EMAIL} created with base data.")
    else:
        print(f"Demo user {DEMO_EMAIL} exists — re-seeding exam/SM2 data.")

    # ── Study streak — INSERT OR REPLACE so re-runs are safe ─────────────────
    cur.execute(
        """
        INSERT OR REPLACE INTO study_streaks (user_id, current_streak, longest_streak, last_study_date, total_study_days)
        VALUES (?, 5, 12, date('now', '-1 day'), 18)
        """,
        (user_id,),
    )

    # ── Achievements ─────────────────────────────────────────────────────────
    achievements = [
        ("first_question", "First Steps",    "Answered your first question"),
        ("streak_3",       "On Fire",        "3-day study streak"),
        ("accuracy_70",    "Getting There",  "Achieved 70% overall accuracy"),
        ("exam_pass",      "Qualified",      "Passed your first exam simulation"),
        ("review_master",  "Review Pro",    "Completed 50 reviews"),
    ]
    for badge_key, badge_name, description in achievements:
        cur.execute(
            """
            INSERT OR IGNORE INTO achievements (user_id, badge_key, badge_name, description, earned_at)
            VALUES (?, ?, ?, ?, datetime('now', '-2 days'))
            """,
            (user_id, badge_key, badge_name, description),
        )

    # ── Get all topic and question IDs ─────────────────────────────────────
    cur.execute("SELECT id, slug FROM topics")
    topics = {row["slug"]: row["id"] for row in cur.fetchall()}
    topic_list = list(topics.values())
    if not topics:
        print("ERROR: No topics found. Run `python backend/load_seed_data.py` first.")
        conn.close()
        return

    cur.execute("SELECT id, topic_id FROM questions")
    questions = cur.fetchall()
    q_map = {row["topic_id"]: row["id"] for row in questions}

    # ── Seed exam sessions with BIASED topic results ─────────────────────────
    # Strategy: some sessions concentrate on specific topics with poor scores
    # so those topics end up with low overall accuracy → high priority for focus mode.
    #
    # Session structure: (offset, questions_per_topic_dict, pass)
    # questions_per_topic_dict = {topic_id: (total, correct)} — only topics listed get tested
    exam_configs = [
        # Session 1: 7 days ago — decent overall (topics 1-5, 70% avg)
        (f"-{DAYS_AGO} days",
         {1: (5, 4), 2: (3, 2), 3: (4, 2), 4: (3, 2), 5: (5, 4)}, True),
        # Session 2: 6 days ago — poor on topics 6,7 (40-45% accuracy)
        (f"-{DAYS_AGO-1} days",
         {6: (5, 2), 7: (5, 3)}, False),
        # Session 3: 5 days ago — poor on topic 8 (30%)
        (f"-{DAYS_AGO-2} days",
         {8: (10, 3)}, False),
        # Session 4: 3 days ago — good (topics 9,10, 80-90%)
        (f"-{DAYS_AGO-3} days",
         {9: (5, 4), 10: (3, 3)}, True),
        # Session 5: 2 days ago — poor on topic 11 (40%)
        (f"-{DAYS_AGO-5} days",
         {11: (5, 2), 6: (3, 2)}, True),  # mixed — topic 6 re-tested, slightly better
    ]

    session_idx = 0
    for offset, topic_results, _pass in exam_configs:
        session_idx += 1
        eid = f"demo-exam-{session_idx:02d}"
        total = sum(t[0] for t in topic_results.values())
        correct = sum(t[1] for t in topic_results.values())
        score = round(correct / total * 100, 1)
        q_ids_json = json.dumps([f"q-{i}" for i in range(total)])
        t_ids_json = json.dumps(list(topic_results.keys()))
        cur.execute(
            """
            INSERT INTO exam_sessions
                (id, user_id, question_ids, topic_ids, total_questions, correct_count,
                 score_percent, status, started_at, completed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'completed',
                    datetime('now', ?, '-2 hours'),
                    datetime('now', ?, '-1 hour'),
                    datetime('now', ?))
            """,
            (eid, user_id, q_ids_json, t_ids_json, total, correct, score, offset, offset, offset),
        )
        q_global_idx = 0
        for tid, (qty, corr) in topic_results.items():
            for q_idx in range(qty):
                real_qid = q_map.get(tid, f"q-{tid}")
                is_corr = 1 if q_idx < corr else 0
                cur.execute(
                    """
                    INSERT INTO exam_answers (id, exam_session_id, question_id, selected_answer_index, is_correct, topic_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (f"demo-ea-{session_idx}-{q_global_idx}", eid, real_qid, 0, is_corr, tid),
                )
                q_global_idx += 1

    # ── SM-2 progress: vary by topic to create realistic spread ─────────────
    # Topics 8 and 11 should have low EF (weak), others moderate/high
    sm2_progress = [
        # (topic_slug, ef, interval, reps, due_offset, corr, total)
        ("voltage-drop",         2.1, 2, 2,  "+0 days",  7, 10),  # due today, OK
        ("fault-loop-zs",        1.8, 1, 1,  "-1 days",  3,  5),  # overdue, struggling
        ("insulation-resistance", 1.5, 1, 1,  "+0 days",  2,  4),  # due today, weak
        ("as-nzs-3000",          2.3, 3, 3,  "+1 days",  8, 10),  # due tomorrow, solid
        ("max-demand",           1.6, 1, 1,  "-2 days",  2,  4),  # overdue, weak
        ("rcd-mcb",              2.5, 5, 4,  "+2 days", 12, 14),  # strong
        ("supply-systems",       1.2, 0, 0,  "-3 days",  1,  3),  # very weak, overdue
        ("motor-starters",       2.0, 2, 2,  "+0 days",  6,  8),  # due today, OK
        ("switchboards",         1.4, 1, 1,  "-1 days",  2,  5),  # overdue, weak
        ("circuit-design",       1.8, 2, 2,  "+1 days",  5,  7),  # due tomorrow, OK
        ("testing-verification", 1.3, 0, 0,  "-2 days",  1,  4),  # very weak, overdue
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
                f"demo-up-{p_idx}", user_id, qid, ef, interval, reps,
                due_offset, total_reviews, correct_count, due_offset,
            ),
        )
        for r in range(min(total_reviews, 4)):
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
                    f"demo-rl-{p_idx}-{r}", user_id, qid, quality, quality,
                    ef - 0.1, ef, max(0, interval - 1), interval,
                    due_offset, f"-{r+1} hours",
                ),
            )

    conn.commit()

    # ── Verify with actual priority endpoint ─────────────────────────────────
    cur.execute("SELECT id FROM users WHERE email = ?", (DEMO_EMAIL,))
    if not cur.fetchone():
        print("ERROR: demo user not found after commit")
        conn.close()
        return

    r = requests.post(
        f"http://localhost:8000/api/auth/login",
        json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
        timeout=10,
    )
    if r.status_code != 200:
        print(f"Login failed: {r.text}")
        conn.close()
        return

    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    pri_resp = requests.get("http://localhost:8000/api/study/priority/demo-user-001", headers=headers, timeout=10)
    scores = pri_resp.json()["topics"] if pri_resp.ok else []

    print(f"\n✅ Demo user seeded: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    print(f"   User ID: {user_id}")
    print(f"   Streak: 5 days | Study days: 18 | 5 achievements unlocked")
    print(f"\n   Topic priority scores (actual from /priority endpoint):")
    for row in scores[:8]:
        tag = " ✅" if row["priority_score"] >= 70 else " ⬜"
        print(f"     {row['topic_name']:<32} {row['priority_score']:.1f}{tag}")

    weak = [r for r in scores if r["priority_score"] >= 70]
    if weak:
        print(f"\n   Focus mode: AVAILABLE ({len(weak)} weak topic(s) >= 70)")
    else:
        print(f"\n   Focus mode: NOTE — no topics >= 70 yet (check seed data)")

    conn.close()


if __name__ == "__main__":
    seed_demo_user()
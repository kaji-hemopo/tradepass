"""
TradePass — SQLite database setup (local mock for MVP).
Mirrors the PostgreSQL schema design from schema/database.sql.
"""
import logging
import sqlite3
from pathlib import Path

_logger = logging.getLogger("tradepass")

DB_PATH = Path(__file__).parent / "tradepass.db"

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # Topics
    cur.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            description TEXT,
            weight INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Questions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY,
            topic_id INTEGER NOT NULL REFERENCES topics(id),
            question_text TEXT NOT NULL,
            answer_text TEXT NOT NULL,
            explanation TEXT,
            reference_clause TEXT,
            difficulty TEXT NOT NULL DEFAULT 'medium',
            is_active INTEGER NOT NULL DEFAULT 1,
            correct_answer_index INTEGER,          -- 0-based index of correct option
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            options TEXT
        )
    """)

    # Users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT,
            password_hash TEXT,
            display_name TEXT,
            timezone TEXT NOT NULL DEFAULT 'Pacific/Auckland',
            is_premium INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # User Progress (SM-2 fields)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_progress (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            question_id TEXT NOT NULL REFERENCES questions(id),
            easiness_factor REAL NOT NULL DEFAULT 2.5,
            interval INTEGER NOT NULL DEFAULT 0,
            repetitions INTEGER NOT NULL DEFAULT 0,
            next_review_date TEXT NOT NULL DEFAULT (date('now')),
            last_reviewed_at TEXT,
            total_reviews INTEGER NOT NULL DEFAULT 0,
            correct_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (user_id, question_id)
        )
    """)

    # Due reviews index
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_progress_due
        ON user_progress (user_id, next_review_date)
    """)

    # Review Logs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS review_logs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            question_id TEXT NOT NULL REFERENCES questions(id),
            quality INTEGER NOT NULL,
            quality_numeric INTEGER NOT NULL,
            easiness_factor_before REAL NOT NULL,
            easiness_factor_after REAL NOT NULL,
            interval_before INTEGER NOT NULL,
            interval_after INTEGER NOT NULL,
            review_duration_ms INTEGER,
            reviewed_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Exam Sessions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS exam_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            question_ids TEXT NOT NULL,
            topic_ids TEXT,
            total_questions INTEGER NOT NULL,
            correct_count INTEGER NOT NULL DEFAULT 0,
            score_percent REAL,
            time_limit_minutes INTEGER NOT NULL DEFAULT 120,
            time_spent_seconds INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'in_progress',
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT,
            pass_mark REAL NOT NULL DEFAULT 60.0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Exam Answers
    cur.execute("""
        CREATE TABLE IF NOT EXISTS exam_answers (
            id TEXT PRIMARY KEY,
            exam_session_id TEXT NOT NULL REFERENCES exam_sessions(id),
            question_id TEXT NOT NULL REFERENCES questions(id),
            selected_answer_index INTEGER,
            is_correct INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            answered_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Index for fast exam answer lookup
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_exam_answers_session
        ON exam_answers (exam_session_id)
    """)

    # Study Sessions
    cur.execute("""
        CREATE TABLE IF NOT EXISTS study_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'review',
            status TEXT NOT NULL DEFAULT 'in_progress',
            question_ids TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Study Streaks
    cur.execute("""
        CREATE TABLE IF NOT EXISTS study_streaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            current_streak INTEGER NOT NULL DEFAULT 0,
            longest_streak INTEGER NOT NULL DEFAULT 0,
            last_study_date TEXT,
            total_study_days INTEGER NOT NULL DEFAULT 0,
            questions_per_day INTEGER NOT NULL DEFAULT 10,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Achievements
    cur.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            badge_key TEXT NOT NULL,
            badge_name TEXT NOT NULL,
            description TEXT,
            earned_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (user_id, badge_key)
        )
    """)

    # Bookmarks
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (user_id, question_id)
        )
    """)

    # Question Flags (exam prep markers)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS question_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            flagged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, question_id)
        )
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    _logger.info("Database initialised at tradepass.db")

"""
TradePass — FastAPI Backend (MVP)
Local SQLite mock — drop-in replace with PostgreSQL/Supabase for production.
"""
import os
import uuid
import json
import time
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Query, Body, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ―― Structured Logger ――――――――――――――――――――――――――――
_logger = logging.getLogger("tradepass")
PYTHON_ENV = os.environ.get("PYTHON_ENV", "production")
DEBUG = PYTHON_ENV != "production"

if DEBUG:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
else:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

from auth import hash_password, verify_password, create_access_token, decode_token

class DailyGoalRequest(BaseModel):
    goal: int = Field(..., ge=1, le=100, description="Daily question target (1–100)")

class FlagRequest(BaseModel):
    user_id: str

from database import get_connection, init_db
from sr import sm2_step, SM2Fields, grade_from_answer


app = FastAPI(title="TradePass API", version="1.0.0")

# —— CORS — configurable via CORS_ORIGINS env var (comma-separated) ——
_cors_origins = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:8501,http://127.0.0.1:8501"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# —― Rate Limiting — 100 req/min per IP for auth endpoints ――
from starlette.middleware.base import BaseHTTPMiddleware

_rate_limit_store: dict[str, list[float]] = {}
_RATE_LIMIT = 100  # requests
_RATE_WINDOW = 60.0  # seconds

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Only rate-limit auth endpoints
        if not request.url.path.startswith("/api/auth"):
            return await call_next(request)
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = _rate_limit_store.get(client_ip, [])
        # Prune old entries
        window = [t for t in window if now - t < _RATE_WINDOW]
        if len(window) >= _RATE_LIMIT:
            _logger.warning(f"Rate limit hit for IP: {client_ip}")
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Limit: 100/min."},
            )
        window.append(now)
        _rate_limit_store[client_ip] = window
        return await call_next(request)

app.add_middleware(RateLimitMiddleware)


# ─────────────────────────────────────────────────────────────────────────────
# —― Exception Handlers ― debug vs production ――
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if DEBUG:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "status_code": exc.status_code},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    _logger.exception("Unhandled exception: %s", exc)
    if DEBUG:
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "type": type(exc).__name__},
        )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

# Pydantic Models
# ─────────────────────────────────────────────────────────────────────────────

class AnswerSubmission(BaseModel):
    user_id: str
    question_id: str
    user_answer_index: int


class ReviewResult(BaseModel):
    user_id: str
    question_id: str
    quality: int  # 0-5 SM-2 quality grade


class ReviewSessionRequest(BaseModel):
    user_id: str
    limit: int = Field(default=20, ge=1, le=100)


# ─────────────────────────────────────────────────────────────────────────────
# Exam Simulation Models
# ─────────────────────────────────────────────────────────────────────────────

class ExamStartRequest(BaseModel):
    user_id: str
    topic_ids: Optional[list[int]] = None   # null = all topics
    question_count: int = Field(default=50, ge=1, le=200)
    time_limit_minutes: int = Field(default=120, ge=10, le=240)
    pass_mark: float = Field(default=60.0, ge=50, le=100)


class ExamAnswerRequest(BaseModel):
    question_id: str
    selected_answer_index: int


# ─────────────────────────────────────────────────────────────────────────────
# Auth Models
# ─────────────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


# ─────────────────────────────────────────────────────────────────────────────
# JWT Dependency
# ─────────────────────────────────────────────────────────────────────────────

def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """
    Validate Bearer token and return the decoded payload.
    Raises 401 if missing, malformed, or expired.
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization[7:]
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(401, "Invalid or expired token")
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Startup
# ─────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    _logger.info("TradePass API starting up — PYTHON_ENV=%s", PYTHON_ENV)
    init_db()
    _logger.info("TradePass API ready on port 8000")

@app.on_event("shutdown")
def shutdown():
    _logger.info("TradePass API shutting down")

# —― Health Check ――
@app.get("/health")
def health_check():
    """Public health endpoint for load balancers / uptime monitors."""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "env": PYTHON_ENV,
    }



# ─────────────────────────────────────────────────────────────────────────────
# Topics
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/topics")
def list_topics():
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, name, slug, description, weight FROM topics ORDER BY weight DESC, name"
    )
    rows = cur.fetchall()
    conn.close()
    return {"topics": [dict(r) for r in rows]}


# ─────────────────────────────────────────────────────────────────────────────
# Questions
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/questions")
def list_questions(
    topic_id: Optional[int] = Query(None),
    difficulty: Optional[str] = Query(None),
    limit: int = Query(20),
):
    conn = get_connection()
    sql = "SELECT * FROM questions WHERE is_active = 1"
    params = []
    if topic_id:
        sql += " AND topic_id = ?"
        params.append(topic_id)
    if difficulty:
        sql += " AND difficulty = ?"
        params.append(difficulty)
    sql += f" ORDER BY RANDOM() LIMIT {limit}"
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return {"questions": [_q_row(d) for d in rows]}


@app.get("/api/questions/{question_id}")
def get_question(question_id: str):
    conn = get_connection()
    cur = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Question not found")
    return _q_row(row)


def _q_row(row) -> dict:
    d = dict(row)
    d["is_active"] = bool(d["is_active"])
    # Parse options JSON string to list for frontend compatibility
    if "options" in d and isinstance(d["options"], str):
        try:
            d["options"] = json.loads(d["options"])
        except Exception:
            d["options"] = []
    # Strip internal fields from response
    d.pop("updated_at", None)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Due Reviews (SM-2)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/reviews/due")
def get_due_reviews(
    user_id: str = Query(...),
    limit: int = Query(10),
):
    """
    Return questions due for review for a given user.
    A question is 'due' if next_review_date <= today.
    """
    conn = get_connection()
    cur = conn.execute(
        """
        SELECT q.*, up.easiness_factor, up.interval, up.repetitions,
               up.next_review_date, up.last_reviewed_at, up.total_reviews,
               up.correct_count
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id
        WHERE up.user_id = ?
          AND up.next_review_date <= ?
          AND q.is_active = 1
        ORDER BY up.next_review_date ASC
        LIMIT ?
        """,
        (user_id, str(date.today()), limit),
    )
    rows = cur.fetchall()
    conn.close()
    return {"due": [_q_row(r) for r in rows], "count": len(rows)}


@app.get("/api/reviews/new")
def get_new_questions(
    user_id: str = Query(...),
    limit: int = Query(5),
):
    """Return questions not yet seen by this user (no user_progress row)."""
    conn = get_connection()
    cur = conn.execute(
        """
        SELECT q.*
        FROM questions q
        WHERE q.is_active = 1
          AND q.id NOT IN (
              SELECT question_id FROM user_progress WHERE user_id = ?
          )
        ORDER BY RANDOM()
        LIMIT ?
        """,
        (user_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return {"new": [_q_row(r) for r in rows], "count": len(rows)}


# ─────────────────────────────────────────────────────────────────────────────
# Submit Review Answer
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/reviews/submit")
def submit_review(review: ReviewResult):
    """
    Process a review: apply SM-2, update user_progress, log review.
    quality: 0-5 SM-2 grade (0=blackout, 5=perfect).
    """
    conn = get_connection()
    cur = conn.cursor()

    # Fetch current SR state
    cur.execute(
        "SELECT * FROM user_progress WHERE user_id = ? AND question_id = ?",
        (review.user_id, review.question_id),
    )
    row = cur.fetchone()

    if row:
        # Existing card — apply SM-2
        fields = SM2Fields(
            easiness_factor=row["easiness_factor"],
            interval=row["interval"],
            repetitions=row["repetitions"],
        )
        ef_before = fields.easiness_factor
        int_before = fields.interval
        new_fields = sm2_step(fields, review.quality)
    else:
        # New card — init SM-2 fields
        ef_before = 2.5
        int_before = 0
        fields = SM2Fields(easiness_factor=2.5, interval=0, repetitions=0)
        new_fields = sm2_step(fields, review.quality)

    now = datetime.utcnow().isoformat()
    next_review = str(date.today())

    log_id = str(uuid.uuid4())
    progress_id = str(uuid.uuid4()) if not row else row["id"]

    if row:
        cur.execute(
            """
            UPDATE user_progress SET
                easiness_factor = ?,
                interval = ?,
                repetitions = ?,
                next_review_date = ?,
                last_reviewed_at = ?,
                total_reviews = total_reviews + 1,
                correct_count = correct_count + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_fields.easiness_factor,
                new_fields.interval,
                new_fields.repetitions,
                next_review,
                now,
                1 if review.quality >= 3 else 0,
                now,
                row["id"],
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO user_progress
                (id, user_id, question_id, easiness_factor, interval, repetitions,
                 next_review_date, last_reviewed_at, total_reviews, correct_count,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                progress_id,
                review.user_id,
                review.question_id,
                new_fields.easiness_factor,
                new_fields.interval,
                new_fields.repetitions,
                next_review,
                now,
                1,
                1 if review.quality >= 3 else 0,
                now,
                now,
            ),
        )

    # Review log
    cur.execute(
        """
        INSERT INTO review_logs
            (id, user_id, question_id, quality, quality_numeric,
             easiness_factor_before, easiness_factor_after,
             interval_before, interval_after, reviewed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            log_id,
            review.user_id,
            review.question_id,
            review.quality,
            review.quality,
            ef_before,
            new_fields.easiness_factor,
            int_before,
            new_fields.interval,
            now,
        ),
    )

    conn.commit()
    conn.close()

    return {
        "status": "ok",
        "next_review_date": next_review,
        "interval": new_fields.interval,
        "easiness_factor": new_fields.easiness_factor,
        "repetitions": new_fields.repetitions,
    }


# ─────────────────────────────────────────────────────────────────────────────
# User Progress Summary
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/users/{user_id}/stats")
def user_stats(user_id: str):
    conn = get_connection()
    cur = conn.execute(
        """
        SELECT
            COUNT(up.id) AS total_cards,
            SUM(up.total_reviews) AS total_reviews,
            SUM(up.correct_count) AS correct_count,
            SUM(CASE WHEN up.next_review_date <= ? THEN 1 ELSE 0 END) AS due_count
        FROM user_progress up
        WHERE up.user_id = ?
        """,
        (str(date.today()), user_id),
    )
    row = cur.fetchone()
    conn.close()
    d = dict(row)
    accuracy = (
        round(d["correct_count"] / d["total_reviews"] * 100, 1)
        if d["total_reviews"] and d["total_reviews"] > 0
        else None
    )
    return {
        "user_id": user_id,
        "total_cards": d["total_cards"],
        "total_reviews": d["total_reviews"],
        "accuracy_pct": accuracy,
        "due_now": d["due_count"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Exam Simulation Mode
# ─────────────────────────────────────────────────────────────────────────────

def _check_expired(session_row) -> bool:
    """Return True if exam has passed its time limit."""
    started = datetime.fromisoformat(session_row["started_at"])
    elapsed = (datetime.utcnow() - started).total_seconds()
    limit_seconds = session_row["time_limit_minutes"] * 60
    return elapsed >= limit_seconds


def _auto_expire(conn, session_row) -> bool:
    """If session is expired, auto-submit it. Returns True if auto-expired."""
    if _check_expired(session_row):
        # Mark any unanswered as wrong (blank = wrong)
        q_ids = __import__("json").loads(session_row["question_ids"])
        cur2 = conn.execute(
            "SELECT question_id FROM exam_answers WHERE exam_session_id = ?",
            (session_row["id"],)
        )
        answered = {r["question_id"] for r in cur2.fetchall()}
        now = datetime.utcnow().isoformat()
        limit_seconds = session_row["time_limit_minutes"] * 60
        for qid in q_ids:
            if qid not in answered:
                cur3 = conn.execute(
                    "SELECT topic_id FROM questions WHERE id = ?", (qid,)
                )
                q_row = cur3.fetchone()
                if q_row:
                    conn.execute(
                        """
                        INSERT INTO exam_answers
                            (id, exam_session_id, question_id, selected_answer_index, is_correct, topic_id, answered_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (str(uuid.uuid4()), session_row["id"], qid, None, 0, q_row["topic_id"], now)
                    )
        # Grade all answers
        cur_grade = conn.execute(
            """
            SELECT ea.id AS answer_id, ea.selected_answer_index, q.correct_answer_index
            FROM exam_answers ea
            JOIN questions q ON q.id = ea.question_id
            WHERE ea.exam_session_id = ?
            """,
            (session_row["id"],)
        )
        for ans in cur_grade.fetchall():
            is_correct = 1 if (
                ans["selected_answer_index"] is not None
                and ans["correct_answer_index"] is not None
                and ans["selected_answer_index"] == ans["correct_answer_index"]
            ) else 0
            conn.execute(
                "UPDATE exam_answers SET is_correct = ? WHERE id = ?",
                (is_correct, ans["answer_id"])
            )
        # Score it
        cur4 = conn.execute(
            "SELECT COUNT(*) as cnt FROM exam_answers WHERE exam_session_id = ? AND is_correct = 1",
            (session_row["id"],)
        )
        correct = cur4.fetchone()["cnt"]
        total = len(q_ids)
        score = round(correct / total * 100, 1) if total > 0 else 0
        conn.execute(
            """
            UPDATE exam_sessions SET
                correct_count = ?,
                score_percent = ?,
                time_spent_seconds = ?,
                status = 'completed',
                completed_at = ?
            WHERE id = ?
            """,
            (correct, score, int(limit_seconds), now, session_row["id"])
        )
        conn.commit()
        return True
    return False


@app.post("/api/exams/start")
def exam_start(req: ExamStartRequest):
    """Start a new exam session. Returns questions (no answers exposed)."""
    conn = get_connection()

    # Build question pool
    if req.topic_ids:
        placeholders = ",".join("?" * len(req.topic_ids))
        cur = conn.execute(
            f"SELECT id, topic_id, question_text, difficulty FROM questions "
            f"WHERE topic_id IN ({placeholders}) AND is_active = 1 ORDER BY RANDOM()",
            req.topic_ids
        )
    else:
        cur = conn.execute(
            "SELECT id, topic_id, question_text, difficulty FROM questions WHERE is_active = 1 ORDER BY RANDOM()"
        )

    all_rows = cur.fetchall()
    if len(all_rows) == 0:
        conn.close()
        raise HTTPException(400, "No questions available for the selected topics")

    # Cap at available or requested
    q_count = min(req.question_count, len(all_rows))
    selected = all_rows[:q_count]
    q_ids = [r["id"] for r in selected]

    # Build question list for client (no answer_text, no explanation)
    questions_for_client = [
        {
            "id": r["id"],
            "topic_id": r["topic_id"],
            "question_text": r["question_text"],
            "difficulty": r["difficulty"],
        }
        for r in selected
    ]

    import json
    session_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    topic_ids_json = json.dumps(req.topic_ids) if req.topic_ids else None

    conn.execute(
        """
        INSERT INTO exam_sessions
            (id, user_id, question_ids, topic_ids, total_questions,
             time_limit_minutes, pass_mark, status, started_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'in_progress', ?)
        """,
        (
            session_id,
            req.user_id,
            json.dumps(q_ids),
            topic_ids_json,
            q_count,
            req.time_limit_minutes,
            req.pass_mark,
            now,
        ),
    )
    conn.commit()
    conn.close()

    return {
        "exam_id": session_id,
        "questions": questions_for_client,
        "total_questions": q_count,
        "time_limit_minutes": req.time_limit_minutes,
        "pass_mark": req.pass_mark,
        "started_at": now,
    }


@app.get("/api/exams/{exam_id}")
def exam_get(exam_id: str):
    """
    Get exam session status. Auto-expires if time limit has passed.
    Returns status, time_remaining_seconds, and question_ids for client reference.
    """
    conn = get_connection()
    cur = conn.execute("SELECT * FROM exam_sessions WHERE id = ?", (exam_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, "Exam session not found")

    d = dict(row)

    # Auto-expire if needed
    if d["status"] == "in_progress" and _check_expired(row):
        conn2 = get_connection()
        _auto_expire(conn2, row)
        conn2.close()
        # Re-fetch
        conn3 = get_connection()
        cur3 = conn3.execute("SELECT * FROM exam_sessions WHERE id = ?", (exam_id,))
        row = cur3.fetchone()
        d = dict(row)
        conn3.close()

    started = datetime.fromisoformat(d["started_at"])
    elapsed = (datetime.utcnow() - started).total_seconds()
    limit_seconds = d["time_limit_minutes"] * 60
    time_remaining = max(0, int(limit_seconds - elapsed))

    import json
    return {
        "exam_id": d["id"],
        "status": d["status"],
        "total_questions": d["total_questions"],
        "time_limit_minutes": d["time_limit_minutes"],
        "time_spent_seconds": d["time_spent_seconds"],
        "time_remaining_seconds": time_remaining,
        "pass_mark": d["pass_mark"],
        "started_at": d["started_at"],
        "completed_at": d["completed_at"],
        "score_percent": d["score_percent"],
        "correct_count": d["correct_count"],
        "question_ids": json.loads(d["question_ids"]),
    }


@app.post("/api/exams/{exam_id}/answer")
def exam_answer(exam_id: str, req: ExamAnswerRequest):
    """Submit an answer to a question within an active exam session."""
    conn = get_connection()
    cur = conn.execute("SELECT * FROM exam_sessions WHERE id = ?", (exam_id,))
    session = cur.fetchone()

    if not session:
        conn.close()
        raise HTTPException(404, "Exam session not found")

    if session["status"] != "in_progress":
        conn.close()
        raise HTTPException(400, "Exam session is not in progress")

    # Auto-expire check
    if _check_expired(session):
        _auto_expire(conn, session)
        conn.close()
        raise HTTPException(400, "Exam session has expired")

    import json
    q_ids = json.loads(session["question_ids"])
    if req.question_id not in q_ids:
        conn.close()
        raise HTTPException(400, "Question does not belong to this exam session")

    # Check if already answered
    cur2 = conn.execute(
        "SELECT id FROM exam_answers WHERE exam_session_id = ? AND question_id = ?",
        (exam_id, req.question_id)
    )
    if cur2.fetchone():
        conn.close()
        raise HTTPException(400, "Question already answered in this session")

    # Get correct answer index and topic for grading
    cur3 = conn.execute(
        "SELECT topic_id, correct_answer_index FROM questions WHERE id = ?", (req.question_id,)
    )
    q_row = cur3.fetchone()
    if not q_row:
        conn.close()
        raise HTTPException(404, "Question not found")

    # Grade immediately: compare selected answer against the stored correct index
    is_correct = 1 if (
        q_row["correct_answer_index"] is not None
        and req.selected_answer_index == q_row["correct_answer_index"]
    ) else 0

    now = datetime.utcnow().isoformat()
    conn.execute(
        """
        INSERT INTO exam_answers
            (id, exam_session_id, question_id, selected_answer_index, is_correct, topic_id, answered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), exam_id, req.question_id, req.selected_answer_index, is_correct, q_row["topic_id"], now)
    )
    conn.commit()
    conn.close()

    return {"status": "ok", "question_id": req.question_id, "is_correct": bool(is_correct)}


@app.post("/api/exams/{exam_id}/submit")
def exam_submit(exam_id: str):
    """
    Submit and finalise the exam. Grades all unanswered questions as wrong,
    calculates score, stores results.
    """
    conn = get_connection()
    cur = conn.execute("SELECT * FROM exam_sessions WHERE id = ?", (exam_id,))
    session = cur.fetchone()

    if not session:
        conn.close()
        raise HTTPException(404, "Exam session not found")

    if session["status"] == "completed":
        conn.close()
        raise HTTPException(400, "Exam already completed")

    import json
    q_ids = json.loads(session["question_ids"])

    # Mark any unanswered as wrong
    now = datetime.utcnow().isoformat()
    cur2 = conn.execute(
        "SELECT question_id FROM exam_answers WHERE exam_session_id = ?", (exam_id,)
    )
    answered = {r["question_id"] for r in cur2.fetchall()}

    for qid in q_ids:
        if qid not in answered:
            cur3 = conn.execute("SELECT topic_id FROM questions WHERE id = ?", (qid,))
            q_row = cur3.fetchone()
            if q_row:
                conn.execute(
                    """
                    INSERT INTO exam_answers
                        (id, exam_session_id, question_id, selected_answer_index, is_correct, topic_id, answered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), exam_id, qid, None, 0, q_row["topic_id"], now)
                )

    # Grade all answers against the question bank's correct_answer_index
    cur_grade = conn.execute(
        """
        SELECT ea.id AS answer_id, ea.selected_answer_index, q.correct_answer_index
        FROM exam_answers ea
        JOIN questions q ON q.id = ea.question_id
        WHERE ea.exam_session_id = ?
        """,
        (exam_id,)
    )
    for ans in cur_grade.fetchall():
        is_correct = 1 if (
            ans["selected_answer_index"] is not None
            and ans["correct_answer_index"] is not None
            and ans["selected_answer_index"] == ans["correct_answer_index"]
        ) else 0
        conn.execute(
            "UPDATE exam_answers SET is_correct = ? WHERE id = ?",
            (is_correct, ans["answer_id"])
        )

    # Calculate score
    cur4 = conn.execute(
        "SELECT COUNT(*) as cnt FROM exam_answers WHERE exam_session_id = ? AND is_correct = 1",
        (exam_id,)
    )
    correct = cur4.fetchone()["cnt"]
    total = len(q_ids)
    score = round(correct / total * 100, 1) if total > 0 else 0

    # Time spent
    started = datetime.fromisoformat(session["started_at"])
    time_spent = int((datetime.utcnow() - started).total_seconds())

    conn.execute(
        """
        UPDATE exam_sessions SET
            correct_count = ?,
            score_percent = ?,
            time_spent_seconds = ?,
            status = 'completed',
            completed_at = ?
        WHERE id = ?
        """,
        (correct, score, time_spent, now, exam_id)
    )
    conn.commit()
    conn.close()

    return {"exam_id": exam_id, "status": "completed", "score_percent": score, "correct_count": correct, "total": total}


@app.get("/api/exams/{exam_id}/results")
def exam_results(exam_id: str):
    """
    Return detailed exam results: overall score, pass/fail, per-topic breakdown.
    Auto-expires and grades the exam if time limit has passed.
    """
    conn = get_connection()
    cur = conn.execute("SELECT * FROM exam_sessions WHERE id = ?", (exam_id,))
    session = cur.fetchone()

    if not session:
        conn.close()
        raise HTTPException(404, "Exam session not found")

    # Auto-expire if still in_progress and time is up
    if session["status"] == "in_progress":
        if _check_expired(session):
            _auto_expire(conn, session)
            cur = conn.execute("SELECT * FROM exam_sessions WHERE id = ?", (exam_id,))
            session = cur.fetchone()

    s = dict(session)
    total = s["total_questions"]
    score = s["score_percent"] or 0
    correct = s["correct_count"] or 0
    passed = score >= s["pass_mark"]

    # Per-topic breakdown
    import json
    cur2 = conn.execute(
        """
        SELECT
            ea.topic_id,
            t.name AS topic_name,
            t.slug AS topic_slug,
            COUNT(ea.id) AS attempts,
            SUM(ea.is_correct) AS correct,
            ROUND(100.0 * SUM(ea.is_correct) / COUNT(ea.id), 1) AS pct
        FROM exam_answers ea
        JOIN topics t ON t.id = ea.topic_id
        WHERE ea.exam_session_id = ?
        GROUP BY ea.topic_id, t.name, t.slug
        ORDER BY t.weight DESC, t.name
        """,
        (exam_id,)
    )
    topic_rows = cur2.fetchall()

    # Per-question detail (without revealing correct answer for unanswered)
    cur3 = conn.execute(
        """
        SELECT ea.question_id, ea.selected_answer_index, ea.is_correct, ea.topic_id,
               q.question_text, q.explanation, q.reference_clause
        FROM exam_answers ea
        JOIN questions q ON q.id = ea.question_id
        WHERE ea.exam_session_id = ?
        ORDER BY ea.answered_at
        """,
        (exam_id,)
    )
    question_rows = cur3.fetchall()

    conn.close()

    questions_result = []
    for qr in question_rows:
        questions_result.append({
            "question_id": qr["question_id"],
            "topic_id": qr["topic_id"],
            "selected_answer_index": qr["selected_answer_index"],
            "is_correct": bool(qr["is_correct"]),
            "question_text": qr["question_text"],
            "explanation": qr["explanation"],
            "reference_clause": qr["reference_clause"],
        })

    return {
        "exam_id": exam_id,
        "status": s["status"],
        "total_questions": total,
        "correct_count": correct,
        "score_percent": score,
        "pass_mark": s["pass_mark"],
        "passed": passed,
        "time_spent_seconds": s["time_spent_seconds"],
        "started_at": s["started_at"],
        "completed_at": s["completed_at"],
        "topic_breakdown": [dict(r) for r in topic_rows],
        "questions": questions_result,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Study Mode — Browse & Review All Questions
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/study/questions")
def study_all_questions(
    topic_id: Optional[int] = Query(None),
    difficulty: Optional[str] = Query(None),
    limit: int = Query(200),
    _token: dict = Depends(get_current_user),
):
    """
    Return all active questions WITH correct_answer_index, explanation,
    and reference_clause exposed — for self-directed study (no exam pressure).
    """
    conn = get_connection()
    sql = """
        SELECT id, topic_id, question_text, answer_text,
               correct_answer_index, explanation, reference_clause, difficulty
        FROM questions
        WHERE is_active = 1
    """
    params = []
    if topic_id:
        sql += " AND topic_id = ?"
        params.append(topic_id)
    if difficulty:
        sql += " AND difficulty = ?"
        params.append(difficulty)
    sql += f" ORDER BY topic_id, difficulty LIMIT {limit}"
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return {
        "questions": [dict(r) for r in rows],
        "count": len(rows),
    }


@app.get("/api/study/topic/{topic_id}")
def study_topic(topic_id: int, _token: dict = Depends(get_current_user)):
    """
    Return all questions for a specific topic with full answer data
    (correct_answer_index, explanation, reference_clause) for study review.
    """
    conn = get_connection()
    cur = conn.execute(
        "SELECT * FROM topics WHERE id = ?", (topic_id,)
    )
    topic = cur.fetchone()
    if not topic:
        conn.close()
        raise HTTPException(404, "Topic not found")

    cur2 = conn.execute(
        """
        SELECT id, topic_id, question_text, answer_text,
               correct_answer_index, explanation, reference_clause, difficulty
        FROM questions
        WHERE topic_id = ? AND is_active = 1
        ORDER BY difficulty, id
        """,
        (topic_id,)
    )
    rows = cur2.fetchall()
    conn.close()

    return {
        "topic": dict(topic),
        "questions": [dict(r) for r in rows],
        "count": len(rows),
    }


@app.get("/api/study/progress/{user_id}")
def study_progress(user_id: str, _token: dict = Depends(get_current_user)):
    """
    Return study progress for a user across all modes:
    - Total questions answered (exam + review combined)
    - Per-topic attempt counts
    - Per-topic accuracy %
    - SM-2 estimated strength per topic (avg easiness_factor across topic's cards)
    """
    conn = get_connection()

    # -- Raw totals --
    # exam answers
    cur = conn.execute(
        """
        SELECT COUNT(DISTINCT question_id) AS exam_answered
        FROM exam_answers ea
        JOIN exam_sessions es ON es.id = ea.exam_session_id
        WHERE es.user_id = ?
        """,
        (user_id,)
    )
    exam_answered = cur.fetchone()["exam_answered"]


    # review answers (user_progress)
    cur2 = conn.execute(
        "SELECT COUNT(*) AS review_answered FROM user_progress WHERE user_id = ?",
        (user_id,)
    )
    review_answered = cur2.fetchone()["review_answered"]


    # -- Per-topic breakdown from exam answers --
    cur3 = conn.execute(
        """
        SELECT
            ea.topic_id,
            t.name  AS topic_name,
            t.slug  AS topic_slug,
            COUNT(ea.id)                        AS exam_attempts,
            SUM(ea.is_correct)                  AS exam_correct,
            ROUND(100.0 * SUM(ea.is_correct) / COUNT(ea.id), 1) AS exam_accuracy_pct
        FROM exam_answers ea
        JOIN exam_sessions es ON es.id = ea.exam_session_id
        JOIN topics t ON t.id = ea.topic_id
        WHERE es.user_id = ?
        GROUP BY ea.topic_id, t.name, t.slug
        """,
        (user_id,)
    )
    exam_by_topic = {r["topic_id"]: dict(r) for r in cur3.fetchall()}

    # -- Per-topic breakdown from review answers --
    cur4 = conn.execute(
        """
        SELECT
            q.topic_id,
            t.name  AS topic_name,
            t.slug  AS topic_slug,
            COUNT(up.id)                       AS review_attempts,
            SUM(up.correct_count)              AS review_correct,
            ROUND(100.0 * SUM(up.correct_count) / SUM(up.total_reviews), 1) AS review_accuracy_pct
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id
        JOIN topics t ON t.id = q.topic_id
        WHERE up.user_id = ?
        GROUP BY q.topic_id, t.name, t.slug
        """,
        (user_id,)
    )
    review_by_topic = {r["topic_id"]: dict(r) for r in cur4.fetchall()}


    # -- SM-2 strength per topic (avg easiness_factor for each topic's cards) --
    cur5 = conn.execute(
        """
        SELECT
            q.topic_id,
            ROUND(AVG(up.easiness_factor), 2) AS sm2_strength
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id
        WHERE up.user_id = ?
        GROUP BY q.topic_id
        """,
        (user_id,)
    )
    sm2_by_topic = {r["topic_id"]: r["sm2_strength"] for r in cur5.fetchall()}

    conn.close()

    # -- Merge topic data --
    all_topic_ids = set(exam_by_topic) | set(review_by_topic) | set(sm2_by_topic)
    topics_result = []
    for tid in sorted(all_topic_ids):
        entry = {
            "topic_id": tid,
            "topic_name": exam_by_topic.get(tid, {}).get("topic_name")
                        or review_by_topic.get(tid, {}).get("topic_name")
                        or "Unknown",
            "topic_slug": exam_by_topic.get(tid, {}).get("topic_slug")
                         or review_by_topic.get(tid, {}).get("topic_slug")
                         or "unknown",
            "exam_attempts": exam_by_topic.get(tid, {}).get("exam_attempts", 0),
            "exam_correct":  exam_by_topic.get(tid, {}).get("exam_correct", 0),
            "exam_accuracy_pct": exam_by_topic.get(tid, {}).get("exam_accuracy_pct"),
            "review_attempts": review_by_topic.get(tid, {}).get("review_attempts", 0),
            "review_correct":  review_by_topic.get(tid, {}).get("review_correct", 0),
            "review_accuracy_pct": review_by_topic.get(tid, {}).get("review_accuracy_pct"),
            "sm2_strength": sm2_by_topic.get(tid),   # null if no SR data yet
        }
        topics_result.append(entry)

    return {
        "user_id": user_id,
        "questions_answered_exam":  exam_answered,
        "questions_answered_review": review_answered,
        "topics": topics_result,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Study Priority — Smart Recommendation Engine
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/study/priority/{user_id}")
def study_priority(user_id: str, _token: dict = Depends(get_current_user)):
    """
    Return all topics for a user sorted by study urgency (highest priority first).
    Priority score: weighted combo of low exam accuracy (40%%), low review accuracy
    (20%%), low SM-2 strength (25%%), and recency of last study (15%%).
    Lower accuracy / weaker SM-2 / longer since studied = higher urgency.

    recommended_action:
      "exam"    — topic has never been attempted in any mode
      "review"  — SM-2 cards are due for this topic
      "mastered" — accuracy > 80%% AND sm2_strength > 2.3
      "study"   — default fallback (has data, needs work)
    """
    conn = get_connection()

    # All active topics (unseen topics also appear as priority = exam)
    cur = conn.execute("SELECT id, name, slug FROM topics")
    all_topics = {r["id"]: {"name": r["name"], "slug": r["slug"]} for r in cur.fetchall()}

    # Per-topic exam stats
    cur = conn.execute(
        """
        SELECT
            ea.topic_id,
            COUNT(ea.id) AS exam_attempts,
            SUM(ea.is_correct) AS exam_correct,
            ROUND(100.0 * SUM(ea.is_correct) / COUNT(ea.id), 1) AS exam_accuracy_pct,
            MAX(ea.answered_at) AS last_exam_at
        FROM exam_answers ea
        JOIN exam_sessions es ON es.id = ea.exam_session_id
        WHERE es.user_id = ?
        GROUP BY ea.topic_id
        """,
        (user_id,)
    )
    exam_by_topic = {r["topic_id"]: dict(r) for r in cur.fetchall()}

    # Per-topic review stats (SM-2)
    cur = conn.execute(
        """
        SELECT
            q.topic_id,
            COUNT(up.id) AS review_attempts,
            SUM(up.correct_count) AS review_correct,
            ROUND(100.0 * SUM(up.correct_count) / SUM(up.total_reviews), 1) AS review_accuracy_pct,
            ROUND(AVG(up.easiness_factor), 2) AS sm2_strength,
            MAX(up.last_reviewed_at) AS last_review_at,
            SUM(CASE WHEN up.next_review_date <= date('now') THEN 1 ELSE 0 END) AS due_count
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id
        WHERE up.user_id = ?
        GROUP BY q.topic_id
        """,
        (user_id,)
    )
    review_by_topic = {r["topic_id"]: dict(r) for r in cur.fetchall()}

    conn.close()

    # Build priority list for all topics
    results = []
    now_ts = datetime.utcnow().timestamp()

    for topic_id, topic_info in all_topics.items():
        exam   = exam_by_topic.get(topic_id, {})
        review = review_by_topic.get(topic_id, {})

        exam_attempts      = exam.get("exam_attempts", 0)
        exam_accuracy_pct  = exam.get("exam_accuracy_pct")
        last_exam_at       = exam.get("last_exam_at")

        review_attempts      = review.get("review_attempts", 0)
        review_accuracy_pct  = review.get("review_accuracy_pct")
        sm2_strength         = review.get("sm2_strength")
        last_review_at       = review.get("last_review_at")
        due_count            = review.get("due_count", 0)

        # Combined accuracy: prefer exam if available, else review
        if exam_attempts > 0 and exam_accuracy_pct is not None:
            combined_accuracy = exam_accuracy_pct
        elif review_attempts > 0 and review_accuracy_pct is not None:
            combined_accuracy = review_accuracy_pct
        else:
            combined_accuracy = None

        # Recency: most recent study event (exam or review)
        last_studied_ts = None
        if last_exam_at:
            try:
                last_studied_ts = datetime.fromisoformat(last_exam_at).timestamp()
            except Exception:
                pass
        if last_review_at:
            try:
                ts = datetime.fromisoformat(last_review_at).timestamp()
                if last_studied_ts is None or ts > last_studied_ts:
                    last_studied_ts = ts
            except Exception:
                pass

        days_since_studied = None
        if last_studied_ts is not None:
            days_since_studied = round((now_ts - last_studied_ts) / 86400, 1)

        # Priority score: lower actual values = higher urgency
        # Weights: exam accuracy (40%%), review accuracy (20%%), SM-2 (25%%), recency (15%%)
        score = 0.0
        weight_total = 0.0

        if exam_accuracy_pct is not None:
            score += (100 - exam_accuracy_pct) * 0.40
            weight_total += 0.40

        if review_accuracy_pct is not None:
            score += (100 - review_accuracy_pct) * 0.20
            weight_total += 0.20

        if sm2_strength is not None:
            # SM-2 EF range ~1.3 to 2.5; lower EF = higher priority
            ef_component = max(0, (2.5 - sm2_strength) / 1.2 * 100)
            score += ef_component * 0.25
            weight_total += 0.25

        if days_since_studied is not None:
            recency_component = min(days_since_studied / 90.0, 1.0) * 100
            score += recency_component * 0.15
            weight_total += 0.15

        if weight_total == 0:
            priority_score = 50.0   # neutral for topics never seen
        else:
            priority_score = round(score / weight_total, 1)

        # recommended_action
        if exam_attempts == 0 and review_attempts == 0:
            recommended_action = "exam"
        elif due_count > 0:
            recommended_action = "review"
        elif (
            combined_accuracy is not None
            and combined_accuracy > 80
            and sm2_strength is not None
            and sm2_strength > 2.3
        ):
            recommended_action = "mastered"
        else:
            recommended_action = "study"

        results.append({
            "topic_id": topic_id,
            "topic_name": topic_info["name"],
            "priority_score": priority_score,
            "exam_accuracy_pct": exam_accuracy_pct,
            "review_accuracy_pct": review_accuracy_pct,
            "sm2_strength": sm2_strength,
            "exam_attempts": exam_attempts,
            "review_attempts": review_attempts,
            "due_count": due_count,
            "days_since_studied": days_since_studied,
            "recommended_action": recommended_action,
        })

    # Sort by priority_score DESC (highest urgency first)
    results.sort(key=lambda x: x["priority_score"], reverse=True)

    return {
        "user_id": user_id,
        "topics": results,
        "count": len(results),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Study Dashboard — Mastery Overview
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/study/dashboard/{user_id}")
def study_dashboard(user_id: str, _token: dict = Depends(get_current_user)):
    """
    Single-page mastery overview for a user.
    Rolls up: streak, totals, accuracy, SM-2 due, exam stats,
    recent exams, strongest/weakest topics, and study time estimate.
    """
    conn = get_connection()

    # ── Streak: consecutive days with any activity ──────────────────────────
    # Collect activity dates from exam completions and review logs
    cur = conn.execute(
        """
        SELECT date(completed_at) as day FROM exam_sessions
        WHERE user_id = ? AND status = 'completed'
        UNION
        SELECT date(reviewed_at) as day FROM review_logs
        WHERE user_id = ?
        ORDER BY day DESC
        """,
        (user_id, user_id),
    )
    activity_days = sorted({r["day"] for r in cur.fetchall()}, reverse=True)

    streak_days = 0
    today_str = str(date.today())
    if activity_days:
        # Walk backwards from today (or most recent activity) counting consecutive days
        # If today/yesterday has no activity, streak = 0
        if activity_days[0] == today_str:
            cursor_date = date.today()
        else:
            # Check if yesterday has activity (streak may still be live)
            yesterday = str(date.today() - timedelta(days=1))
            if yesterday in activity_days:
                cursor_date = date.today() - timedelta(days=1)
            else:
                streak_days = 0
                cursor_date = None

        if cursor_date is not None:
            for d in activity_days:
                if d == str(cursor_date):
                    streak_days += 1
                    cursor_date -= timedelta(days=1)
                else:
                    break

    # ── Total questions answered (exam + review) ────────────────────────────
    cur = conn.execute(
        """
        SELECT COUNT(DISTINCT question_id) AS exam_answered
        FROM exam_answers ea
        JOIN exam_sessions es ON es.id = ea.exam_session_id
        WHERE es.user_id = ?
        """,
        (user_id,)
    )
    exam_answered = cur.fetchone()["exam_answered"] or 0

    cur = conn.execute(
        "SELECT COUNT(*) AS review_answered FROM user_progress WHERE user_id = ?",
        (user_id,)
    )
    review_answered = cur.fetchone()["review_answered"] or 0

    total_questions_answered = exam_answered + review_answered

    # ── Overall accuracy (weighted exam + review) ──────────────────────────
    cur = conn.execute(
        """
        SELECT
            SUM(ea.is_correct) AS exam_correct,
            COUNT(ea.id) AS exam_total
        FROM exam_answers ea
        JOIN exam_sessions es ON es.id = ea.exam_session_id
        WHERE es.user_id = ?
        """,
        (user_id,)
    )
    exam_row = cur.fetchone()

    cur = conn.execute(
        """
        SELECT
            SUM(correct_count) AS review_correct,
            SUM(total_reviews) AS review_total
        FROM user_progress WHERE user_id = ?
        """,
        (user_id,)
    )
    review_row = cur.fetchone()

    total_correct = (exam_row["exam_correct"] or 0) + (review_row["review_correct"] or 0)
    total_attempts = (exam_row["exam_total"] or 0) + (review_row["review_total"] or 0)
    overall_accuracy_pct = (
        round(total_correct / total_attempts * 100, 1)
        if total_attempts > 0 else None
    )

    # ── SM-2 due today ──────────────────────────────────────────────────────
    cur = conn.execute(
        """
        SELECT COUNT(*) AS due_count FROM user_progress
        WHERE user_id = ? AND next_review_date <= ?
        """,
        (user_id, today_str)
    )
    sm2_due_today = cur.fetchone()["due_count"] or 0

    # ── Exam session stats ─────────────────────────────────────────────────
    cur = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'completed' AND score_percent >= pass_mark THEN 1 ELSE 0 END) AS passed,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_count
        FROM exam_sessions WHERE user_id = ?
        """,
        (user_id,)
    )
    exam_row2 = cur.fetchone()
    exam_sessions_total = exam_row2["total"] or 0
    exam_sessions_passed = exam_row2["passed"] or 0
    exam_pass_rate_pct = (
        round(exam_sessions_passed / exam_sessions_total * 100, 1)
        if exam_sessions_total > 0 else None
    )

    # ── Recent exams (last 5 completed) ────────────────────────────────────
    cur = conn.execute(
        """
        SELECT id AS exam_id, score_percent, pass_mark,
               (score_percent >= pass_mark) AS passed,
               completed_at
        FROM exam_sessions
        WHERE user_id = ? AND status = 'completed'
        ORDER BY completed_at DESC
        LIMIT 5
        """,
        (user_id,)
    )
    recent_exams = []
    for r in cur.fetchall():
        recent_exams.append({
            "exam_id": r["exam_id"],
            "score_percent": r["score_percent"],
            "passed": bool(r["passed"]),
            "completed_at": r["completed_at"],
        })

    conn.close()

    # ── Weakest / Strongest topics (reuse TASK 8 priority logic) ────────────
    # Build priority inline using same scoring as study_priority
    conn2 = get_connection()

    cur = conn2.execute("SELECT id, name, slug FROM topics")
    all_topics = {r["id"]: {"name": r["name"], "slug": r["slug"]} for r in cur.fetchall()}

    cur = conn2.execute(
        """
        SELECT ea.topic_id,
               COUNT(ea.id) AS exam_attempts,
               SUM(ea.is_correct) AS exam_correct,
               ROUND(100.0 * SUM(ea.is_correct) / COUNT(ea.id), 1) AS exam_accuracy_pct,
               MAX(ea.answered_at) AS last_exam_at
        FROM exam_answers ea
        JOIN exam_sessions es ON es.id = ea.exam_session_id
        WHERE es.user_id = ?
        GROUP BY ea.topic_id
        """,
        (user_id,)
    )
    exam_by_topic = {r["topic_id"]: dict(r) for r in cur.fetchall()}

    cur = conn2.execute(
        """
        SELECT q.topic_id,
               COUNT(up.id) AS review_attempts,
               SUM(up.correct_count) AS review_correct,
               ROUND(100.0 * SUM(up.correct_count) / SUM(up.total_reviews), 1) AS review_accuracy_pct,
               ROUND(AVG(up.easiness_factor), 2) AS sm2_strength,
               MAX(up.last_reviewed_at) AS last_review_at,
               SUM(CASE WHEN up.next_review_date <= date('now') THEN 1 ELSE 0 END) AS due_count
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id
        WHERE up.user_id = ?
        GROUP BY q.topic_id
        """,
        (user_id,)
    )
    review_by_topic = {r["topic_id"]: dict(r) for r in cur.fetchall()}
    conn2.close()

    now_ts = datetime.utcnow().timestamp()
    topic_scores = []

    for topic_id, topic_info in all_topics.items():
        exam   = exam_by_topic.get(topic_id, {})
        review = review_by_topic.get(topic_id, {})

        exam_accuracy_pct  = exam.get("exam_accuracy_pct")
        review_accuracy_pct = review.get("review_accuracy_pct")
        sm2_strength       = review.get("sm2_strength")
        exam_attempts       = exam.get("exam_attempts", 0)
        review_attempts     = review.get("review_attempts", 0)

        if exam_attempts > 0 and exam_accuracy_pct is not None:
            combined_accuracy = exam_accuracy_pct
        elif review_attempts > 0 and review_accuracy_pct is not None:
            combined_accuracy = review_accuracy_pct
        else:
            combined_accuracy = None

        last_exam_at   = exam.get("last_exam_at")
        last_review_at = review.get("last_review_at")
        last_studied_ts = None
        if last_exam_at:
            try: last_studied_ts = datetime.fromisoformat(last_exam_at).timestamp()
            except: pass
        if last_review_at:
            try:
                ts = datetime.fromisoformat(last_review_at).timestamp()
                if last_studied_ts is None or ts > last_studied_ts:
                    last_studied_ts = ts
            except: pass

        days_since_studied = None
        if last_studied_ts is not None:
            days_since_studied = round((now_ts - last_studied_ts) / 86400, 1)

        score = 0.0
        weight_total = 0.0
        if exam_accuracy_pct is not None:
            score += (100 - exam_accuracy_pct) * 0.40
            weight_total += 0.40
        if review_accuracy_pct is not None:
            score += (100 - review_accuracy_pct) * 0.20
            weight_total += 0.20
        if sm2_strength is not None:
            ef_component = max(0, (2.5 - sm2_strength) / 1.2 * 100)
            score += ef_component * 0.25
            weight_total += 0.25
        if days_since_studied is not None:
            recency_component = min(days_since_studied / 90.0, 1.0) * 100
            score += recency_component * 0.15
            weight_total += 0.15

        priority_score = round(score / weight_total, 1) if weight_total > 0 else 50.0

        topic_scores.append({
            "topic_id": topic_id,
            "topic_name": topic_info["name"],
            "topic_slug": topic_info["slug"],
            "priority_score": priority_score,
            "combined_accuracy_pct": combined_accuracy,
            "sm2_strength": sm2_strength,
        })

    # Weakest: highest priority score (most urgent)
    topic_scores.sort(key=lambda x: x["priority_score"], reverse=True)
    weakest_topics = [
        {"topic_id": t["topic_id"], "topic_name": t["topic_name"],
         "topic_slug": t["topic_slug"], "priority_score": t["priority_score"]}
        for t in topic_scores[:3]
    ]

    # Strongest: best combined accuracy and SM-2 strength
    # Filter to topics with some history, sort by accuracy desc then sm2 desc
    eligible = [t for t in topic_scores
                 if t["combined_accuracy_pct"] is not None and t["sm2_strength"] is not None
                 and t["combined_accuracy_pct"] > 70 and t["sm2_strength"] > 2.0]
    eligible.sort(key=lambda x: (x["combined_accuracy_pct"], x["sm2_strength"]), reverse=True)
    strongest_topics = [
        {"topic_id": t["topic_id"], "topic_name": t["topic_name"],
         "topic_slug": t["topic_slug"],
         "accuracy_pct": t["combined_accuracy_pct"], "sm2_strength": t["sm2_strength"]}
        for t in eligible[:3]
    ]

    # ── Study time estimate ────────────────────────────────────────────────
    study_time_estimate_minutes = sm2_due_today * 2

    return {
        "user_id": user_id,
        "streak_days": streak_days,
        "total_questions_answered": total_questions_answered,
        "overall_accuracy_pct": overall_accuracy_pct,
        "sm2_due_today": sm2_due_today,
        "exam_sessions_total": exam_sessions_total,
        "exam_sessions_passed": exam_sessions_passed,
        "exam_pass_rate_pct": exam_pass_rate_pct,
        "recent_exams": recent_exams,
        "weakest_topics": weakest_topics,
        "strongest_topics": strongest_topics,
        "study_time_estimate_minutes": study_time_estimate_minutes,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Smart Review Session — Guided Study Flow
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/study/review-session")
def review_session(req: ReviewSessionRequest, _token: dict = Depends(get_current_user)):
    """
    Generate a complete, sequenced study plan for a user in one call.
    Returns three sections:
      - due_reviews: up to `limit` cards due for SM-2 review today (oldest first)
      - new_questions: up to 5 fresh questions from weak topics (priority_score >= 60)
      - weak_topic_quiz: 3 questions from the user's weakest attempted topic
    Also creates a study_sessions record (status='in_progress').
    """
    import json

    conn = get_connection()

    # ── 1. Due reviews (oldest first, full card data) ─────────────────────
    cur = conn.execute(
        """
        SELECT q.id, q.topic_id, q.question_text, q.answer_text,
               q.explanation, q.reference_clause, q.difficulty,
               up.easiness_factor, up.interval, up.repetitions,
               up.next_review_date, up.last_reviewed_at,
               up.total_reviews, up.correct_count
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id
        WHERE up.user_id = ?
          AND up.next_review_date <= ?
          AND q.is_active = 1
        ORDER BY up.next_review_date ASC
        LIMIT ?
        """,
        (req.user_id, str(date.today()), req.limit),
    )
    due_rows = cur.fetchall()

    # ── 2. Compute topic priority scores (same logic as TASK 8) ───────────
    now_ts = datetime.utcnow().timestamp()

    cur = conn.execute("SELECT id, name, slug FROM topics")
    all_topics = {r["id"]: {"name": r["name"], "slug": r["slug"]} for r in cur.fetchall()}

    cur = conn.execute(
        """
        SELECT ea.topic_id,
               COUNT(ea.id) AS exam_attempts,
               SUM(ea.is_correct) AS exam_correct,
               ROUND(100.0 * SUM(ea.is_correct) / COUNT(ea.id), 1) AS exam_accuracy_pct,
               MAX(ea.answered_at) AS last_exam_at
        FROM exam_answers ea
        JOIN exam_sessions es ON es.id = ea.exam_session_id
        WHERE es.user_id = ?
        GROUP BY ea.topic_id
        """,
        (req.user_id,)
    )
    exam_by_topic = {r["topic_id"]: dict(r) for r in cur.fetchall()}

    cur = conn.execute(
        """
        SELECT q.topic_id,
               COUNT(up.id) AS review_attempts,
               SUM(up.correct_count) AS review_correct,
               ROUND(100.0 * SUM(up.correct_count) / SUM(up.total_reviews), 1) AS review_accuracy_pct,
               ROUND(AVG(up.easiness_factor), 2) AS sm2_strength,
               MAX(up.last_reviewed_at) AS last_review_at
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id
        WHERE up.user_id = ?
        GROUP BY q.topic_id
        """,
        (req.user_id,)
    )
    review_by_topic = {r["topic_id"]: dict(r) for r in cur.fetchall()}

    topic_priority = {}  # topic_id -> priority_score
    topic_info_map = {}

    for topic_id, info in all_topics.items():
        exam   = exam_by_topic.get(topic_id, {})
        review = review_by_topic.get(topic_id, {})

        exam_accuracy_pct  = exam.get("exam_accuracy_pct")
        review_accuracy_pct = review.get("review_accuracy_pct")
        sm2_strength       = review.get("sm2_strength")
        last_exam_at       = exam.get("last_exam_at")
        last_review_at     = review.get("last_review_at")

        last_studied_ts = None
        if last_exam_at:
            try: last_studied_ts = datetime.fromisoformat(last_exam_at).timestamp()
            except: pass
        if last_review_at:
            try:
                ts = datetime.fromisoformat(last_review_at).timestamp()
                if last_studied_ts is None or ts > last_studied_ts:
                    last_studied_ts = ts
            except: pass

        days_since_studied = None
        if last_studied_ts is not None:
            days_since_studied = round((now_ts - last_studied_ts) / 86400, 1)

        score = 0.0
        weight_total = 0.0
        if exam_accuracy_pct is not None:
            score += (100 - exam_accuracy_pct) * 0.40
            weight_total += 0.40
        if review_accuracy_pct is not None:
            score += (100 - review_accuracy_pct) * 0.20
            weight_total += 0.20
        if sm2_strength is not None:
            ef_component = max(0, (2.5 - sm2_strength) / 1.2 * 100)
            score += ef_component * 0.25
            weight_total += 0.25
        if days_since_studied is not None:
            recency_component = min(days_since_studied / 90.0, 1.0) * 100
            score += recency_component * 0.15
            weight_total += 0.15

        priority_score = round(score / weight_total, 1) if weight_total > 0 else 50.0
        topic_priority[topic_id] = priority_score
        topic_info_map[topic_id] = info

    # Weak topics: priority_score >= 60
    weak_topic_ids = [tid for tid, ps in topic_priority.items() if ps >= 60]

    # ── 3. New questions from weak topics (not yet in user_progress) ──────
    new_questions = []
    if weak_topic_ids:
        placeholders = ",".join("?" * len(weak_topic_ids))
        cur = conn.execute(
            f"""
            SELECT q.id, q.topic_id, q.question_text, q.answer_text,
                   q.explanation, q.reference_clause, q.difficulty
            FROM questions q
            WHERE q.is_active = 1
              AND q.topic_id IN ({placeholders})
              AND q.id NOT IN (
                  SELECT question_id FROM user_progress WHERE user_id = ?
              )
            ORDER BY RANDOM()
            LIMIT 5
            """,
            weak_topic_ids + [req.user_id],
        )
        new_questions = [dict(r) for r in cur.fetchall()]

    # ── 4. Weakest attempted topic (highest priority with exam_attempts > 0) ─
    attempted_topics = [
        (tid, topic_priority.get(tid, 50.0))
        for tid, exam_data in exam_by_topic.items()
        if exam_data.get("exam_attempts", 0) > 0
    ]
    attempted_topics.sort(key=lambda x: x[1], reverse=True)

    weak_topic_quiz = []
    if attempted_topics:
        weakest_id = attempted_topics[0][0]
        cur = conn.execute(
            """
            SELECT id, topic_id, question_text, answer_text,
                   explanation, reference_clause, difficulty
            FROM questions
            WHERE topic_id = ? AND is_active = 1
            ORDER BY RANDOM()
            LIMIT 3
            """,
            (weakest_id,)
        )
        weak_topic_quiz = [dict(r) for r in cur.fetchall()]

    conn.close()

    # ── 5. Persist study session ───────────────────────────────────────────
    all_q_ids = [r["id"] for r in due_rows] + [r["id"] for r in new_questions] + [r["id"] for r in weak_topic_quiz]
    session_id = str(uuid.uuid4())

    conn2 = get_connection()
    conn2.execute(
        """
        INSERT INTO study_sessions (id, user_id, type, status, question_ids, created_at)
        VALUES (?, ?, 'review', 'in_progress', ?, ?)
        """,
        (session_id, req.user_id, json.dumps(all_q_ids), datetime.utcnow().isoformat()),
    )
    conn2.commit()
    conn2.close()

    # ── 6. Build response ───────────────────────────────────────────────────
    due_reviews = []
    for r in due_rows:
        d = dict(r)
        due_reviews.append({
            "question_id": d["id"],
            "topic_id": d["topic_id"],
            "question_text": d["question_text"],
            "answer_text": d["answer_text"],
            "explanation": d["explanation"],
            "reference_clause": d.get("reference_clause"),
            "difficulty": d["difficulty"],
            "easiness_factor": d["easiness_factor"],
            "interval": d["interval"],
            "repetitions": d["repetitions"],
            "next_review_date": d["next_review_date"],
            "last_reviewed_at": d["last_reviewed_at"],
            "total_reviews": d["total_reviews"],
            "correct_count": d["correct_count"],
        })

    total_estimate_minutes = (len(due_reviews) + len(new_questions) + len(weak_topic_quiz)) * 2

    return {
        "session_id": session_id,
        "due_reviews": due_reviews,
        "new_questions": new_questions,
        "weak_topic_quiz": weak_topic_quiz,
        "total_estimate_minutes": total_estimate_minutes,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Review Session Grading — SM-2 Write-back
# ─────────────────────────────────────────────────────────────────────────────

class ReviewGradeItem(BaseModel):
    question_id: str
    quality: int = Field(ge=0, le=5)


class ReviewGradeRequest(BaseModel):
    user_id: str
    reviews: list[ReviewGradeItem]


@app.post("/api/study/review-session/{session_id}/grade")
def grade_review_session(session_id: str, req: ReviewGradeRequest, _token: dict = Depends(get_current_user)):
    """
    Receive SM-2 quality grades for cards in a review session,
    apply sm2_step() to each, and write updated fields to user_progress.
    Also writes a review_logs row per card.

    When all cards in the session have been graded, mark the session 'completed'.
    """
    import json

    conn = get_connection()

    # Load session
    cur = conn.execute(
        "SELECT * FROM study_sessions WHERE id = ? AND user_id = ?",
        (session_id, req.user_id),
    )
    session = cur.fetchone()
    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="Review session not found.")
    if session["status"] == "completed":
        conn.close()
        raise HTTPException(status_code=400, detail="Review session already completed.")

    question_ids_in_session = json.loads(session["question_ids"])
    graded_qids = {r.question_id for r in req.reviews}

    # ── Grade each card ───────────────────────────────────────────────────
    results = []
    for item in req.reviews:
        cur = conn.execute(
            "SELECT * FROM user_progress WHERE user_id = ? AND question_id = ?",
            (req.user_id, item.question_id),
        )
        row = cur.fetchone()
        if not row:
            # Card not in user_progress — upsert it
            conn.execute(
                """
                INSERT INTO user_progress (id, user_id, question_id,
                    easiness_factor, interval, repetitions,
                    next_review_date, last_reviewed_at,
                    total_reviews, correct_count)
                VALUES (?, ?, ?, 2.5, 0, 0, date('now'), NULL, 0, 0)
                """,
                (str(uuid.uuid4()), req.user_id, item.question_id),
            )
            cur = conn.execute(
                "SELECT * FROM user_progress WHERE user_id = ? AND question_id = ?",
                (req.user_id, item.question_id),
            )
            row = cur.fetchone()

        fields = SM2Fields(
            easiness_factor=row["easiness_factor"],
            interval=row["interval"],
            repetitions=row["repetitions"],
        )
        new_fields = sm2_step(fields, item.quality)

        ef_before = row["easiness_factor"]
        interval_before = row["interval"]
        q_correct = 1 if item.quality >= 3 else 0

        # Write new user_progress
        conn.execute(
            """
            UPDATE user_progress SET
                easiness_factor = ?,
                interval = ?,
                repetitions = ?,
                next_review_date = ?,
                last_reviewed_at = ?,
                total_reviews = total_reviews + 1,
                correct_count = correct_count + ?,
                updated_at = ?
            WHERE user_id = ? AND question_id = ?
            """,
            (
                new_fields.easiness_factor,
                new_fields.interval,
                new_fields.repetitions,
                str(new_fields.interval),
                datetime.utcnow().isoformat(),
                q_correct,
                datetime.utcnow().isoformat(),
                req.user_id,
                item.question_id,
            ),
        )

        # Write review_log
        log_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO review_logs (
                id, user_id, question_id, quality, quality_numeric,
                easiness_factor_before, easiness_factor_after,
                interval_before, interval_after,
                reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log_id,
                req.user_id,
                item.question_id,
                item.quality,
                item.quality,
                ef_before,
                new_fields.easiness_factor,
                interval_before,
                new_fields.interval,
                datetime.utcnow().isoformat(),
            ),
        )

        results.append({
            "question_id": item.question_id,
            "quality": item.quality,
            "passed": item.quality >= 3,
            "new_easiness_factor": new_fields.easiness_factor,
            "new_interval": new_fields.interval,
            "new_repetitions": new_fields.repetitions,
        })

    # ── Mark session completed if all cards graded ─────────────────────────
    graded_in_session = graded_qids & set(question_ids_in_session)
    if graded_in_session == set(question_ids_in_session):
        conn.execute(
            "UPDATE study_sessions SET status = 'completed' WHERE id = ?",
            (session_id,),
        )
        session_completed = True
    else:
        session_completed = False

    conn.commit()

    # Update streak and check badges (after commit so streak row is stable)
    _update_streak(conn, req.user_id)
    _check_and_award_badges(conn, req.user_id, session_type="review")
    conn.commit()
    conn.close()

    return {
        "session_id": session_id,
        "cards_graded": len(req.reviews),
        "results": results,
        "session_completed": session_completed,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Weakness Detection Engine
# ─────────────────────────────────────────────────────────────────────────────


WEAK_THRESHOLD_PCT = 70.0   # topics below this accuracy are "weak zones"


@app.get("/api/weak-zones/{user_id}")
def weak_zones(user_id: str):
    """
    Return topics below 70%% accuracy as "weak zones", sorted by urgency.
    Exam accuracy is weighted 2x over review accuracy.
    Never-seen topics are NOT flagged as weak — only actively-studied topics
    with sufficient data (< 2 attempts = insufficient data).

    Response:
      - weak_zones:  list of topics with accuracy < 70%%
      - caution_zones: topics 70-80%% (watch closely)
      - insufficient_data: topics seen < 2 times (can't assess)
      - drill_priority: ordered list of topic_ids to prioritise in next session
    """
    conn = get_connection()

    # All active topics
    cur = conn.execute("SELECT id, name, slug FROM topics ORDER BY name")
    all_topics = {r["id"]: {"name": r["name"], "slug": r["slug"]} for r in cur.fetchall()}

    # Exam accuracy per topic
    cur = conn.execute(
        """
        SELECT
            ea.topic_id,
            COUNT(ea.id) AS attempts,
            SUM(ea.is_correct) AS correct,
            ROUND(100.0 * SUM(ea.is_correct) / COUNT(ea.id), 1) AS accuracy_pct
        FROM exam_answers ea
        JOIN exam_sessions es ON es.id = ea.exam_session_id
        WHERE es.user_id = ?
        GROUP BY ea.topic_id
        """,
        (user_id,)
    )
    exam_acc = {r["topic_id"]: dict(r) for r in cur.fetchall()}

    # Review accuracy per topic
    cur = conn.execute(
        """
        SELECT
            q.topic_id,
            COUNT(up.id) AS attempts,
            SUM(up.correct_count) AS correct,
            ROUND(100.0 * SUM(up.correct_count) / SUM(up.total_reviews), 1) AS accuracy_pct
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id
        WHERE up.user_id = ?
        GROUP BY q.topic_id
        """,
        (user_id,)
    )
    review_acc = {r["topic_id"]: dict(r) for r in cur.fetchall()}

    conn.close()

    weak_zones = []
    caution_zones = []
    insufficient_data = []
    drill_priority = []

    for topic_id, info in all_topics.items():
        exam   = exam_acc.get(topic_id, {})
        review = review_acc.get(topic_id, {})

        exam_attempts = exam.get("attempts", 0)
        review_attempts = review.get("attempts", 0)
        total_attempts = exam_attempts + review_attempts

        # Weighted combined accuracy (exam weighted 2x)
        if exam_attempts > 0 and review_attempts > 0:
            combined_acc = round(
                (exam["accuracy_pct"] * 2 + review["accuracy_pct"]) / 3, 1
            )
        elif exam_attempts > 0:
            combined_acc = exam["accuracy_pct"]
        elif review_attempts > 0:
            combined_acc = review["accuracy_pct"]
        else:
            combined_acc = None

        entry = {
            "topic_id": topic_id,
            "topic_name": info["name"],
            "topic_slug": info["slug"],
            "exam_attempts": exam_attempts,
            "exam_accuracy_pct": exam.get("accuracy_pct"),
            "review_attempts": review_attempts,
            "review_accuracy_pct": review.get("accuracy_pct"),
            "combined_accuracy_pct": combined_acc,
        }

        if total_attempts < 2:
            entry["total_attempts"] = total_attempts
            insufficient_data.append(entry)
        elif combined_acc is not None and combined_acc < WEAK_THRESHOLD_PCT:
            entry["total_attempts"] = total_attempts
            entry["gap_from_pass"] = round(WEAK_THRESHOLD_PCT - combined_acc, 1)
            weak_zones.append(entry)
            drill_priority.append(topic_id)
        elif combined_acc is not None and combined_acc < 80.0:
            entry["total_attempts"] = total_attempts
            caution_zones.append(entry)

    # Sort weak zones by gap (largest gap = most urgent)
    weak_zones.sort(key=lambda x: x["gap_from_pass"], reverse=True)
    caution_zones.sort(key=lambda x: x["combined_accuracy_pct"])

    return {
        "user_id": user_id,
        "weak_threshold_pct": WEAK_THRESHOLD_PCT,
        "weak_zones": weak_zones,
        "caution_zones": caution_zones,
        "insufficient_data": insufficient_data,
        "drill_priority": drill_priority,
        "weak_count": len(weak_zones),
        "caution_count": len(caution_zones),
    }


@app.get("/api/weak-zones/{user_id}/review-queue")
def weak_zones_review_queue(user_id: str, limit: int = Query(10)):
    """
    Return a prioritised review queue targeting weak zones.
    Orders due/new questions by topic priority score
    (prioritising topics with lowest combined accuracy).
    """
    conn = get_connection()

    # Get weak zone data
    weak_data = weak_zones(user_id)  # reuse above logic (dict response)
    drill_priority = weak_data["drill_priority"]

    # Build priority map: topic_id -> priority rank (0=highest urgency)
    priority_map = {tid: rank for rank, tid in enumerate(drill_priority)}

    # Due questions with priority
    cur = conn.execute(
        """
        SELECT q.*, up.easiness_factor, up.interval, up.repetitions,
               up.next_review_date, up.last_reviewed_at,
               up.total_reviews, up.correct_count
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id
        WHERE up.user_id = ?
          AND up.next_review_date <= ?
          AND q.is_active = 1
        ORDER BY q.topic_id
        """,
        (user_id, str(date.today())),
    )
    due_rows = cur.fetchall()

    # New questions (never seen) for weak zone topics
    if drill_priority:
        placeholders = ",".join("?" * len(drill_priority))
        cur = conn.execute(
            f"""
            SELECT q.*
            FROM questions q
            WHERE q.is_active = 1
              AND q.id NOT IN (
                  SELECT question_id FROM user_progress WHERE user_id = ?
              )
              AND q.topic_id IN ({placeholders})
            ORDER BY q.topic_id
            """,
            [user_id] + drill_priority,
        )
        new_rows = cur.fetchall()
    else:
        new_rows = []

    conn.close()

    def priority_sort_key(row):
        tid = row["topic_id"]
        return priority_map.get(tid, 999)

    # Merge and sort
    merged = []
    for r in sorted(due_rows, key=priority_sort_key):
        d = _q_row(r)
        d["mode"] = "review"
        d["topic_priority_rank"] = priority_map.get(r["topic_id"], 99)
        merged.append(d)
    for r in sorted(new_rows, key=priority_sort_key):
        d = _q_row(r)
        d["mode"] = "new"
        d["topic_priority_rank"] = priority_map.get(r["topic_id"], 99)
        merged.append(d)

    return {
        "user_id": user_id,
        "queue": merged[:limit],
        "weak_zone_count": weak_data["weak_count"],
        "caution_zone_count": weak_data["caution_count"],
        "prioritised_topics": [
            {"topic_id": tid, "topic_name": next(
                (t["topic_name"] for t in weak_data["weak_zones"] if t["topic_id"] == tid
            ), "unknown")}
            for tid in drill_priority
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Exam Simulation
# ─────────────────────────────────────────────────────────────────────────────

class ExamStartRequest(BaseModel):
    user_id: str
    topic_ids: Optional[list[int]] = None
    question_count: int = Field(default=10, ge=1, le=200)
    time_limit_minutes: int = Field(default=120, ge=10, le=240)
    pass_mark: float = Field(default=70.0, ge=50.0, le=100.0)


class ExamAnswerItem(BaseModel):
    question_id: str
    selected_answer_index: int


class ExamSubmitRequest(BaseModel):
    answers: list[ExamAnswerItem]


@app.post("/api/study/exam-session")
def start_exam_session(req: ExamStartRequest, _token: dict = Depends(get_current_user)):
    """
    Start a new exam session.
    Questions are drawn first from topics never attempted (exam_attempts=0)
    or where exam_accuracy < 60%%, then fall back to random active questions.
    Creates an exam_sessions row (status='in_progress') and returns
    the question list (including options) for the client to display.
    """
    import json

    conn = get_connection()

    # Build topic filter clause
    if req.topic_ids:
        tp_placeholders = ",".join("?" * len(req.topic_ids))
        topic_filter_sql = f"AND q.topic_id IN ({tp_placeholders})"
        topic_filter_args: list = list(req.topic_ids)
    else:
        topic_filter_sql = ""
        topic_filter_args = []

    never_seen_ids: set = set()
    low_accuracy_ids: set = set()

    # Query 1: never-seen questions
    cur = conn.execute(
        f"""
        SELECT q.id, q.topic_id, q.question_text, q.answer_text,
               q.explanation, q.reference_clause, q.difficulty,
               q.options, q.correct_answer_index
        FROM questions q
        WHERE q.is_active = 1
          {topic_filter_sql}
          AND q.id NOT IN (
              SELECT ea.question_id
              FROM exam_answers ea
              JOIN exam_sessions es ON es.id = ea.exam_session_id
              WHERE es.user_id = ?
          )
        ORDER BY RANDOM()
        LIMIT ?
        """,
        [req.user_id] + topic_filter_args + [req.question_count],
    )
    never_seen = list(cur.fetchall())
    never_seen_ids = {r["id"] for r in never_seen}

    # Query 2: low-accuracy questions (excluding already-seen)
    remaining = req.question_count - len(never_seen)
    if remaining > 0:
        cur = conn.execute(
            f"""
            SELECT q.id, q.topic_id, q.question_text, q.answer_text,
                   q.explanation, q.reference_clause, q.difficulty,
                   q.options, q.correct_answer_index
            FROM questions q
            WHERE q.is_active = 1
              {topic_filter_sql}
              AND q.id IN (
                  SELECT ea.question_id
                  FROM exam_answers ea
                  JOIN exam_sessions es ON es.id = ea.exam_session_id
                  WHERE es.user_id = ?
                  GROUP BY ea.question_id
                  HAVING ROUND(100.0 * SUM(ea.is_correct) / COUNT(ea.id), 1) < 60.0
              )
              AND q.id NOT IN (SELECT value FROM json_each(?))
            ORDER BY RANDOM()
            LIMIT ?
            """,
            [req.user_id] + topic_filter_args
            + [json.dumps(list(never_seen_ids)), remaining],
        )
        low_accuracy = list(cur.fetchall())
        low_accuracy_ids = {r["id"] for r in low_accuracy}
    else:
        low_accuracy = []

    # Query 3: random fallback for any still-remaining slots
    fill_remaining = req.question_count - len(never_seen) - len(low_accuracy)
    if fill_remaining > 0:
        seen_ids_list = list(never_seen_ids | low_accuracy_ids)
        if seen_ids_list:
            not_in_sql = "AND q.id NOT IN (" + ",".join("?" * len(seen_ids_list)) + ")"
            not_in_args: list = seen_ids_list
        else:
            not_in_sql = ""
            not_in_args = []
        cur = conn.execute(
            f"""
            SELECT q.id, q.topic_id, q.question_text, q.answer_text,
                   q.explanation, q.reference_clause, q.difficulty,
                   q.options, q.correct_answer_index
            FROM questions q
            WHERE q.is_active = 1
              {topic_filter_sql}
              {not_in_sql}
            ORDER BY RANDOM()
            LIMIT ?
            """,
            topic_filter_args + not_in_args + [fill_remaining],
        )
        random_fallback = list(cur.fetchall())
    else:
        random_fallback = []

    conn.close()

    selected = never_seen + low_accuracy + random_fallback

    if not selected:
        raise HTTPException(
            status_code=400,
            detail="No questions available for the specified criteria.",
        )

    exam_q_ids = [r["id"] for r in selected]
    topic_ids_used = list({r["topic_id"] for r in selected})
    session_id = str(uuid.uuid4())

    # Persist exam session
    conn2 = get_connection()
    conn2.execute(
        """
        INSERT INTO exam_sessions
            (id, user_id, question_ids, topic_ids, total_questions,
             time_limit_minutes, pass_mark, status, started_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'in_progress', ?)
        """,
        (
            session_id,
            req.user_id,
            json.dumps(exam_q_ids),
            json.dumps(topic_ids_used),
            len(exam_q_ids),
            req.time_limit_minutes,
            req.pass_mark,
            datetime.utcnow().isoformat(),
        ),
    )
    conn2.commit()
    conn2.close()

    # Build question payload for client
    questions_out = []
    for r in selected:
        import json as _json
        opts = _json.loads(r["options"]) if r["options"] else []
        questions_out.append({
            "question_id": r["id"],
            "topic_id": r["topic_id"],
            "question_text": r["question_text"],
            "options": opts,
            "difficulty": r["difficulty"],
            "explanation": r["explanation"],
            "reference_clause": r["reference_clause"],
        })

    total_estimate = len(questions_out) * 1.5  # 1.5 min per exam Q rough guide

    return {
        "exam_session_id": session_id,
        "total_questions": len(questions_out),
        "time_limit_minutes": req.time_limit_minutes,
        "pass_mark": req.pass_mark,
        "questions": questions_out,
        "total_estimate_minutes": round(total_estimate, 1),
    }


@app.post("/api/study/exam-session/{exam_session_id}/submit")
def submit_exam_session(exam_session_id: str, req: ExamSubmitRequest, _token: dict = Depends(get_current_user)):
    """
    Grade an exam session.
    Accepts a list of {question_id, selected_answer_index} answers.
    Updates exam_sessions (score, status='completed') and writes exam_answers rows.
    Returns score breakdown by topic and overall pass/fail.
    """
    import json

    conn = get_connection()

    # Load exam session
    cur = conn.execute(
        "SELECT * FROM exam_sessions WHERE id = ?",
        (exam_session_id,),
    )
    session = cur.fetchone()
    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="Exam session not found.")
    if session["status"] == "completed":
        conn.close()
        raise HTTPException(status_code=400, detail="Exam already submitted.")

    question_ids = json.loads(session["question_ids"])
    answer_map = {a.question_id: a.selected_answer_index for a in req.answers}

    # Fetch correct answers for all questions in session
    placeholders = ",".join("?" * len(question_ids))
    cur = conn.execute(
        f"""
        SELECT id, topic_id, correct_answer_index, options
        FROM questions WHERE id IN ({placeholders})
        """,
        question_ids,
    )
    question_info = {r["id"]: dict(r) for r in cur.fetchall()}

    # Grade each answer and write exam_answers rows
    correct_count = 0
    topic_results = {}  # topic_id -> {total, correct}
    answer_details = []

    for qid in question_ids:
        info = question_info.get(qid)
        if not info:
            continue

        selected = answer_map.get(qid)
        is_correct = 1 if selected == info["correct_answer_index"] else 0
        if is_correct:
            correct_count += 1

        # Track per-topic
        tid = info["topic_id"]
        if tid not in topic_results:
            topic_results[tid] = {"total": 0, "correct": 0}
        topic_results[tid]["total"] += 1
        if is_correct:
            topic_results[tid]["correct"] += 1

        # Write exam_answer row
        answer_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO exam_answers
                (id, exam_session_id, question_id, selected_answer_index,
                 is_correct, topic_id, answered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                answer_id,
                exam_session_id,
                qid,
                selected,
                is_correct,
                tid,
                datetime.utcnow().isoformat(),
            ),
        )

        # Include detail in response (correct answer revealed)
        import json as _json
        opts = _json.loads(info["options"]) if info.get("options") else []
        answer_details.append({
            "question_id": qid,
            "topic_id": tid,
            "selected_answer_index": selected,
            "correct_answer_index": info["correct_answer_index"],
            "is_correct": bool(is_correct),
            "correct_answer": opts[info["correct_answer_index"]] if opts else info["answer_text"],
        })

    total = len(question_ids)
    score_pct = round(100.0 * correct_count / total, 1) if total > 0 else 0.0
    passed = score_pct >= session["pass_mark"]

    # Time spent
    started = datetime.fromisoformat(session["started_at"])
    time_spent = int((datetime.utcnow() - started).total_seconds())

    # Update exam session
    conn.execute(
        """
        UPDATE exam_sessions
        SET correct_count = ?, score_percent = ?, status = 'completed',
            time_spent_seconds = ?, completed_at = ?
        WHERE id = ?
        """,
        (
            correct_count,
            score_pct,
            time_spent,
            datetime.utcnow().isoformat(),
            exam_session_id,
        ),
    )
    conn.commit()

    # Update streak and check badges (pass exam score for perfect_exam badge)
    _update_streak(conn, session["user_id"])
    _check_and_award_badges(conn, session["user_id"], session_type="exam",
                             exam_score_percent=score_pct)
    conn.commit()
    conn.close()

    # Build topic breakdown
    topic_breakdown = []
    for tid, stats in sorted(topic_results.items()):
        pct = round(100.0 * stats["correct"] / stats["total"], 1) if stats["total"] > 0 else 0.0
        topic_breakdown.append({
            "topic_id": tid,
            "total": stats["total"],
            "correct": stats["correct"],
            "score_pct": pct,
            "passed": pct >= session["pass_mark"],
        })

    return {
        "exam_session_id": exam_session_id,
        "total_questions": total,
        "correct_count": correct_count,
        "score_percent": score_pct,
        "pass_mark": session["pass_mark"],
        "passed": passed,
        "time_spent_seconds": time_spent,
        "topic_breakdown": topic_breakdown,
        "answers": answer_details,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Focus Session — Weak Zone Deep Drill
# ─────────────────────────────────────────────────────────────────────────────

class FocusSessionRequest(BaseModel):
    user_id: str
    topic_ids: Optional[list[int]] = None   # null = all weak topics
    question_count: int = Field(default=10, ge=1, le=50)


class FocusAnswerItem(BaseModel):
    question_id: str
    selected_answer_index: int


class FocusSubmitRequest(BaseModel):
    answers: list[FocusAnswerItem]


@app.post("/api/study/focus-session")
def start_focus_session(req: FocusSessionRequest, _token: dict = Depends(get_current_user)):
    """
    Generate a focused study session targeting the user's weakest topics.

    - Draws questions from topics with priority_score >= 40 (weak zones)
    - Within each weak topic: most-failed questions come first
    - Questions answered incorrectly in exams/reviews get repeated more often
      (weighted selection: incorrect → 3x weight, never seen → 1x weight)
    - Creates a study_sessions row with type='focus'

    Returns:
      session_id, questions[], topic_breakdown[], total_estimate_minutes
    """
    WEAK_THRESHOLD = 40.0
    now_ts = datetime.utcnow().timestamp()

    conn = get_connection()

    # ── 1. Build topic priority scores (same logic as /priority endpoint) ───
    cur = conn.execute("SELECT id, name, slug FROM topics")
    all_topics = {r["id"]: {"name": r["name"], "slug": r["slug"]} for r in cur.fetchall()}

    cur = conn.execute(
        """
        SELECT ea.topic_id,
               COUNT(ea.id) AS exam_attempts,
               SUM(ea.is_correct) AS exam_correct,
               ROUND(100.0 * SUM(ea.is_correct) / COUNT(ea.id), 1) AS exam_accuracy_pct,
               MAX(ea.answered_at) AS last_exam_at
        FROM exam_answers ea
        JOIN exam_sessions es ON es.id = ea.exam_session_id
        WHERE es.user_id = ?
        GROUP BY ea.topic_id
        """,
        (req.user_id,)
    )
    exam_by_topic = {r["topic_id"]: dict(r) for r in cur.fetchall()}

    cur = conn.execute(
        """
        SELECT q.topic_id,
               COUNT(up.id) AS review_attempts,
               SUM(up.correct_count) AS review_correct,
               ROUND(100.0 * SUM(up.correct_count) / SUM(up.total_reviews), 1) AS review_accuracy_pct,
               ROUND(AVG(up.easiness_factor), 2) AS sm2_strength,
               MAX(up.last_reviewed_at) AS last_review_at
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id
        WHERE up.user_id = ?
        GROUP BY q.topic_id
        """,
        (req.user_id,)
    )
    review_by_topic = {r["topic_id"]: dict(r) for r in cur.fetchall()}

    topic_priority = {}  # topic_id -> priority_score
    for topic_id, info in all_topics.items():
        exam   = exam_by_topic.get(topic_id, {})
        review = review_by_topic.get(topic_id, {})

        exam_accuracy_pct    = exam.get("exam_accuracy_pct")
        review_accuracy_pct  = review.get("review_accuracy_pct")
        sm2_strength         = review.get("sm2_strength")
        last_exam_at         = exam.get("last_exam_at")
        last_review_at       = review.get("last_review_at")

        last_studied_ts = None
        if last_exam_at:
            try: last_studied_ts = datetime.fromisoformat(last_exam_at).timestamp()
            except: pass
        if last_review_at:
            try:
                ts = datetime.fromisoformat(last_review_at).timestamp()
                if last_studied_ts is None or ts > last_studied_ts:
                    last_studied_ts = ts
            except: pass

        days_since_studied = None
        if last_studied_ts is not None:
            days_since_studied = round((now_ts - last_studied_ts) / 86400, 1)

        score = 0.0
        weight_total = 0.0
        if exam_accuracy_pct is not None:
            score += (100 - exam_accuracy_pct) * 0.40
            weight_total += 0.40
        if review_accuracy_pct is not None:
            score += (100 - review_accuracy_pct) * 0.20
            weight_total += 0.20
        if sm2_strength is not None:
            ef_component = max(0, (2.5 - sm2_strength) / 1.2 * 100)
            score += ef_component * 0.25
            weight_total += 0.25
        if days_since_studied is not None:
            recency_component = min(days_since_studied / 90.0, 1.0) * 100
            score += recency_component * 0.15
            weight_total += 0.15

        priority_score = round(score / weight_total, 1) if weight_total > 0 else 50.0
        topic_priority[topic_id] = priority_score

    # ── 2. Filter to weak topics (priority_score >= 70) ─────────────────────
    weak_topic_ids = [
        tid for tid, ps in topic_priority.items()
        if ps >= WEAK_THRESHOLD
        and (not req.topic_ids or tid in req.topic_ids)
    ]
    # Sort by descending priority_score
    weak_topic_ids.sort(key=lambda tid: topic_priority[tid], reverse=True)

    if not weak_topic_ids:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=(
                f"No weak topics found (priority_score >= {WEAK_THRESHOLD}) "
                f"for user. Try a higher question_count or no topic filter."
            ),
        )

    # ── 3. For each weak topic, compute personal failure rate per question ──
    #    weight = 3 if ever failed, 1 if never attempted
    #    Build a weighted pool and sample
    import random
    random.seed()  # fresh randomness each call

    selected_questions = []
    used_question_ids: set = set()
    topic_question_counts: dict = {}  # topic_id -> count selected

    for tid in weak_topic_ids:
        if len(selected_questions) >= req.question_count:
            break

        # Personal accuracy for each question in this topic
        cur = conn.execute(
            """
            SELECT
                q.id,
                q.topic_id,
                q.question_text,
                q.answer_text,
                q.explanation,
                q.reference_clause,
                q.difficulty,
                q.options,
                q.correct_answer_index,
                -- Exam failure rate
                COALESCE(
                    ROUND(
                        100.0 * (
                            COUNT(ea.id) - SUM(ea.is_correct)
                        ) / COUNT(ea.id),
                    1),
                    0.0
                ) AS exam_fail_pct,
                -- Review failure rate
                COALESCE(
                    ROUND(
                        100.0 * (
                            up.total_reviews - up.correct_count
                        ) / up.total_reviews,
                    1),
                    0.0
                ) AS review_fail_pct,
                -- Ever failed in exam?
                MAX(
                    CASE WHEN ea.is_correct = 0 THEN 1 ELSE 0 END
                ) AS ever_failed_exam,
                -- Ever failed in review?
                MAX(
                    CASE WHEN (up.total_reviews > up.correct_count) THEN 1 ELSE 0 END
                ) AS ever_failed_review
            FROM questions q
            LEFT JOIN exam_answers ea
                ON ea.question_id = q.id
                AND ea.exam_session_id IN (
                    SELECT id FROM exam_sessions WHERE user_id = ?
                )
            LEFT JOIN user_progress up
                ON up.question_id = q.id
                AND up.user_id = ?
            WHERE q.topic_id = ?
              AND q.is_active = 1
            GROUP BY q.id
            ORDER BY exam_fail_pct DESC, review_fail_pct DESC
            """,
            (req.user_id, req.user_id, tid),
        )

        rows = cur.fetchall()
        # Build weighted pool: 3x weight for ever-failed, 1x for never-failed
        weighted_pool = []
        for r in rows:
            ever_failed = r["ever_failed_exam"] or r["ever_failed_review"]
            weight = 3 if ever_failed else 1
            weighted_pool.extend([dict(r)] * weight)

        # Shuffle weighted pool
        random.shuffle(weighted_pool)

        # De-duplicate against already-selected
        slots_remaining = req.question_count - len(selected_questions)
        for wrow in weighted_pool:
            if len(selected_questions) >= req.question_count:
                break
            qid = wrow["id"]
            if qid not in used_question_ids:
                selected_questions.append(wrow)
                used_question_ids.add(qid)
                topic_question_counts[tid] = topic_question_counts.get(tid, 0) + 1

    if not selected_questions:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="No questions available for the specified weak topics.",
        )

    # ── 4. Persist study_sessions row (type='focus') ───────────────────────
    session_id = str(uuid.uuid4())
    question_ids = [r["id"] for r in selected_questions]

    conn.execute(
        """
        INSERT INTO study_sessions (id, user_id, type, status, question_ids, created_at)
        VALUES (?, ?, 'focus', 'in_progress', ?, ?)
        """,
        (session_id, req.user_id, json.dumps(question_ids), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

    # ── 5. Build question payload ───────────────────────────────────────────
    questions_out = []
    for r in selected_questions:
        import json as _json
        opts = _json.loads(r["options"]) if r["options"] else []
        questions_out.append({
            "question_id": r["id"],
            "topic_id": r["topic_id"],
            "question_text": r["question_text"],
            "options": opts,
            "difficulty": r["difficulty"],
            "explanation": r["explanation"],
            "reference_clause": r["reference_clause"],
        })

    # ── 6. Build topic breakdown ────────────────────────────────────────────
    topic_breakdown = []
    for tid in weak_topic_ids:
        if tid in topic_question_counts:
            topic_breakdown.append({
                "topic_id": tid,
                "name": all_topics[tid]["name"],
                "priority_score": topic_priority[tid],
                "question_count": topic_question_counts[tid],
            })

    # Sort by priority_score DESC
    topic_breakdown.sort(key=lambda x: x["priority_score"], reverse=True)

    total_estimate = len(questions_out) * 1.5  # 1.5 min per focus Q

    return {
        "session_id": session_id,
        "total_questions": len(questions_out),
        "questions": questions_out,
        "topic_breakdown": topic_breakdown,
        "total_estimate_minutes": round(total_estimate, 1),
    }


@app.post("/api/study/focus-session/{session_id}/submit")
def submit_focus_session(session_id: str, req: FocusSubmitRequest, _token: dict = Depends(get_current_user)):
    """
    Grade a focus session.

    - Accepts {answers: [{question_id, selected_answer_index}]}
    - Converts to SM-2 quality grades: correct (quality>=3), incorrect (quality<3)
    - Writes exam_answers rows for historical tracking
    - Updates user_progress via SM-2
    - Marks study_sessions row as 'completed'
    - Returns score breakdown by topic and overall pass/fail
    """
    import json

    conn = get_connection()

    # Load focus session
    cur = conn.execute(
        "SELECT * FROM study_sessions WHERE id = ? AND type = 'focus'",
        (session_id,),
    )
    session = cur.fetchone()
    if not session:
        conn.close()
        raise HTTPException(status_code=404, detail="Focus session not found.")
    if session["status"] == "completed":
        conn.close()
        raise HTTPException(status_code=400, detail="Focus session already submitted.")
    if session["user_id"] != req.answers[0].question_id and len(req.answers) > 0:
        pass  # user_id check deferred to actual answers

    question_ids = json.loads(session["question_ids"])
    answer_map = {a.question_id: a.selected_answer_index for a in req.answers}

    # Fetch correct answers
    placeholders = ",".join("?" * len(question_ids))
    cur = conn.execute(
        f"""
        SELECT id, topic_id, correct_answer_index, options, question_text
        FROM questions WHERE id IN ({placeholders})
        """,
        question_ids,
    )
    question_info = {r["id"]: dict(r) for r in cur.fetchall()}

    correct_count = 0
    topic_results = {}  # topic_id -> {total, correct}
    answer_details = []
    sm2_results = []

    for qid in question_ids:
        info = question_info.get(qid)
        if not info:
            continue

        selected = answer_map.get(qid)
        is_correct = 1 if selected == info["correct_answer_index"] else 0
        if is_correct:
            correct_count += 1

        tid = info["topic_id"]
        if tid not in topic_results:
            topic_results[tid] = {"total": 0, "correct": 0}
        topic_results[tid]["total"] += 1
        if is_correct:
            topic_results[tid]["correct"] += 1

        # Write exam_answer row (tracks every answer for history)
        answer_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO exam_answers
                (id, exam_session_id, question_id, selected_answer_index,
                 is_correct, topic_id, answered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (answer_id, session_id, qid, selected, is_correct, tid, datetime.utcnow().isoformat()),
        )

        # Convert to SM-2 quality and apply to user_progress
        quality = 4 if is_correct else 1  # correct→q=4, incorrect→q=1

        cur = conn.execute(
            "SELECT * FROM user_progress WHERE user_id = ? AND question_id = ?",
            (session["user_id"], qid),
        )
        row = cur.fetchone()
        if not row:
            # Upsert new
            conn.execute(
                """
                INSERT INTO user_progress (id, user_id, question_id,
                    easiness_factor, interval, repetitions,
                    next_review_date, last_reviewed_at,
                    total_reviews, correct_count)
                VALUES (?, ?, ?, 2.5, 0, 0, date('now'), NULL, 0, 0)
                """,
                (str(uuid.uuid4()), session["user_id"], qid),
            )
            cur = conn.execute(
                "SELECT * FROM user_progress WHERE user_id = ? AND question_id = ?",
                (session["user_id"], qid),
            )
            row = cur.fetchone()

        fields = SM2Fields(
            easiness_factor=row["easiness_factor"],
            interval=row["interval"],
            repetitions=row["repetitions"],
        )
        new_fields = sm2_step(fields, quality)

        # Write updated user_progress
        conn.execute(
            """
            UPDATE user_progress SET
                easiness_factor = ?,
                interval = ?,
                repetitions = ?,
                next_review_date = ?,
                last_reviewed_at = ?,
                total_reviews = total_reviews + 1,
                correct_count = correct_count + ?,
                updated_at = ?
            WHERE user_id = ? AND question_id = ?
            """,
            (
                new_fields.easiness_factor,
                new_fields.interval,
                new_fields.repetitions,
                str(new_fields.interval),
                datetime.utcnow().isoformat(),
                is_correct,
                datetime.utcnow().isoformat(),
                session["user_id"],
                qid,
            ),
        )

        # Write review_log
        log_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO review_logs (
                id, user_id, question_id, quality, quality_numeric,
                easiness_factor_before, easiness_factor_after,
                interval_before, interval_after, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log_id,
                session["user_id"],
                qid,
                quality,
                quality,
                row["easiness_factor"],
                new_fields.easiness_factor,
                row["interval"],
                new_fields.interval,
                datetime.utcnow().isoformat(),
            ),
        )

        sm2_results.append({
            "question_id": qid,
            "quality": quality,
            "new_easiness_factor": new_fields.easiness_factor,
            "new_interval": new_fields.interval,
        })

        # Include detail in response
        import json as _json
        opts = _json.loads(info["options"]) if info.get("options") else []
        answer_details.append({
            "question_id": qid,
            "topic_id": tid,
            "selected_answer_index": selected,
            "correct_answer_index": info["correct_answer_index"],
            "is_correct": bool(is_correct),
            "correct_answer": opts[info["correct_answer_index"]] if opts else info["answer_text"],
        })

    total = len(question_ids)
    score_pct = round(100.0 * correct_count / total, 1) if total > 0 else 0.0
    pass_mark = 70.0
    passed = score_pct >= pass_mark

    # Mark session completed
    conn.execute(
        "UPDATE study_sessions SET status = 'completed' WHERE id = ?",
        (session_id,),
    )
    conn.commit()

    # Update streak and check badges (focus_drill badge)
    _update_streak(conn, session["user_id"])
    _check_and_award_badges(conn, session["user_id"], session_type="focus")
    conn.commit()
    conn.close()

    # Build topic breakdown
    topic_breakdown = []
    for tid, stats in sorted(topic_results.items()):
        pct = round(100.0 * stats["correct"] / stats["total"], 1) if stats["total"] > 0 else 0.0
        topic_breakdown.append({
            "topic_id": tid,
            "total": stats["total"],
            "correct": stats["correct"],
            "score_pct": pct,
            "passed": pct >= pass_mark,
        })

    return {
        "session_id": session_id,
        "total_questions": total,
        "correct_count": correct_count,
        "score_percent": score_pct,
        "pass_mark": pass_mark,
        "passed": passed,
        "topic_breakdown": topic_breakdown,
        "answers": answer_details,
        "sm2_results": sm2_results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Streaks & Gamification Helpers
# ─────────────────────────────────────────────────────────────────────────────

# Badge definitions
BADGE_DEFINITIONS = {
    "first_session": {
        "badge_name": "First Steps",
        "description": "Completed your first study session.",
    },
    "streak_3": {
        "badge_name": "Hat-Trick",
        "description": "Studied 3 days in a row.",
    },
    "streak_7": {
        "badge_name": "Week Warrior",
        "description": "Studied 7 days in a row.",
    },
    "streak_14": {
        "badge_name": "Fortnight Focus",
        "description": "Studied 14 days in a row.",
    },
    "streak_30": {
        "badge_name": "Monthly Master",
        "description": "Studied 30 days in a row.",
    },
    "volume_50": {
        "badge_name": "Question Quantity",
        "description": "Answered 50 questions.",
    },
    "volume_100": {
        "badge_name": "Centurion",
        "description": "Answered 100 questions.",
    },
    "volume_500": {
        "badge_name": "Volume King",
        "description": "Answered 500 questions.",
    },
    "accuracy_80": {
        "badge_name": "High Flier",
        "description": "Maintained 80%+ average accuracy.",
    },
    "accuracy_90": {
        "badge_name": "Precision Expert",
        "description": "Maintained 90%+ average accuracy.",
    },
    "first_exam_passed": {
        "badge_name": "Exam Ready",
        "description": "Passed your first exam.",
    },
    "exams_5_passed": {
        "badge_name": "Exam Veteran",
        "description": "Passed 5 exams.",
    },
    "exams_10_passed": {
        "badge_name": "Exam Champion",
        "description": "Passed 10 exams.",
    },
    "perfect_exam": {
        "badge_name": "Perfect Score",
        "description": "Scored 100% on an exam session.",
    },
    "focus_drill": {
        "badge_name": "Focus Drill",
        "description": "Completed a focus drill session.",
    },
    "focus_10": {
        "badge_name": "Focus Master",
        "description": "Completed 10 focus drill sessions.",
    },
    "all_topics_attempted": {
        "badge_name": "Well Rounded",
        "description": "Attempted at least one question from every topic.",
    },
}


def _update_streak(conn, user_id: str):
    """
    Update streak for user after any study activity.
    Called at the end of grade_review_session, submit_exam_session,
    submit_focus_session.
    Uses UTC for all date comparisons to match datetime.utcnow() used
    throughout the rest of the submission pipeline.
    """
    today_utc = datetime.utcnow().date()
    today_str = str(today_utc)

    # Get or create streak row
    cur = conn.execute(
        "SELECT * FROM study_streaks WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()

    if not row:
        # First ever activity — create row, start streak at 1
        conn.execute(
            """
            INSERT INTO study_streaks
                (user_id, current_streak, longest_streak, last_study_date, total_study_days, streak_freeze_tokens)
            VALUES (?, 1, 1, ?, 1, 1)
            """,
            (user_id, today_str),
        )
        return

    last_date = row["last_study_date"]
    current_streak = row["current_streak"]
    longest_streak = row["longest_streak"]
    total_days = row["total_study_days"]

    if last_date == today_str:
        # Already studied today — no change to streak
        pass
    else:
        yesterday_utc = (datetime.utcnow() - timedelta(days=1)).date()
        yesterday_str = str(yesterday_utc)
        if last_date == yesterday_str:
            # Consecutive day — increment streak
            new_streak = current_streak + 1
        else:
            # Gap detected — check for streak freeze token to protect streak
            freeze_tokens = row["streak_freeze_tokens"]
            if freeze_tokens > 0 and current_streak > 0:
                # Consume one freeze token to protect the streak
                new_streak = current_streak
                new_longest = longest_streak
                conn.execute(
                    """
                    UPDATE study_streaks
                    SET last_study_date = ?,
                        streak_freeze_tokens = streak_freeze_tokens - 1,
                        updated_at = datetime('now')
                    WHERE user_id = ?
                    """,
                    (yesterday_str, user_id),
                )
                return  # streak preserved with freeze — don't write the reset below
            else:
                # No freeze available — reset streak
                new_streak = 1

        new_longest = max(longest_streak, new_streak)
        new_total = total_days + 1

        conn.execute(
            """
            UPDATE study_streaks
            SET current_streak = ?,
                longest_streak = ?,
                last_study_date = ?,
                total_study_days = ?,
                updated_at = datetime('now')
            WHERE user_id = ?
            """,
            (new_streak, new_longest, today_str, new_total, user_id),
        )


def _check_and_award_badges(conn, user_id: str, session_type: str = None,
                             exam_score_percent: float = None):
    """
    Check badge conditions and insert any newly earned achievements.
    Safe to call multiple times — badges are unique (user_id, badge_key).
    """
    earned = []

    # ── first_session: any study activity ──────────────────────────────────
    cur = conn.execute(
        "SELECT 1 FROM achievements WHERE user_id = ? AND badge_key = 'first_session'",
        (user_id,)
    )
    if not cur.fetchone():
        conn.execute(
            """
            INSERT OR IGNORE INTO achievements (user_id, badge_key, badge_name, description)
            VALUES (?, 'first_session', ?, ?)
            """,
            (user_id, BADGE_DEFINITIONS["first_session"]["badge_name"],
             BADGE_DEFINITIONS["first_session"]["description"]),
        )
        earned.append("first_session")

    # ── streak badges ───────────────────────────────────────────────────────
    cur = conn.execute(
        "SELECT current_streak FROM study_streaks WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    streak = row["current_streak"] if row else 0

    for badge_key in ["streak_3", "streak_7", "streak_30"]:
        threshold = int(badge_key.split("_")[1])
        if streak >= threshold:
            cur = conn.execute(
                "SELECT 1 FROM achievements WHERE user_id = ? AND badge_key = ?",
                (user_id, badge_key),
            )
            if not cur.fetchone():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO achievements
                        (user_id, badge_key, badge_name, description)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, badge_key,
                     BADGE_DEFINITIONS[badge_key]["badge_name"],
                     BADGE_DEFINITIONS[badge_key]["description"]),
                )
                earned.append(badge_key)

    # ── perfect_exam ─────────────────────────────────────────────────────────
    if exam_score_percent is not None and exam_score_percent == 100.0:
        cur = conn.execute(
            "SELECT 1 FROM achievements WHERE user_id = ? AND badge_key = 'perfect_exam'",
            (user_id,)
        )
        if not cur.fetchone():
            conn.execute(
                """
                INSERT OR IGNORE INTO achievements
                    (user_id, badge_key, badge_name, description)
                VALUES (?, 'perfect_exam', ?, ?)
                """,
                (user_id,
                 BADGE_DEFINITIONS["perfect_exam"]["badge_name"],
                 BADGE_DEFINITIONS["perfect_exam"]["description"]),
            )
            earned.append("perfect_exam")

    # ── focus_drill ─────────────────────────────────────────────────────────
    if session_type == "focus":
        cur = conn.execute(
            "SELECT 1 FROM achievements WHERE user_id = ? AND badge_key = 'focus_drill'",
            (user_id,)
        )
        if not cur.fetchone():
            conn.execute(
                """
                INSERT OR IGNORE INTO achievements
                    (user_id, badge_key, badge_name, description)
                VALUES (?, 'focus_drill', ?, ?)
                """,
                (user_id,
                 BADGE_DEFINITIONS["focus_drill"]["badge_name"],
                 BADGE_DEFINITIONS["focus_drill"]["description"]),
            )
            earned.append("focus_drill")

    # ── all_topics_attempted ────────────────────────────────────────────────
    cur = conn.execute(
        "SELECT 1 FROM achievements WHERE user_id = ? AND badge_key = 'all_topics_attempted'",
        (user_id,)
    )
    if not cur.fetchone():
        cur = conn.execute("SELECT COUNT(*) as total_topics FROM topics")
        total_topics = cur.fetchone()["total_topics"]
        cur = conn.execute(
            """
            SELECT COUNT(DISTINCT q.topic_id) AS attempted_topics
            FROM exam_answers ea
            JOIN exam_sessions es ON es.id = ea.exam_session_id
            JOIN questions q ON q.id = ea.question_id
            WHERE es.user_id = ?
            """,
            (user_id,)
        )
        attempted = cur.fetchone()["attempted_topics"] or 0
        if attempted >= total_topics:
            conn.execute(
                """
                INSERT OR IGNORE INTO achievements
                    (user_id, badge_key, badge_name, description)
                VALUES (?, 'all_topics_attempted', ?, ?)
                """,
                (user_id,
                 BADGE_DEFINITIONS["all_topics_attempted"]["badge_name"],
                 BADGE_DEFINITIONS["all_topics_attempted"]["description"]),
            )
            earned.append("all_topics_attempted")

    # ── volume badges (50 / 100 / 500 questions answered) ───────────────────
    cur = conn.execute(
        "SELECT COUNT(*) as cnt FROM exam_answers WHERE user_id = ?",
        (user_id,)
    )
    exam_q = cur.fetchone()["cnt"] or 0
    cur = conn.execute(
        "SELECT COUNT(*) as cnt FROM review_logs WHERE user_id = ?",
        (user_id,)
    )
    review_q = cur.fetchone()["cnt"] or 0
    total_q = exam_q + review_q
    for thresh in [50, 100, 500]:
        key = f"volume_{thresh}"
        if total_q >= thresh:
            cur = conn.execute(
                "SELECT 1 FROM achievements WHERE user_id = ? AND badge_key = ?",
                (user_id, key),
            )
            if not cur.fetchone():
                conn.execute(
                    "INSERT OR IGNORE INTO achievements (user_id, badge_key, badge_name, description) VALUES (?, ?, ?, ?)",
                    (user_id, key, BADGE_DEFINITIONS[key]["badge_name"], BADGE_DEFINITIONS[key]["description"]),
                )
                earned.append(key)

    # ── accuracy badges (80%+ and 90%+ average) ──────────────────────────────
    # exam answers (need exam_session to get user_id)
    cur = conn.execute(
        "SELECT COUNT(ea.id) as total, SUM(ea.is_correct) as correct FROM exam_answers ea JOIN exam_sessions es ON es.id = ea.exam_session_id WHERE es.user_id = ?",
        (user_id,)
    )
    exam_row = cur.fetchone()
    exam_correct = exam_row["correct"] or 0
    exam_total = exam_row["total"] or 0
    cur = conn.execute(
        "SELECT COUNT(*) as total, SUM(CASE WHEN quality >= 3 THEN 1 ELSE 0 END) as correct FROM review_logs WHERE user_id = ?",
        (user_id,)
    )
    review_row = cur.fetchone()
    review_correct = review_row["correct"] or 0
    review_total = review_row["total"] or 0
    total_correct = exam_correct + review_correct
    total_attempts = exam_total + review_total
    avg_acc = round(total_correct / total_attempts * 100, 1) if total_attempts > 0 else None
    for threshold in [80.0, 90.0]:
        key = f"accuracy_{int(threshold)}"
        if avg_acc is not None and avg_acc >= threshold:
            cur = conn.execute(
                "SELECT 1 FROM achievements WHERE user_id = ? AND badge_key = ?",
                (user_id, key),
            )
            if not cur.fetchone():
                conn.execute(
                    "INSERT OR IGNORE INTO achievements (user_id, badge_key, badge_name, description) VALUES (?, ?, ?, ?)",
                    (user_id, key, BADGE_DEFINITIONS[key]["badge_name"], BADGE_DEFINITIONS[key]["description"]),
                )
                earned.append(key)

    # ── exam milestone badges ───────────────────────────────────────────────
    cur = conn.execute(
        "SELECT COUNT(*) as passed FROM exam_sessions WHERE user_id = ? AND passed = 1",
        (user_id,)
    )
    passed_count = cur.fetchone()["passed"] or 0
    for thresh, key in [(1, "first_exam_passed"), (5, "exams_5_passed"), (10, "exams_10_passed")]:
        if passed_count >= thresh:
            cur = conn.execute(
                "SELECT 1 FROM achievements WHERE user_id = ? AND badge_key = ?",
                (user_id, key),
            )
            if not cur.fetchone():
                conn.execute(
                    "INSERT OR IGNORE INTO achievements (user_id, badge_key, badge_name, description) VALUES (?, ?, ?, ?)",
                    (user_id, key, BADGE_DEFINITIONS[key]["badge_name"], BADGE_DEFINITIONS[key]["description"]),
                )
                earned.append(key)

    # ── focus_10: 10 focus sessions completed ────────────────────────────────
    cur = conn.execute(
        "SELECT COUNT(*) as focus_count FROM study_sessions WHERE user_id = ? AND type = 'focus'",
        (user_id,)
    )
    row = cur.fetchone()
    focus_count = row["focus_count"] if row else 0
    if focus_count >= 10:
        cur = conn.execute(
            "SELECT 1 FROM achievements WHERE user_id = ? AND badge_key = 'focus_10'",
            (user_id,)
        )
        if not cur.fetchone():
            conn.execute(
                "INSERT OR IGNORE INTO achievements (user_id, badge_key, badge_name, description) VALUES (?, ?, ?, ?)",
                (user_id, "focus_10", BADGE_DEFINITIONS["focus_10"]["badge_name"], BADGE_DEFINITIONS["focus_10"]["description"]),
            )
            earned.append("focus_10")

    return earned


# ─────────────────────────────────────────────────────────────────────────────
# Streaks & Gamification Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/study/streaks/{user_id}")
def study_streaks(user_id: str, _token: dict = Depends(get_current_user)):
    """
    Returns current/longest streak, last study date,
    study calendar (last 30 days with activity flags),
    and daily_goal_progress.
    """
    conn = get_connection()

    # Get streak row
    cur = conn.execute(
        "SELECT * FROM study_streaks WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        return {
            "user_id": user_id,
            "current_streak": 0,
            "longest_streak": 0,
            "last_study_date": None,
            "total_study_days": 0,
            "questions_per_day": 10,
            "study_calendar": [],
            "daily_goal_progress": {
                "target": 10,
                "answered_today": 0,
                "percent": 0,
            },
        }

    questions_per_day = row["questions_per_day"]

    # Build 30-day study calendar (UTC, matching submission pipeline)
    today_utc = datetime.utcnow().date()
    today = today_utc
    calendar_days = []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        d_str = str(d)
        cur = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM (
                SELECT date(completed_at) as day FROM exam_sessions
                WHERE user_id = ? AND status = 'completed' AND date(completed_at) = ?
                UNION ALL
                SELECT date(reviewed_at) as day FROM review_logs
                WHERE user_id = ? AND date(reviewed_at) = ?
            )
            """,
            (user_id, d_str, user_id, d_str),
        )
        cnt = cur.fetchone()["cnt"] or 0
        calendar_days.append({
            "date": d_str,
            "active": cnt > 0,
            "sessions_count": cnt,
        })

    # Today's question count
    today_str = str(today)
    cur = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM (
            SELECT 1 FROM exam_answers ea
            JOIN exam_sessions es ON es.id = ea.exam_session_id
            WHERE es.user_id = ? AND date(ea.answered_at) = ?
            UNION ALL
            SELECT 1 FROM review_logs WHERE user_id = ? AND date(reviewed_at) = ?
        )
        """,
        (user_id, today_str, user_id, today_str),
    )
    answered_today = cur.fetchone()["cnt"] or 0

    daily_progress = {
        "target": questions_per_day,
        "answered_today": answered_today,
        "percent": min(100, round(answered_today / questions_per_day * 100, 1)) if questions_per_day > 0 else 0,
    }

    # Streak-loss warning logic
    streak_at_risk = False
    streak_broken = False
    days_missed = 0
    if row["current_streak"] > 0 and row["last_study_date"]:
        last_date = datetime.strptime(row["last_study_date"], "%Y-%m-%d").date()
        yesterday = today - timedelta(days=1)
        if last_date == yesterday:
            streak_at_risk = True
            days_missed = 1
        elif last_date < yesterday:
            streak_broken = True
            days_missed = (yesterday - last_date).days

    # Derive streak_status enum
    if streak_broken:
        streak_status = "broken"
    elif streak_at_risk:
        streak_status = "at_risk"
    else:
        streak_status = "active"

    conn.close()

    return {
        "user_id": user_id,
        "current_streak": row["current_streak"],
        "longest_streak": row["longest_streak"],
        "last_study_date": row["last_study_date"],
        "total_study_days": row["total_study_days"],
        "questions_per_day": questions_per_day,
        "study_calendar": calendar_days,
        "daily_goal_progress": daily_progress,
        "streak_at_risk": streak_at_risk,
        "streak_broken": streak_broken,
        "streak_status": streak_status,
        "days_missed": days_missed,
        "streak_freeze_tokens": row["streak_freeze_tokens"],
    }


@app.put("/api/study/streaks/{user_id}/daily-goal")
def update_daily_goal(user_id: str, body: DailyGoalRequest, _token: dict = Depends(get_current_user)):
    """
    Set the user's daily question target (1–100).
    """
    goal = body.goal
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO study_streaks (user_id, questions_per_day, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(user_id) DO UPDATE SET
            questions_per_day = excluded.questions_per_day,
            updated_at = datetime('now')
        """,
        (user_id, goal),
    )
    conn.commit()
    conn.close()
    return {"user_id": user_id, "questions_per_day": goal, "updated": True}


@app.post("/api/study/streaks/{user_id}/use-freeze")
def use_streak_freeze(user_id: str, _token: dict = Depends(get_current_user)):
    """
    Consume one streak freeze token to protect a streak that is at_risk or broken.
    Resets last_study_date to yesterday (or today if already studied today),
    restores streak_status to 'active', and decrements streak_freeze_tokens.
    Returns 400 if no tokens remain.
    """
    conn = get_connection()
    cur = conn.execute(
        "SELECT * FROM study_streaks WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Streak record not found.")

    tokens = row["streak_freeze_tokens"]
    if tokens <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="No streak freeze tokens remaining.")

    # Reset last_study_date to yesterday so streak won't be broken
    yesterday = (datetime.utcnow() - timedelta(days=1)).date()
    yesterday_str = str(yesterday)
    today_str = str(datetime.utcnow().date())

    # If already active and last_study_date is today, still consume token (edge case)
    # The intent is to protect the streak going forward
    last_date = row["last_study_date"]
    if last_date == today_str:
        # Already studied today — freeze still protects tomorrow
        pass
    else:
        # Set last_study_date to yesterday so gap-day check passes
        pass  # keep yesterday_str

    new_tokens = tokens - 1
    conn.execute(
        """
        UPDATE study_streaks
        SET last_study_date = ?,
            current_streak = COALESCE(current_streak, 0) + 1,
            longest_streak = MAX(COALESCE(longest_streak, 0), current_streak + 1),
            streak_freeze_tokens = ?,
            updated_at = datetime('now')
        WHERE user_id = ?
        """,
        (yesterday_str, new_tokens, user_id),
    )
    conn.commit()
    conn.close()

    return {"used": True, "tokens_remaining": new_tokens}


@app.get("/api/study/achievements/{user_id}")
def study_achievements(user_id: str, _token: dict = Depends(get_current_user)):
    """
    Returns all badge definitions with earned_at for earned badges,
    and earned=false for unearned badges.
    """
    conn = get_connection()

    cur = conn.execute(
        "SELECT badge_key, badge_name, description, earned_at \
        FROM achievements WHERE user_id = ? ORDER BY earned_at DESC",
        (user_id,)
    )
    earned_rows = {r["badge_key"]: dict(r) for r in cur.fetchall()}
    conn.close()

    result = []
    for key, meta in BADGE_DEFINITIONS.items():
        if key in earned_rows:
            row = earned_rows[key]
            result.append({
                "badge_key": key,
                "badge_name": row["badge_name"],
                "description": row["description"],
                "earned": True,
                "earned_at": row["earned_at"],
            })
        else:
            result.append({
                "badge_key": key,
                "badge_name": meta["badge_name"],
                "description": meta["description"],
                "earned": False,
                "earned_at": None,
            })

    return {"user_id": user_id, "achievements": result}


@app.post("/api/study/reset-progress/{user_id}")
def reset_study_progress(user_id: str, _token: dict = Depends(get_current_user)):
    """
    Clears all study history and SM-2 progress for a user but keeps the account.
    Deletes: user_progress, review_logs, exam_answers, exam_sessions, achievements.
    Resets: study_streak to 0 days, last_study_date to null.
    Useful for demos that need a clean slate.
    """
    conn = get_connection()
    cur = conn.cursor()

    # Verify user exists
    cur.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    # Clear study data
    cur.execute("DELETE FROM user_progress WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM review_logs WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM exam_answers WHERE exam_session_id IN (SELECT id FROM exam_sessions WHERE user_id = ?)", (user_id,))
    cur.execute("DELETE FROM exam_sessions WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM achievements WHERE user_id = ?", (user_id,))

    # Reset streak to zero (keep the row so the user still has a streak record)
    cur.execute(
        """UPDATE study_streaks
           SET current_streak = 0, longest_streak = 0,
               last_study_date = NULL, total_study_days = 0
           WHERE user_id = ?""",
        (user_id,)
    )

    conn.commit()
    conn.close()
    _logger.info(f"Study progress reset for user {user_id}")
    return {"user_id": user_id, "reset": True,
            "message": "All study progress cleared. Account preserved."}


@app.get("/api/study/daily-progress/{user_id}")
def study_daily_progress(user_id: str, _token: dict = Depends(get_current_user)):
    """
    Returns today's questions answered vs daily goal,
    and minutes studied today.
    """
    conn = get_connection()
    today_utc = datetime.utcnow().date()
    today_str = str(today_utc)

    # Questions answered today
    cur = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM (
            SELECT 1 FROM exam_answers ea
            JOIN exam_sessions es ON es.id = ea.exam_session_id
            WHERE es.user_id = ? AND date(ea.answered_at) = ?
            UNION ALL
            SELECT 1 FROM review_logs WHERE user_id = ? AND date(reviewed_at) = ?
        )
        """,
        (user_id, today_str, user_id, today_str),
    )
    questions_answered = cur.fetchone()["cnt"] or 0

    # Study time (from exam session time_spent + estimated review time)
    cur = conn.execute(
        """
        SELECT SUM(time_spent_seconds) as total_secs
        FROM exam_sessions
        WHERE user_id = ? AND status = 'completed' AND date(completed_at) = ?
        """,
        (user_id, today_str),
    )
    exam_secs = cur.fetchone()["total_secs"] or 0

    # Estimate review time: 30 seconds per review log entry
    cur = conn.execute(
        "SELECT COUNT(*) as cnt FROM review_logs \
        WHERE user_id = ? AND date(reviewed_at) = ?",
        (user_id, today_str),
    )
    review_count = cur.fetchone()["cnt"] or 0
    review_secs = review_count * 30

    total_secs = exam_secs + review_secs
    minutes_studied = round(total_secs / 60, 1)

    # Daily goal
    cur = conn.execute(
        "SELECT questions_per_day FROM study_streaks WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    daily_goal = row["questions_per_day"] if row else 10

    conn.close()

    return {
        "user_id": user_id,
        "date": today_str,
        "questions_answered": questions_answered,
        "daily_goal": daily_goal,
        "goal_percent": min(100, round(questions_answered / daily_goal * 100, 1)) if daily_goal > 0 else 0,
        "minutes_studied": minutes_studied,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Weekly Progress Digest + Performance Analytics
# ─────────────────────────────────────────────────────────────────────────────

def _week_range(dt: date):
    """Return (week_start Monday, week_end Sunday) for a given date."""
    monday = dt - timedelta(days=dt.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


@app.get("/api/study/weekly/{user_id}")
def study_weekly(user_id: str, _token: dict = Depends(get_current_user)):
    """
    This week's study summary: questions answered, sessions completed,
    streak status at end of week, accuracy vs last week, topics studied.
    """
    conn = get_connection()
    today_utc = datetime.utcnow().date()
    this_mon, this_sun = _week_range(today_utc)
    last_mon = this_mon - timedelta(days=7)
    last_sun = this_mon - timedelta(days=1)

    def week_question_count(conn, user_id, mon, sun):
        cur = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM (
                SELECT 1 FROM exam_answers ea
                JOIN exam_sessions es ON es.id = ea.exam_session_id
                WHERE es.user_id = ?
                  AND date(ea.answered_at) >= ?
                  AND date(ea.answered_at) <= ?
                UNION ALL
                SELECT 1 FROM review_logs
                WHERE user_id = ?
                  AND date(reviewed_at) >= ?
                  AND date(reviewed_at) <= ?
            )
            """,
            (user_id, str(mon), str(sun), user_id, str(mon), str(sun)),
        )
        return cur.fetchone()["cnt"] or 0

    def week_accuracy(conn, user_id, mon, sun):
        cur = conn.execute(
            """
            SELECT
                SUM(is_correct) as correct,
                COUNT(*) as total
            FROM (
                SELECT ea.is_correct FROM exam_answers ea
                JOIN exam_sessions es ON es.id = ea.exam_session_id
                WHERE es.user_id = ?
                  AND date(ea.answered_at) >= ?
                  AND date(ea.answered_at) <= ?
                UNION ALL
                SELECT CASE WHEN quality >= 3 THEN 1 ELSE 0 END as is_correct
                FROM review_logs
                WHERE user_id = ?
                  AND date(reviewed_at) >= ?
                  AND date(reviewed_at) <= ?
            )
            """,
            (user_id, str(mon), str(sun), user_id, str(mon), str(sun)),
        )
        row = cur.fetchone()
        if not row or row["total"] == 0:
            return None
        return round(row["correct"] / row["total"] * 100, 1)

    def week_sessions(conn, user_id, mon, sun):
        cur = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM (
                SELECT 1 FROM exam_sessions
                WHERE user_id = ? AND status = 'completed'
                  AND date(completed_at) >= ? AND date(completed_at) <= ?
                UNION ALL
                SELECT 1 FROM review_logs
                WHERE user_id = ?
                  AND date(reviewed_at) >= ? AND date(reviewed_at) <= ?
            )
            """,
            (user_id, str(mon), str(sun), user_id, str(mon), str(sun)),
        )
        return cur.fetchone()["cnt"] or 0

    def week_topics(conn, user_id, mon, sun):
        cur = conn.execute(
            """
            SELECT DISTINCT t.id, t.name, t.slug FROM topics t
            WHERE t.id IN (
                SELECT DISTINCT q.topic_id FROM exam_answers ea
                JOIN exam_sessions es ON es.id = ea.exam_session_id
                JOIN questions q ON q.id = ea.question_id
                WHERE es.user_id = ?
                  AND date(ea.answered_at) >= ?
                  AND date(ea.answered_at) <= ?
                UNION
                SELECT DISTINCT q.topic_id FROM review_logs rl
                JOIN questions q ON q.id = rl.question_id
                WHERE rl.user_id = ?
                  AND date(rl.reviewed_at) >= ?
                  AND date(rl.reviewed_at) <= ?
            )
            ORDER BY t.name
            """,
            (user_id, str(mon), str(sun), user_id, str(mon), str(sun)),
        )
        return [{"id": r["id"], "name": r["name"], "slug": r["slug"]} for r in cur.fetchall()]

    # This week
    questions_this_week = week_question_count(conn, user_id, this_mon, this_sun)
    sessions_this_week = week_sessions(conn, user_id, this_mon, this_sun)
    accuracy_this_week = week_accuracy(conn, user_id, this_mon, this_sun)
    topics_this_week = week_topics(conn, user_id, this_mon, this_sun)

    # Last week
    questions_last_week = week_question_count(conn, user_id, last_mon, last_sun)
    accuracy_last_week = week_accuracy(conn, user_id, last_mon, last_sun)

    # Streak at end of this week (check if last_study_date within this week range)
    cur = conn.execute(
        "SELECT current_streak, longest_streak, last_study_date FROM study_streaks WHERE user_id = ?",
        (user_id,)
    )
    streak_row = cur.fetchone()
    if streak_row and streak_row["last_study_date"]:
        last_date = datetime.strptime(streak_row["last_study_date"], "%Y-%m-%d").date()
        streak_this_week = streak_row["current_streak"] if last_date >= this_mon else 0
    else:
        streak_this_week = 0

    conn.close()

    return {
        "user_id": user_id,
        "week_start": str(this_mon),
        "week_end": str(this_sun),
        "questions_answered": questions_this_week,
        "sessions_completed": sessions_this_week,
        "streak_at_week_end": streak_this_week,
        "accuracy_pct": accuracy_this_week,
        "accuracy_vs_last_week": (
            round(accuracy_this_week - accuracy_last_week, 1)
            if accuracy_this_week is not None and accuracy_last_week is not None
            else None
        ),
        "questions_last_week": questions_last_week,
        "accuracy_last_week_pct": accuracy_last_week,
        "topics_studied": topics_this_week,
    }


@app.get("/api/study/topics/{user_id}/trends")
def study_topic_trends(user_id: str, _token: dict = Depends(get_current_user)):
    """
    Per-topic performance trends:
    - current accuracy (all-time)
    - best accuracy (highest single-session accuracy)
    - attempts count
    - trend direction: improving / declining / stable
      (last-3-session avg vs overall accuracy)
    """
    conn = get_connection()

    # Get per-topic overall accuracy and attempts from review_logs
    cur = conn.execute(
        """
        SELECT
            q.topic_id,
            t.name as topic_name,
            t.slug as topic_slug,
            COUNT(*) as attempts,
            SUM(CASE WHEN rl.quality >= 3 THEN 1 ELSE 0 END) as correct
        FROM review_logs rl
        JOIN questions q ON q.id = rl.question_id
        JOIN topics t ON t.id = q.topic_id
        WHERE rl.user_id = ?
        GROUP BY q.topic_id
        ORDER BY t.name
        """,
        (user_id,)
    )
    topic_rows = cur.fetchall()

    trends = []
    for row in topic_rows:
        topic_id = row["topic_id"]
        overall_acc = (
            round(row["correct"] / row["attempts"] * 100, 1)
            if row["attempts"] > 0 else None
        )

        # Best accuracy: best single-session accuracy for this topic
        cur2 = conn.execute(
            """
            SELECT
                COUNT(*) as sess_attempts,
                SUM(CASE WHEN quality >= 3 THEN 1 ELSE 0 END) as sess_correct
            FROM (
                SELECT date(rl.reviewed_at) as sess_day, rl.quality
                FROM review_logs rl
                WHERE rl.user_id = ?
                  AND rl.question_id IN (
                      SELECT q.id FROM questions q WHERE q.topic_id = ?
                  )
            )
            GROUP BY sess_day
            ORDER BY (CAST(SUM(CASE WHEN quality >= 3 THEN 1 ELSE 0 END) AS REAL) /
                      NULLIF(COUNT(*), 0)) DESC
            LIMIT 1
            """,
            (user_id, topic_id)
        )
        best_row = cur2.fetchone()
        best_acc = (
            round(best_row["sess_correct"] / best_row["sess_attempts"] * 100, 1)
            if best_row and best_row["sess_attempts"] > 0 else None
        )

        # Trend: last 3 sessions accuracy vs overall
        cur3 = conn.execute(
            """
            SELECT
                CAST(SUM(CASE WHEN quality >= 3 THEN 1 ELSE 0 END) AS REAL) /
                     NULLIF(COUNT(*), 0) * 100 as sess_acc
            FROM (
                SELECT date(rl.reviewed_at) as sess_day, rl.quality
                FROM review_logs rl
                WHERE rl.user_id = ?
                  AND rl.question_id IN (
                      SELECT q.id FROM questions q WHERE q.topic_id = ?
                  )
            )
            GROUP BY sess_day
            ORDER BY sess_day DESC
            LIMIT 3
            """,
            (user_id, topic_id)
        )
        last_3 = [r["sess_acc"] for r in cur3.fetchall() if r["sess_acc"] is not None]

        if last_3 and overall_acc is not None and len(last_3) >= 1:
            avg_last_3 = sum(last_3) / len(last_3)
            if avg_last_3 > overall_acc + 2:
                trend = "improving"
            elif avg_last_3 < overall_acc - 2:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "stable"

        trends.append({
            "topic_id": topic_id,
            "topic_name": row["topic_name"],
            "topic_slug": row["topic_slug"],
            "current_accuracy_pct": overall_acc,
            "best_accuracy_pct": best_acc,
            "attempts_count": row["attempts"],
            "trend": trend,
        })

    conn.close()
    return {"user_id": user_id, "topics": trends}


# ─────────────────────────────────────────────────────────────────────────────
# Auth Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/auth/register")
def register(body: RegisterRequest):
    """
    Register a new user. Creates user + issues JWT access token.
    """
    import json as _json
    conn = get_connection()
    cur = conn.cursor()

    # Check if email already exists
    cur.execute("SELECT id FROM users WHERE email = ?", (body.email,))
    if cur.fetchone():
        conn.close()
        raise HTTPException(400, "Email already registered")

    user_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    cur.execute(
        """
        INSERT INTO users (id, email, password_hash, display_name, timezone, is_premium, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'Asia/Tokyo', 0, ?, ?)
        """,
        (user_id, body.email, hash_password(body.password), body.display_name, now, now),
    )

    # Initialize study_streaks for this user
    cur.execute(
        """
        INSERT OR IGNORE INTO study_streaks (user_id, current_streak, longest_streak, last_study_date, total_study_days, questions_per_day, streak_freeze_tokens, updated_at)
        VALUES (?, 0, 0, NULL, 0, 10, 1, ?)
        """,
        (user_id, now),
    )

    conn.commit()
    conn.close()

    token = create_access_token(user_id)
    return {"access_token": token, "token_type": "bearer", "user_id": user_id}


@app.post("/api/auth/login")
def login(body: LoginRequest):
    """
    Login with email + password. Returns JWT access token.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, email, display_name, password_hash FROM users WHERE email = ?", (body.email,))
    row = cur.fetchone()
    conn.close()

    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    token = create_access_token(row["id"])
    return {"access_token": token, "token_type": "bearer", "user_id": row["id"]}


@app.get("/api/study/profile/{user_id}")
def get_profile(user_id: str, token_payload: dict = Depends(get_current_user)):
    """
    Return user profile: display_name, email, member_since, total_study_days, is_premium.
    Requires valid JWT.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT id, email, display_name, is_premium, created_at, timezone
           FROM users WHERE id = ?""",
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "User not found")

    # total_study_days from study_streaks
    cur.execute(
        "SELECT total_study_days FROM study_streaks WHERE user_id = ?",
        (user_id,),
    )
    streak_row = cur.fetchone()
    total_study_days = streak_row["total_study_days"] if streak_row else 0

    conn.close()

    return {
        "user_id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "member_since": row["created_at"],
        "total_study_days": total_study_days,
        "is_premium": bool(row["is_premium"]),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Session History
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/study/history/{user_id}")
def get_study_history(user_id: str, limit: int = 50, _token: dict = Depends(get_current_user)):
    """
    Returns the last N study/exam/focus sessions for a user.
    Each entry: session_id, type, date, score_pct, correct_count, total_count, duration_minutes.
    Union of exam_sessions (exam), study_sessions (focus), and study_sessions (review).
    """
    conn = get_connection()

    # ── 1. Exam sessions ──────────────────────────────────────────────────
    exam_rows = conn.execute(
        """
        SELECT
            id                          AS session_id,
            'exam'                      AS type,
            COALESCE(completed_at, created_at) AS date,
            COALESCE(score_percent, 0.0) AS score_pct,
            correct_count               AS correct_count,
            total_questions             AS total_count,
            ROUND(time_spent_seconds / 60.0, 1) AS duration_minutes
        FROM exam_sessions
        WHERE user_id = ? AND status = 'completed'
        """,
        (user_id,)
    ).fetchall()

    # ── 2. Focus sessions ─────────────────────────────────────────────────
    # answered_at on exam_answers rows gives us timestamps per answer
    focus_rows_raw = conn.execute(
        """
        SELECT
            ss.id                                        AS session_id,
            'focus'                                     AS type,
            ss.created_at                                AS date,
            COALESCE(
                ROUND(100.0 * SUM(ea.is_correct) / COUNT(ea.id), 1),
                0.0
            )                                            AS score_pct,
            SUM(ea.is_correct)                          AS correct_count,
            COUNT(ea.id)                                AS total_count,
            COALESCE(
                ROUND(
                    (JULIANDAY(MAX(ea.answered_at)) - JULIANDAY(MIN(ea.answered_at))) * 1440.0,
                1),
                NULL
            )                                            AS duration_minutes
        FROM study_sessions ss
        LEFT JOIN exam_answers ea ON ea.exam_session_id = ss.id
        WHERE ss.user_id = ? AND ss.type = 'focus' AND ss.status = 'completed'
        GROUP BY ss.id
        """,
        (user_id,)
    ).fetchall()

    # ── 3. Review sessions ────────────────────────────────────────────────
    review_rows_raw = conn.execute(
        """
        SELECT
            ss.id                                        AS session_id,
            'review'                                    AS type,
            MAX(rl.reviewed_at)                         AS date,
            COALESCE(
                ROUND(100.0 * SUM(CASE WHEN rl.quality >= 3 THEN 1 ELSE 0 END) / COUNT(rl.id), 1),
                0.0
            )                                            AS score_pct,
            SUM(CASE WHEN rl.quality >= 3 THEN 1 ELSE 0 END) AS correct_count,
            COUNT(rl.id)                                AS total_count,
            COALESCE(
                ROUND(
                    (JULIANDAY(MAX(rl.reviewed_at)) - JULIANDAY(MIN(rl.reviewed_at))) * 1440.0,
                1),
                NULL
            )                                            AS duration_minutes
        FROM study_sessions ss
        LEFT JOIN review_logs rl ON rl.user_id = ss.user_id
        WHERE ss.user_id = ? AND ss.type = 'review' AND ss.status = 'completed'
        GROUP BY ss.id
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    # Combine, sort by date DESC, cap at limit
    all_rows = (
        [dict(r) for r in exam_rows]
        + [dict(r) for r in focus_rows_raw]
        + [dict(r) for r in review_rows_raw]
    )
    all_rows.sort(key=lambda r: r["date"] or "", reverse=True)
    all_rows = all_rows[:limit]

    return {"sessions": all_rows, "total": len(all_rows)}


# ─────────────────────────────────────────────────────────────────────────────
# Personalized Recommendations
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/study/recommendations/{user_id}")
def get_recommendations(user_id: str, _token: dict = Depends(get_current_user)):
    """
    Returns up to 3 personalized study recommendations.
    Based on: lowest-accuracy topics, stale topics (7+ days), at-risk streak with no reviews due.
    Falls back to generic suggestions when history is thin.
    """
    conn = get_connection()
    recommendations = []
    added_topics = set()

    # ── 1. Lowest-accuracy topic ──────────────────────────────────────────
    cur = conn.execute(
        """
        SELECT ea.topic_id, t.name,
               ROUND(100.0 * SUM(ea.is_correct) / COUNT(ea.id), 1) AS acc
        FROM exam_answers ea
        JOIN exam_sessions es ON es.id = ea.exam_session_id
        JOIN topics t ON t.id = ea.topic_id
        WHERE es.user_id = ? AND es.status = 'completed'
        GROUP BY ea.topic_id
        HAVING acc < 75
        ORDER BY acc ASC
        LIMIT 1
        """,
        (user_id,)
    )
    weakest = cur.fetchone()
    if weakest and weakest["topic_id"] not in added_topics:
        recommendations.append({
            "priority": "high",
            "topic_name": weakest["name"],
            "reason": f"Lowest exam accuracy at {weakest['acc']}% — needs targeted practice.",
            "recommended_action": "focus"
        })
        added_topics.add(weakest["topic_id"])

    # ── 2. Stale topic (not studied in 7+ days) ───────────────────────────
    cur = conn.execute(
        """
        SELECT DISTINCT q.topic_id, t.name, MAX(ea.answered_at) AS last_studied
        FROM exam_answers ea
        JOIN exam_sessions es ON es.id = ea.exam_session_id
        JOIN questions q ON q.id = ea.question_id
        JOIN topics t ON t.id = q.topic_id
        WHERE es.user_id = ?
        GROUP BY q.topic_id
        HAVING last_studied < datetime('now', '-7 days') OR last_studied IS NULL
        LIMIT 1
        """,
        (user_id,)
    )
    stale = cur.fetchone()
    if stale and stale["topic_id"] not in added_topics:
        recommendations.append({
            "priority": "medium",
            "topic_name": stale["name"],
            "reason": f"Not reviewed in over 7 days — content may be fading.",
            "recommended_action": "review"
        })
        added_topics.add(stale["topic_id"])

    # ── 3. At-risk streak with no reviews due today ────────────────────────
    cur = conn.execute(
        """
        SELECT ss.current_streak, ss.last_study_date,
               (SELECT COUNT(*) FROM user_progress up
                WHERE up.user_id = ss.user_id AND up.next_review_date <= date('now')) AS due_count
        FROM study_streaks ss
        WHERE ss.user_id = ?
        """,
        (user_id,)
    )
    streak_row = cur.fetchone()
    if streak_row:
        last = streak_row["last_study_date"]
        today = datetime.utcnow().strftime("%Y-%m-%d")
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        if last == today:
            streak_status = "active"
        elif last == yesterday:
            streak_status = "at_risk"
        else:
            streak_status = "broken"
    else:
        streak_status = "broken"
        streak_row = {"current_streak": 0, "due_count": 0, "last_study_date": None}
    if streak_status == "at_risk" and streak_row["due_count"] == 0:
        recommendations.append({
            "priority": "high",
            "topic_name": "Streak Protection",
            "reason": f"🔥 {streak_row['current_streak']}-day streak is at risk and no reviews are due. Complete any session today!",
            "recommended_action": "any"
        })

    # ── Fallback if history is too thin ───────────────────────────────────
    cur.execute("SELECT COUNT(*) as cnt FROM exam_sessions WHERE user_id = ? AND status = 'completed'", (user_id,))
    exam_count = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM review_logs WHERE user_id = ?", (user_id,))
    review_count = cur.fetchone()["cnt"]

    if exam_count < 2 and review_count < 3:
        # Very thin history — suggest starting with exam or review
        if len([r for r in recommendations if r["recommended_action"] == "exam"]) == 0:
            recommendations.append({
                "priority": "medium",
                "topic_name": "Getting Started",
                "reason": "Complete your first Exam Simulation to get personalized recommendations.",
                "recommended_action": "exam"
            })
        elif len([r for r in recommendations if r["recommended_action"] == "review"]) == 0:
            recommendations.append({
                "priority": "medium",
                "topic_name": "Build Your Foundation",
                "reason": "Try a Review Session to generate SM-2 cards and track your memory.",
                "recommended_action": "review"
            })

    conn.close()
    return {"recommendations": recommendations[:3]}


# ─────────────────────────────────────────────────────────────────────────────
# Study Calendar + Upcoming Reviews
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/study/calendar/{user_id}")
def get_study_calendar(user_id: str, _token: dict = Depends(get_current_user)):
    """
    Returns:
    - past_weeks: last 28 days of activity (date, had_activity, sessions_count, questions_answered)
    - upcoming: next 14 days of due cards from user_progress
    - total_due_today: count of cards due today
    """
    conn = get_connection()
    today = str(date.today())

    # ── Past 4 weeks: activity per day ─────────────────────────────────────
    past_weeks = []
    for i in range(27, -1, -1):
        day = date.today() - timedelta(days=i)
        day_str = str(day)

        # sessions on this day
        exam_count = conn.execute(
            "SELECT COUNT(*) FROM exam_sessions WHERE user_id = ? AND date(completed_at) = ?",
            (user_id, day_str)
        ).fetchone()[0] or 0

        review_count = conn.execute(
            "SELECT COUNT(*) FROM review_logs WHERE user_id = ? AND date(reviewed_at) = ?",
            (user_id, day_str)
        ).fetchone()[0] or 0

        sessions_count = exam_count + review_count

        # questions answered on this day
        questions_answered = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT ea.id FROM exam_answers ea
                JOIN exam_sessions es ON es.id = ea.exam_session_id
                WHERE es.user_id = ? AND date(ea.answered_at) = ?
                UNION ALL
                SELECT rl.id FROM review_logs rl WHERE rl.user_id = ? AND date(rl.reviewed_at) = ?
            )
            """,
            (user_id, day_str, user_id, day_str)
        ).fetchone()[0] or 0

        past_weeks.append({
            "date": day_str,
            "had_activity": sessions_count > 0,
            "sessions_count": sessions_count,
            "questions_answered": questions_answered
        })

    # ── Upcoming 14 days: cards due ─────────────────────────────────────────
    upcoming = []
    for i in range(14):
        day = date.today() + timedelta(days=i)
        day_str = str(day)
        due_count = conn.execute(
            "SELECT COUNT(*) FROM user_progress WHERE user_id = ? AND next_review_date <= ?",
            (user_id, day_str)
        ).fetchone()[0] or 0
        upcoming.append({"date": day_str, "due_count": due_count})

    # ── Total due today ─────────────────────────────────────────────────────
    total_due_today = conn.execute(
        "SELECT COUNT(*) FROM user_progress WHERE user_id = ? AND next_review_date <= ?",
        (user_id, today)
    ).fetchone()[0] or 0

    return {
        "past_weeks": past_weeks,
        "upcoming": upcoming,
        "total_due_today": total_due_today
    }


@app.get("/api/study/topics/{user_id}/due-breakdown")
def get_due_breakdown(user_id: str, _token: dict = Depends(get_current_user)):
    """
    Per-topic breakdown of cards due today.
    Returns: topic_id, topic_name, due_count.
    """
    conn = get_connection()
    today = str(date.today())
    rows = conn.execute(
        """
        SELECT t.id AS topic_id, t.name AS topic_name, COUNT(up.id) AS due_count
        FROM user_progress up
        JOIN questions q ON q.id = up.question_id
        JOIN topics t ON t.id = q.topic_id
        WHERE up.user_id = ? AND up.next_review_date <= ?
        GROUP BY t.id
        ORDER BY due_count DESC
        """,
        (user_id, today)
    ).fetchall()
    return {"topics": [dict(r) for r in rows]}


# ─────────────────────────────────────────────────────────────────────────────
# Bookmarks
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/study/bookmarks/{user_id}")
def get_bookmarks(user_id: str, _token: dict = Depends(get_current_user)):
    """Return list of bookmarked question IDs for the user."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT b.question_id, b.created_at,
               q.question_text, q.difficulty, t.name AS topic_name
        FROM bookmarks b
        JOIN questions q ON q.id = b.question_id
        JOIN topics t ON t.id = q.topic_id
        WHERE b.user_id = ?
        ORDER BY b.created_at DESC
        """,
        (user_id,)
    ).fetchall()
    conn.close()
    return {"bookmarks": [dict(r) for r in rows]}


@app.post("/api/study/bookmarks/{user_id}")
def add_bookmark(user_id: str, payload: dict = Body(...), _token: dict = Depends(get_current_user)):
    """Add a bookmark for a question."""
    question_id = payload.get("question_id")
    if not question_id:
        raise HTTPException(status_code=400, detail="question_id is required")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO bookmarks (user_id, question_id) VALUES (?, ?)",
            (user_id, question_id)
        )
        conn.commit()
    finally:
        conn.close()
    return {"added": True, "question_id": question_id}


@app.delete("/api/study/bookmarks/{user_id}/{question_id}")
def remove_bookmark(user_id: str, question_id: str, _token: dict = Depends(get_current_user)):
    """Remove a bookmark."""
    conn = get_connection()
    conn.execute(
        "DELETE FROM bookmarks WHERE user_id = ? AND question_id = ?",
        (user_id, question_id)
    )
    conn.commit()
    conn.close()
    return {"removed": True}


# ─────────────────────────────────────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/study/search")
def search_questions(
    user_id: str = Query(...),
    q: str = Query("", description="Search text"),
    topic_id: int = Query(None),
    difficulty: str = Query(None),
    _token: dict = Depends(get_current_user)
):
    """Search questions by text, topic, and/or difficulty. Max 50 results."""
    conn = get_connection()
    conditions = ["q.is_active = 1"]
    params = []

    if q:
        conditions.append("(q.question_text LIKE ? OR q.explanation LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    if topic_id is not None:
        conditions.append("q.topic_id = ?")
        params.append(topic_id)
    if difficulty:
        conditions.append("q.difficulty = ?")
        params.append(difficulty)

    query = f"""
        SELECT q.id AS question_id, t.name AS topic_name,
               q.question_text, q.difficulty
        FROM questions q
        JOIN topics t ON t.id = q.topic_id
        WHERE {" AND ".join(conditions)}
        ORDER BY q.created_at DESC
        LIMIT 50
    """
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return {"results": [dict(r) for r in rows]}


# ─────────────────────────────────────────────────────────────────────────────
# Topic Question History
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/study/topic/{topic_id}/question-history/{user_id}")
def get_topic_question_history(
    topic_id: int,
    user_id: str,
    _token: dict = Depends(get_current_user)
):
    """
    Returns all questions from this topic that the user has seen,
    with attempt stats per question.
    """
    conn = get_connection()

    # Exam answers for this user/topic
    exam_rows = conn.execute(
        """
        SELECT
            q.id                                          AS question_id,
            q.question_text,
            q.difficulty,
            COUNT(ea.id)                                 AS attempt_count,
            SUM(ea.is_correct)                           AS times_correct,
            COUNT(ea.id) - SUM(ea.is_correct)            AS times_incorrect,
            MAX(ea.answered_at)                          AS last_attempted,
            CASE WHEN SUM(ea.is_correct) > 0 THEN 'correct' ELSE 'incorrect' END
                AS last_result,
            ROUND(100.0 * SUM(ea.is_correct) / COUNT(ea.id), 1) AS best_score
        FROM questions q
        JOIN exam_answers ea ON ea.question_id = q.id
        JOIN exam_sessions es ON es.id = ea.exam_session_id
        WHERE q.topic_id = ? AND es.user_id = ? AND es.status = 'completed'
        GROUP BY q.id
        """,
        (topic_id, user_id)
    ).fetchall()

    # Review logs for this user/topic
    review_rows = conn.execute(
        """
        SELECT
            q.id                                          AS question_id,
            q.question_text,
            q.difficulty,
            COUNT(rl.id)                                 AS attempt_count,
            SUM(CASE WHEN rl.quality >= 3 THEN 1 ELSE 0 END) AS times_correct,
            SUM(CASE WHEN rl.quality < 3 THEN 1 ELSE 0 END) AS times_incorrect,
            MAX(rl.reviewed_at)                         AS last_attempted,
            CASE WHEN SUM(CASE WHEN rl.quality >= 3 THEN 1 ELSE 0 END) > 0
                 THEN 'correct' ELSE 'incorrect' END      AS last_result,
            ROUND(100.0 * SUM(CASE WHEN rl.quality >= 3 THEN 1 ELSE 0 END) / COUNT(rl.id), 1)
                                                        AS best_score
        FROM questions q
        JOIN review_logs rl ON rl.question_id = q.id
        WHERE q.topic_id = ? AND rl.user_id = ?
        GROUP BY q.id
        """,
        (topic_id, user_id)
    ).fetchall()

    conn.close()

    # Combine — deduplicate by question_id, exam data takes precedence
    seen: dict = {}
    for r in exam_rows:
        seen[r["question_id"]] = dict(r)
    for r in review_rows:
        qid = r["question_id"]
        if qid in seen:
            # Merge: add attempt counts
            ex = seen[qid]
            ex["attempt_count"] = ex["attempt_count"] + r["attempt_count"]
            ex["times_correct"] = ex["times_correct"] + r["times_correct"]
            ex["times_incorrect"] = ex["times_incorrect"] + r["times_incorrect"]
            if r["last_attempted"] > ex["last_attempted"]:
                ex["last_attempted"] = r["last_attempted"]
                ex["last_result"] = r["last_result"]
        else:
            seen[qid] = dict(r)

    history = sorted(seen.values(), key=lambda x: x["last_attempted"] or "", reverse=True)
    return {"topic_id": topic_id, "questions": history, "total": len(history)}


# ─────────────────────────────────────────────────────────────────────────────
# Question Flags (exam prep markers)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/study/questions/{question_id}/flag")
def toggle_question_flag(
    question_id: str,
    body: FlagRequest,
    _token: dict = Depends(get_current_user)
):
    """Toggle flag for a question (exam-prep marker)."""
    user_id = body.user_id
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM question_flags WHERE user_id = ? AND question_id = ?",
        (user_id, question_id)
    ).fetchone()
    if existing:
        conn.execute("DELETE FROM question_flags WHERE user_id = ? AND question_id = ?",
                     (user_id, question_id))
        conn.commit()
        conn.close()
        return {"flagged": False}
    else:
        conn.execute(
            "INSERT OR IGNORE INTO question_flags (user_id, question_id) VALUES (?, ?)",
            (user_id, question_id)
        )
        conn.commit()
        conn.close()
        return {"flagged": True}


@app.get("/api/study/questions/{question_id}/flag")
def get_question_flag(
    question_id: str,
    user_id: str = Query(...),
    _token: dict = Depends(get_current_user)
):
    """Check if a question is flagged for a user."""
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM question_flags WHERE user_id = ? AND question_id = ?",
        (user_id, question_id)
    ).fetchone()
    conn.close()
    return {"flagged": row is not None}


# ─────────────────────────────────────────────────────────────────────────────
# Question Flags — List all flagged for a user
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/study/flags/{user_id}")
def get_flagged_questions(user_id: str, _token: dict = Depends(get_current_user)):
    """Return all flagged exam-prep questions for a user, sorted by flagged_at DESC."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT f.question_id, f.flagged_at,
               q.question_text, q.difficulty, t.name AS topic_name
        FROM question_flags f
        JOIN questions q ON q.id = f.question_id
        JOIN topics t ON t.id = q.topic_id
        WHERE f.user_id = ?
        ORDER BY f.flagged_at DESC
        """,
        (user_id,)
    ).fetchall()
    conn.close()
    return {"flagged_questions": [dict(r) for r in rows]}


# ─────────────────────────────────────────────────────────────────────────────
# Solo Study — focus on one specific question
# ─────────────────────────────────────────────────────────────────────────────

class SoloStudyRequest(BaseModel):
    user_id: str
    quality: int = Field(..., ge=0, le=5)


@app.post("/api/study/solo/{question_id}")
def solo_study(
    question_id: str,
    body: SoloStudyRequest,
    _token: dict = Depends(get_current_user),
):
    """
    Grade a single question studied in isolation (solo exam-prep mode).
    Returns the question data + SM-2 grade result for that one question.
    """
    uid = body.user_id
    quality = body.quality

    conn = get_connection()
    # Fetch question details
    q_row = conn.execute(
        "SELECT q.*, t.name AS topic_name FROM questions q "
        "JOIN topics t ON t.id = q.topic_id WHERE q.id = ?",
        (question_id,)
    ).fetchone()
    if not q_row:
        conn.close()
        raise HTTPException(404, "Question not found")

    q = _q_row(q_row)
    topic_name = q.pop("topic_name", "")

    # Get or create SM-2 progress row for this user/question
    up_row = conn.execute(
        "SELECT * FROM user_progress WHERE user_id = ? AND question_id = ?",
        (uid, question_id),
    ).fetchone()

    if up_row:
        up = dict(up_row)
    else:
        up = {
            "id": str(uuid.uuid4()),
            "user_id": uid,
            "question_id": question_id,
            "easiness_factor": 2.5,
            "interval": 0,
            "repetitions": 0,
            "next_review_date": date.today().isoformat(),
            "last_reviewed_at": None,
            "total_reviews": 0,
            "correct_count": 0,
        }

    sm2_fields = SM2Fields(
        easiness_factor=up["easiness_factor"],
        interval=up["interval"],
        repetitions=up["repetitions"],
    )
    new_sm2 = sm2_step(sm2_fields, quality)

    # Write review log
    review_id = str(uuid.uuid4())
    correct = 1 if quality >= 3 else 0
    conn.execute(
        """INSERT INTO review_logs
        (id, user_id, question_id, quality, quality_numeric,
         easiness_factor_before, easiness_factor_after,
         interval_before, interval_after, reviewed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (review_id, uid, question_id, quality, quality,
         up["easiness_factor"], new_sm2.easiness_factor,
         up["interval"], new_sm2.interval),
    )

    # Upsert user_progress
    conn.execute(
        """INSERT OR REPLACE INTO user_progress
        (id, user_id, question_id, easiness_factor, interval, repetitions,
         next_review_date, last_reviewed_at, total_reviews, correct_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)""",
        (up["id"], uid, question_id,
         new_sm2.easiness_factor, new_sm2.interval, new_sm2.repetitions,
         (date.today() + timedelta(days=new_sm2.interval)).isoformat(),
         up["total_reviews"] + 1,
         up["correct_count"] + correct),
    )
    conn.commit()
    conn.close()

    return {
        "question_id": question_id,
        "question_text": q.get("question_text"),
        "topic_name": topic_name,
        "difficulty": q.get("difficulty"),
        "answer_text": q.get("answer_text"),
        "explanation": q.get("explanation"),
        "quality": quality,
        "correct": correct == 1,
        "easiness_factor_before": up["easiness_factor"],
        "easiness_factor_after": new_sm2.easiness_factor,
        "interval_before": up["interval"],
        "interval_after": new_sm2.interval,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

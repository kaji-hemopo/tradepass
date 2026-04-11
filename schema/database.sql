-- TradePass PostgreSQL Schema
-- SuperMemo-2 Spaced Repetition for NZ EWRB Trade Certifications
-- PostgreSQL target (Supabase-ready); SQLite mock for local MVP
-- Generated: 2026-04-10

-- =============================================================================
-- EXTENSIONS
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- ENUMS
-- =============================================================================
CREATE TYPE question_difficulty AS ENUM ('easy', 'medium', 'hard');
CREATE TYPE review_quality AS ENUM ('blackout', 'wrong', 'hard', 'okay', 'good', 'perfect');
CREATE TYPE exam_status AS ENUM ('in_progress', 'completed', 'abandoned');

-- =============================================================================
-- TOPICS (EWRB exam domains)
-- =============================================================================
CREATE TABLE topics (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,                  -- e.g., "Voltage Drop", "Fault Loop Zs"
    slug            TEXT NOT NULL UNIQUE,           -- e.g., "voltage-drop", "fault-loop-zs"
    description     TEXT,
    weight          INTEGER NOT NULL DEFAULT 1,     -- exam weighting (1-5)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- QUESTIONS (EWRB exam question bank)
-- =============================================================================
CREATE TABLE questions (
    id                  UUID NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    topic_id            INTEGER NOT NULL REFERENCES topics(id) ON DELETE RESTRICT,
    question_text       TEXT NOT NULL,
    answer_text         TEXT NOT NULL,
    explanation         TEXT,                        -- why correct, why others wrong
    reference_clause    TEXT,                        -- AS/NZS 3000 clause or regulation ref
    difficulty          question_difficulty NOT NULL DEFAULT 'medium',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- USERS (future: Supabase Auth integration)
-- =============================================================================
CREATE TABLE users (
    id              UUID NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    email           TEXT,                            -- nullable pre-auth
    display_name    TEXT,
    timezone        TEXT NOT NULL DEFAULT 'Pacific/Auckland',
    is_premium      BOOLEAN NOT NULL DEFAULT FALSE,
    stripe_customer_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- USER PROGRESS (SuperMemo-2 fields per user per question)
-- One row per (user, question) pair — this is the SR state engine.
-- =============================================================================
CREATE TABLE user_progress (
    id                  UUID NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question_id         UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    easiness_factor     REAL NOT NULL DEFAULT 2.5,  -- SM-2: EF, min 1.3
    interval            INTEGER NOT NULL DEFAULT 0, -- days until next review
    repetitions         INTEGER NOT NULL DEFAULT 0,  -- successful review count
    next_review_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    last_reviewed_at    TIMESTAMPTZ,
    total_reviews       INTEGER NOT NULL DEFAULT 0,
    correct_count       INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    --
    UNIQUE (user_id, question_id)
);

-- Index for fast "due reviews" query
CREATE INDEX idx_user_progress_due
    ON user_progress (user_id, next_review_date)
    WHERE next_review_date <= CURRENT_DATE + INTERVAL '1 day';

-- =============================================================================
-- REVIEW LOGS (history + analytics)
-- =============================================================================
CREATE TABLE review_logs (
    id                      UUID NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question_id             UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    quality                 review_quality NOT NULL,   -- SM-2: 0-5 mapped to enum
    quality_numeric         INTEGER NOT NULL CHECK (quality_numeric BETWEEN 0 AND 5),
    easiness_factor_before  REAL NOT NULL,
    easiness_factor_after   REAL NOT NULL,
    interval_before         INTEGER NOT NULL,
    interval_after          INTEGER NOT NULL,
    review_duration_ms      INTEGER,                   -- time spent on card
    reviewed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for analytics queries (weak topic detection)
CREATE INDEX idx_review_logs_user_topic
    ON review_logs (user_id, question_id, reviewed_at DESC);

-- =============================================================================
-- EXAM SESSIONS (Exam Simulation Mode — TASK 5)
-- =============================================================================
CREATE TABLE exam_sessions (
    id                  UUID NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_ids           INTEGER[],                    -- which topics this exam covers
    total_questions     INTEGER NOT NULL,
    correct_count       INTEGER NOT NULL DEFAULT 0,
    score_percent       REAL,
    time_limit_minutes  INTEGER NOT NULL DEFAULT 120,
    time_spent_seconds  INTEGER NOT NULL DEFAULT 0,
    status              exam_status NOT NULL DEFAULT 'in_progress',
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    pass_mark           REAL NOT NULL DEFAULT 70.0    -- EWRB standard
);

-- =============================================================================
-- EXAM ANSWERS (individual answers per exam session)
-- =============================================================================
CREATE TABLE exam_answers (
    id                  UUID NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    exam_session_id     UUID NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
    question_id         UUID NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    selected_answer     TEXT,
    is_correct          BOOLEAN NOT NULL,
    topic_id            INTEGER NOT NULL REFERENCES topics(id),
    answered_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for per-topic exam breakdown analysis
CREATE INDEX idx_exam_answers_session
    ON exam_answers (exam_session_id, topic_id);

-- =============================================================================
-- WEAK TOPIC DETECTION VIEW (computed, refreshed on demand)
-- Accuracy per topic per user — used to flag weak zones
-- =============================================================================
CREATE VIEW topic_accuracy AS
SELECT
    u.id                     AS user_id,
    t.id                     AS topic_id,
    t.name                   AS topic_name,
    t.slug                   AS topic_slug,
    COUNT(ea.id)             AS total_attempts,
    SUM(CASE WHEN ea.is_correct THEN 1 ELSE 0 END) AS correct_attempts,
    ROUND(
        100.0 * SUM(CASE WHEN ea.is_correct THEN 1 ELSE 0 END) / NULLIF(COUNT(ea.id), 0),
        1
    )                        AS accuracy_pct,
    CASE
        WHEN COUNT(ea.id) < 5 THEN NULL          -- not enough data
        WHEN ROUND(100.0 * SUM(CASE WHEN ea.is_correct THEN 1 ELSE 0 END) / NULLIF(COUNT(ea.id), 0), 1) < 70
            THEN TRUE
        ELSE FALSE
    END                      AS is_weak
FROM users u
CROSS JOIN topics t
LEFT JOIN exam_answers ea
    ON ea.user_id = u.id
    AND ea.topic_id = t.id
GROUP BY u.id, t.id, t.name, t.slug;

-- =============================================================================
-- STUDY SESSIONS (guided review sessions — TASK 8)
-- =============================================================================
CREATE TYPE study_session_type AS ENUM ('review', 'weakness_drill', 'exam');
CREATE TYPE study_session_status AS ENUM ('in_progress', 'completed', 'abandoned');

CREATE TABLE study_sessions (
    id              UUID NOT NULL DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type            study_session_type NOT NULL DEFAULT 'review',
    status          study_session_status NOT NULL DEFAULT 'in_progress',
    question_ids    UUID[] NOT NULL,                  -- ordered list of question UUIDs
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_study_sessions_user_status
    ON study_sessions (user_id, status);

-- =============================================================================
-- SEED DATA — EWRB Topic Taxonomy
-- =============================================================================
INSERT INTO topics (name, slug, description, weight) VALUES
    ('Voltage Drop',            'voltage-drop',           'AS/NZS 3000 volt drop calculations and limits',              5),
    ('Fault Loop Impedance',    'fault-loop-zs',           'Zs verification, Ze calculation, Zc timing',                   5),
    ('AS/NZS 3000 Wiring Rules','as-nzs-3000',              'General wiring rules, cable sizing, installation methods',   5),
    ('Insulation Resistance',   'insulation-resistance',   'IR testing, min values, test voltages',                      3),
    ('Max Demand & Diversity',  'max-demand',              'Diversity factors, demand calculations, cable selection',    3),
    ('RCD & MCB Protection',    'rcd-mcb',                  'RCD sizing, MCB curves, discrimination',                     3),
    ('Supply Systems',          'supply-systems',           'TT/TN/CS, earthing, MEN, supply characteristics',             2),
    ('Motor Starters',          'motor-starters',           'DOL, star-delta, soft starters, thermal overload',            2),
    ('Switchboards',            'switchboards',             'Board design, clearances, segregation, labelling',           2),
    ('Circuit Design',          'circuit-design',           'Circuit types, protective devices, documentation',            2);

-- =============================================================================
-- TRIGGER: updated_at auto-update
-- =============================================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_questions_updated_at
    BEFORE UPDATE ON questions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_user_progress_updated_at
    BEFORE UPDATE ON user_progress
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

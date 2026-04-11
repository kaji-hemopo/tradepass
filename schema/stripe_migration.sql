-- TradePass Stripe Freemium Migration
-- Adds subscription and tier fields to the users table
-- Run this migration AFTER schema/database.sql has been applied
-- Compatible with: SQLite (local dev) and PostgreSQL (production/Supabase)
--
-- To run against SQLite:
--   sqlite3 tradepass.db < schema/stripe_migration.sql
--
-- To run against PostgreSQL (Supabase):
--   psql $DATABASE_URL -f schema/stripe_migration.sql
--
-- ─────────────────────────────────────────────────────────────────────────────

-- Free tier: Voltage Drop (topic_id=1), Fault Loop Impedance (topic_id=2)
-- Premium unlocks: All 11 topics + unlimited exam simulation
-- Free exam quota: 1 completed exam session per user

BEGIN;

-- 1. Add subscription fields to users table
-- Only add if columns don't already exist (idempotent for repeated runs)

-- SQLite: Use PRAGMA to check column existence (run via python or sqlite3 shell if needed)
-- PostgreSQL: Use ALTER TABLE with IF NOT EXISTS (PostgreSQL 14+)

-- ── For SQLite (backward compatible check) ──────────────────────────────────
-- Note: SQLite does not support IF NOT EXISTS for ADD COLUMN before version 3.35.0.
-- The script below uses a Python helper to apply SQLite migrations.
-- For PostgreSQL, the ALTER TABLE statements below run directly.

-- ── PostgreSQL version ───────────────────────────────────────────────────────
-- Uncomment the PostgreSQL block and comment out the SQLite block for Supabase

-- ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN NOT NULL DEFAULT FALSE;
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status TEXT;  -- active | past_due | canceled | trialing
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_end_date TEXT;  -- ISO8601 timestamp
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_price_id TEXT;  -- monthly or annual price ID
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TEXT;  -- ISO8601 timestamp


-- ── SQLite version ───────────────────────────────────────────────────────────
-- SQLite-safe: use PRAGMA table_info to check column existence before adding

-- Migration: Add is_premium
-- Migration: Add stripe_customer_id
-- Migration: Add subscription_status
-- Migration: Add subscription_end_date
-- Migration: Add stripe_price_id
-- Migration: Add updated_at


-- ══════════════════════════════════════════════════════════════════════════════
-- For Python/SQLite apply_migration() — paste into load_seed_data.py or a standalone script
-- ══════════════════════════════════════════════════════════════════════════════
--
-- def apply_stripe_migration(conn):
--     """
--     Idempotent SQLite migration for Stripe subscription fields.
--     Safe to call multiple times — only adds missing columns.
--     """
--     import sqlite3
--     cur = conn.cursor()
--
--     # Get existing column names
--     cur.execute("PRAGMA table_info(users)")
--     existing_cols = {row[1] for row in cur.fetchall()}
--
--     migrations = {
--         "is_premium":            "ALTER TABLE users ADD COLUMN is_premium BOOLEAN NOT NULL DEFAULT 0",
--         "stripe_customer_id":    "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT",
--         "subscription_status":   "ALTER TABLE users ADD COLUMN subscription_status TEXT",
--         "subscription_end_date": "ALTER TABLE users ADD COLUMN subscription_end_date TEXT",
--         "stripe_price_id":       "ALTER TABLE users ADD COLUMN stripe_price_id TEXT",
--         "updated_at":            "ALTER TABLE users ADD COLUMN updated_at TEXT",
--     }
--
--     for col_name, ddl in migrations.items():
--         if col_name not in existing_cols:
--             cur.execute(ddl)
--             print(f"  ✓ Added column: {col_name}")
--         else:
--             print(f"  - Skipped (exists): {col_name}")
--
--     conn.commit()
--     print("Stripe migration applied successfully.")
--
--
-- ══════════════════════════════════════════════════════════════════════════════
-- CONSTANTS — hardcoded into app logic, NOT stored in DB
-- ══════════════════════════════════════════════════════════════════════════════
--
-- FREE_TOPIC_IDS = {1, 2}           -- Voltage Drop, Fault Loop Impedance
-- FREE_EXAM_LIMIT = 1              -- one free completed exam per user
-- TIER_CHECK_ENDPOINTS = {
--     "GET /api/study/topic/{id}":         lambda tid: tid not in FREE_TOPIC_IDS,
--     "GET /api/study/questions":          lambda params: int(params.get("topic_id", 0)) not in FREE_TOPIC_IDS,
--     "POST /api/exams/start":             lambda: True,  -- checked via exam quota
--     "GET /api/weak-zones/{uid}/review-queue": lambda: True,
-- }
-- ══════════════════════════════════════════════════════════════════════════════


-- ══════════════════════════════════════════════════════════════════════════════
-- PostgreSQL Production Migration (Supabase)
-- Run with: psql $DATABASE_URL -f schema/stripe_migration.sql
-- ══════════════════════════════════════════════════════════════════════════════

-- Add subscription columns (PostgreSQL 14+ IF NOT EXISTS)
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_end_date TIMESTAMP WITH TIME ZONE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_price_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();

-- Index for fast subscription status lookup
CREATE INDEX IF NOT EXISTS idx_users_stripe_customer_id ON users(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_users_is_premium ON users(is_premium);

COMMIT;

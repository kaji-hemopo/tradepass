# TradePass TASK 9 — Stripe Freemium Integration (Design Brief)

**Agent**: Odie (workspace-odie/TradePass/)
**Task**: TASK 9 in TASK_QUEUE.md
**Priority**: HIGH — needed before MVP launch
**Deadline**: Next heartbeat cycle

---

## Context

TradePass is a micro-SaaS MVP: spaced-repetition exam engine for NZ trade certifications (EWRB Electricians first).
- Backend: Python/FastAPI, SQLite mock (PostgreSQL target on Supabase)
- 8 tasks complete (TASK 1–8): EWRB research, 20 Qs, schema, FastAPI, exam sim, explanations, weakness engine, progress dashboard
- TASK 9 and 10 remain in the backlog

---

## TASK 9: Stripe Freemium Integration (Design Only)

The goal of this task is to DESIGN the Stripe integration — do NOT implement payment processing yet.

### What to produce

Write a design doc at `design/stripe_freemium_design.md` covering:

1. **Freemium Model Definition**
   - Free tier: what limits? (e.g., first 2 topics only = ~50 questions, no exam simulation)
   - Premium tier: "EWRB Complete" — full question bank + exam sim
   - Price point: ¥1,500/mo (~NZD $15/mo) — reason: $149 EWRB exam >> $15 sub makes it cheap
   - Annual discount option?

2. **Stripe Product / Price Setup**
   - Product name: "TradePass EWRB Complete"
   - Pricing: 1,500 JPY/month, 15,000 JPY/year (2 months free)
   - Currency: JPY (Stripe Japan supports JPY)
   - One-time purchase option? ($149 EWRB exam >> $15 sub — but maybe bundle)

3. **Implementation Architecture**
   - Use Stripe Checkout (hosted page — simplest, no PCI compliance issues)
   - Webhook endpoint: `POST /api/webhooks/stripe` to handle `checkout.session.completed`, `customer.subscription.deleted`
   - User table update: `is_premium BOOLEAN`, `stripe_customer_id TEXT`, `subscription_status TEXT`
   - Protect premium endpoints: middleware checks `is_premium` on `/api/exams/*`, `/api/weak-zones/full`

4. **Freemium Gate Logic**
   - Topic access: free users can access topics 1-2 only (Volt Drop, Fault Loop Zs)
   - Exam simulation: free users get 1 free exam, then pay
   - How to enforce: `user_tier` enum ('free', 'premium') in users table

5. **Database Migration**
   - Write SQL migration at `schema/stripe_migration.sql`:
     - Add `is_premium BOOLEAN DEFAULT FALSE` to users table
     - Add `stripe_customer_id TEXT`
     - Add `subscription_status TEXT`
     - Add `subscription_end_date TIMESTAMP`
   - Write `schema/stripe_migration.sql` — make it executable against the existing schema

6. **API Endpoint Design**
   - `POST /api/create-checkout-session` — creates Stripe Checkout session for premium
   - `POST /api/webhooks/stripe` — handles Stripe webhooks (verify signature)
   - `GET /api/user/subscription` — returns user's subscription status
   - `POST /api/cancel-subscription` — cancels at period end

7. **Environment Variables Required**
   ```
   STRIPE_SECRET_KEY=sk_test_...
   STRIPE_WEBHOOK_SECRET=whsec_...
   STRIPE_PRICE_ID_MONTHLY=price_...
   STRIPE_PRICE_ID_ANNUAL=price_...
   ```

8. **Testing Plan**
   - How to test Stripe locally (use Stripe CLI + test mode)
   - Test checkout session creation
   - Test webhook locally with Stripe CLI
   - Mock a successful payment for local testing

9. **Alternatives Considered**
   - LemonSocke / Paddle — why Stripe was chosen (marketplace vs direct)
   - In-app purchases vs Stripe — PCI complexity

---

## Deliverables

1. `design/stripe_freemium_design.md` — full design doc
2. `schema/stripe_migration.sql` — executable SQL migration
3. Update `STATE.md` — mark TASK 9 as design-complete and note what's ready for implementation

---

## Constraints

- Design only — no payment processing code yet
- Use absolute paths: `/Users/jacksonhemopo/.openclaw/workspace-odie/TradePass/`
- Write tools (NOT edit) for any file writes
- Terminate after completing the design doc

---

## Success Criteria

- [ ] `design/stripe_freemium_design.md` exists and covers all 9 sections above
- [ ] `schema/stripe_migration.sql` is runnable against existing database schema
- [ ] `STATE.md` checkpoint updated: TASK 9 design complete, ready for implementation
- [ ] `TASK_QUEUE.md` — TASK 9 marked complete, TASK 10 becomes top pending
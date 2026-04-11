# TradePass — Stripe Freemium Integration Design

**Status**: Design Complete (TASK 9 — implementation pending)
**Last Updated**: 2026-04-11 17:56 UTC

---

## 1. Freemium Model Definition

### Free Tier
- **Question access**: Topics 1–2 only (Voltage Drop + Fault Loop Impedance) = ~8 questions
- **Exam simulation**: 1 free exam session, then blocked with upsell prompt
- **Study mode**: Full access to free-topic question explanations and review (SM-2)
- **Dashboard**: Full access to progress dashboard and streak tracking
- **No time limit on free tier**: User can study free topics indefinitely
- **Rationale**: Voltage Drop and Fault Loop Impedance are the #1 and #2 highest-failure EWRB topics — give users a taste that proves the value of the app before asking for payment

### Premium Tier — "EWRB Complete"
- **Price**: ¥1,500/month (≈ NZD $15/mo)
- **Full question bank**: All 11 topics, all 20+ questions
- **Exam simulation**: Unlimited exam sessions, all topics
- **Weak zone drill**: Full access to prioritised weak-zone queue
- **Study priority**: Full urgency-ranked topic recommendations
- **Annual option**: ¥15,000/year (2 months free) — Stripe Price ID: `STRIPE_PRICE_ID_ANNUAL`
- **One-time purchase**: Not offered initially — subscription aligns with recurring revenue model and lifetime value; revisit after 3 months if churn is low

### Why ¥1,500/mo?
- EWRB exam fee: ~NZD $149 (~¥13,500)
- Passing the exam on the first try saves ¥13,500 — ¥1,500/mo is 11% of that cost
- Tradies routinely pay ¥3,000–8,000 for one-day exam prep courses
- Target: users who see the app as exam insurance, not a monthly subscription

---

## 2. Stripe Product / Price Setup

### Product
- **Name**: TradePass EWRB Complete
- **Description**: Unlimited exam simulation + full question bank for NZ EWRB Electrician's Theory & Regulations exams

### Prices (Stripe Dashboard configuration)
| Price Name | Amount | Currency | Interval | Stripe Price ID env var |
|---|---|---|---|---|
| Monthly | ¥1,500 JPY | JPY | month | `STRIPE_PRICE_ID_MONTHLY` |
| Annual | ¥15,000 JPY | JPY | year | `STRIPE_PRICE_ID_ANNUAL` |

### Stripe Currency Note
- Stripe Japan supports JPY directly — no currency conversion needed
- Use `jpy` as the `currency` parameter in Checkout Session API calls
- Set `locale: 'auto'` in Checkout Session for Japanese/English localisation

### Stripe Dashboard Steps
1. Create product "TradePass EWRB Complete" in Stripe Dashboard (test mode first)
2. Create two prices: ¥1,500/month recurring, ¥15,000/year recurring
3. Copy Price IDs into `.env` (never commit to repo)
4. Enable customer portal for self-service cancellation/upgrades

---

## 3. Implementation Architecture

### Flow Overview
```
User clicks "Go Premium"
  → POST /api/create-checkout-session { user_id, price_id: "monthly" | "annual" }
  → Backend creates Stripe Checkout Session (hosted page)
  → User redirected to Stripe Checkout (PCI-compliant, no card data touches backend)
  → On success: Stripe redirects to /premium/success?session_id=cs_xxx
  → Stripe sends checkout.session.completed webhook → POST /api/webhooks/stripe
  → Webhook handler: verify signature, update user is_premium=TRUE, subscription_status="active"
  → User redirected to success page → full access granted
```

### Webhook Events to Handle
| Event | Action |
|---|---|
| `checkout.session.completed` | Set `is_premium=TRUE`, `subscription_status="active"`, store `stripe_customer_id` |
| `customer.subscription.deleted` | Set `is_premium=FALSE`, `subscription_status="canceled"` |
| `customer.subscription.updated` | Update `subscription_status` (e.g., "past_due" → prompt user) |
| `invoice.payment_failed` | Set `subscription_status="past_due"` — block premium features on next heartbeat |

### Key Design Decisions
- **Stripe Checkout (hosted)**: No PCI compliance burden. Card details never touch our backend. Stripe handles 3DS, locale, receipt emails.
- **No Stripe Customer Portal (yet)**: Simplicity over self-service. Add in phase 2 for cancellation/upgrade flows.
- **Webhook over polling**: Subscription status driven by webhook events, not by polling Stripe API.

---

## 4. Freemium Gate Logic

### Tier Enforcement Points

#### Topic Access
```python
# Free topics: Voltage Drop (id=1), Fault Loop Impedance (id=2)
FREE_TOPIC_IDS = {1, 2}

def require_premium_or_free_topic(user_id: str, topic_id: int):
    if user_tier(user_id) == "premium":
        return  # allow
    if topic_id not in FREE_TOPIC_IDS:
        raise HTTPException(403, "Premium required for this topic")
```

Endpoints affected:
- `GET /api/study/topic/{topic_id}` — block if topic_id ∉ FREE_TOPIC_IDS and user is free
- `GET /api/study/questions?topic_id=X` — same gate
- `GET /api/weak-zones/{user_id}` — return only free topics for non-premium

#### Exam Simulation Gate
```python
FREE_EXAM_LIMIT = 1  # one free exam per user

def check_exam_quota(user_id: str) -> bool:
    """Return True if user has exam quota remaining."""
    # Count completed exam sessions for this user
    count = conn.execute(
        "SELECT COUNT(*) FROM exam_sessions WHERE user_id = ? AND status = 'completed'",
        (user_id,)
    ).fetchone()[0]
    return count < FREE_EXAM_LIMIT or user_tier(user_id) == "premium"
```

Endpoints affected:
- `POST /api/exams/start` — check quota; if exceeded, return 403 with upsell message
- Upsell response body: `{"error": "premium_required", "message": "Upgrade to EWRB Complete for unlimited exams", "upsell_url": "/premium"}`

#### Premium Endpoints (new)
These endpoints return 403 for non-premium users:
- `POST /api/exams/start` (beyond free limit)
- `GET /api/weak-zones/{user_id}/review-queue` (full drill queue — free users get limited queue)

---

## 5. Database Migration

See: `schema/stripe_migration.sql`

```sql
-- Adds Stripe subscription fields to users table
-- Run against existing tradepass.db or PostgreSQL schema

ALTER TABLE users ADD COLUMN is_premium BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN stripe_customer_id TEXT;
ALTER TABLE users ADD COLUMN subscription_status TEXT;  -- 'active' | 'past_due' | 'canceled' | 'trialing'
ALTER TABLE users ADD COLUMN subscription_end_date TEXT; -- ISO8601 timestamp
ALTER TABLE users ADD COLUMN stripe_price_id TEXT;      -- current active price
ALTER TABLE users ADD COLUMN updated_at TEXT;            -- ISO8601
```

### Users Table Post-Migration Schema
| Column | Type | Notes |
|---|---|---|
| id | TEXT | UUID, primary key |
| name | TEXT | User display name |
| email | TEXT | Unique, for Stripe identification |
| created_at | TEXT | ISO8601 |
| is_premium | BOOLEAN | DEFAULT FALSE |
| stripe_customer_id | TEXT | From Stripe Checkout |
| subscription_status | TEXT | active/past_due/canceled/trialing |
| subscription_end_date | TEXT | ISO8601, for access revocation |
| stripe_price_id | TEXT | Monthly or annual price |
| updated_at | TEXT | ISO8601 |

---

## 6. API Endpoint Design

### `POST /api/create-checkout-session`

**Request**:
```json
{
  "user_id": "uuid",
  "price_id": "monthly" | "annual"
}
```

**Response (200)**:
```json
{
  "checkout_url": "https://checkout.stripe.com/c/pay/..."
}
```
Client redirects user to `checkout_url`.

**Response (400)** — user already premium:
```json
{
  "error": "already_premium"
}
```

**Implementation notes**:
- Pass `client_reference_id: user_id` in session metadata for webhook lookup
- Pass `customer_email` if user has email (pre-fill Stripe form)
- Success redirect: `{APP_URL}/premium/success`
- Cancel redirect: `{APP_URL}/premium/cancel`

---

### `POST /api/webhooks/stripe`

**Stripe signature verification** (required — do NOT skip):
```python
import stripe
stripe.api_key = settings.STRIPE_SECRET_KEY
event = stripe.Webhook.construct_event(
    payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
)
```

**Event routing**:
```
checkout.session.completed → activate_premium(session)
customer.subscription.deleted → deactivate_premium(subscription)
customer.subscription.updated → update_subscription_status(subscription)
invoice.payment_failed → set_past_due(customer_id)
```

**Webhook test** (Stripe CLI):
```bash
stripe listen --forward-to localhost:8000/api/webhooks/stripe
# Stripe CLI outputs webhook secret: whsec_xxx
# Put this in STRIPE_WEBHOOK_SECRET
```

---

### `GET /api/user/subscription`

**Response (200)**:
```json
{
  "user_id": "uuid",
  "is_premium": true,
  "subscription_status": "active",
  "subscription_end_date": "2026-05-11T00:00:00Z",
  "tier": "premium",
  "price": "monthly"
}
```

---

### `POST /api/cancel-subscription`

**Response (200)**:
```json
{
  "status": "canceled",
  "message": "Subscription will remain active until 2026-05-11"
}
```

**Implementation**: Uses Stripe Billing Portal or direct API call to cancel at period end (`cancel_at_period_end: true`).

---

## 7. Environment Variables Required

```bash
# .env — NEVER commit this file
STRIPE_SECRET_KEY=sk_test_...           # Stripe test secret key
STRIPE_PUBLISHABLE_KEY=pk_test_...       # Exposed to frontend
STRIPE_WEBHOOK_SECRET=whsec_...          # From `stripe listen` CLI output
STRIPE_PRICE_ID_MONTHLY=price_...       # From Stripe Dashboard > Product > Monthly Price
STRIPE_PRICE_ID_ANNUAL=price_...         # From Stripe Dashboard > Product > Annual Price
APP_URL=http://localhost:3000           # Frontend URL for redirect after checkout
```

---

## 8. Testing Plan

### Local Testing with Stripe CLI

```bash
# 1. Install Stripe CLI
brew install stripe/stripe-cli/stripe

# 2. Login
stripe login

# 3. Start webhook forwarding (separate terminal)
stripe listen --forward-to localhost:8000/api/webhooks/stripe

# 4. Copy the webhook signing secret (starts with whsec_) into STRIPE_WEBHOOK_SECRET

# 5. Create a checkout session (trigger locally)
curl -X POST http://localhost:8000/api/create-checkout-session \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test-user-123", "price_id": "monthly"}'

# 6. Open the checkout_url returned, use Stripe test card:
#    Card: 4242 4242 4242 4242 | Any future expiry | Any CVC | Any postal
#    (use https://stripe.com/docs/testing#test-cards for full list)

# 7. Webhook fires → check user is_premium in DB
```

### Test Cards (Stripe Test Mode)
| Card Number | Result |
|---|---|
| 4242 4242 4242 4242 | Successful payment |
| 4000 0000 0000 0002 | Always fails (card declined) |
| 4000 0025 0000 3155 | Requires 3D Secure |
| 4000 0000 0000 9995 | Insufficient funds |

### Test Scenarios
1. **Happy path**: Free user → checkout → webhook → is_premium=TRUE → can access all topics
2. **Cancel flow**: Premium user → cancel subscription → webhook → is_premium=FALSE at period end
3. **Payment failure**: Card expires → invoice.payment_failed → subscription_status="past_due"
4. **Duplicate checkout**: Already premium user tries to checkout → 400 "already_premium"
5. **Webhook signature**: Invalid payload → 400 "Invalid signature" → reject

### Local DB Verification
```bash
sqlite3 tradepass.db "SELECT id, email, is_premium, subscription_status FROM users;"
```

---

## 9. Alternatives Considered

### LemonSqueezy vs Stripe
| Factor | LemonSqueezy | Stripe |
|---|---|---|
| Japan/JPY support | Good, no-fuss | Excellent, direct JPY |
| Checkout UI | Hosted, clean | Hosted, highly customisable |
| Vendor API | Simplified | Full-featured |
| PCI compliance | Managed | Managed |
| Learning curve | Lower | Moderate |
| **Decision** | **Stripe chosen** | Marketplace/embed model better for subscription SaaS; Stripe's brand increases trust for ¥ purchase |

### Paddle vs Stripe
- Paddle: merchant of record (handles tax compliance for Japan — consumption tax)
- Trade-off: Paddle takes higher cut (~5%) vs Stripe (~3.5%) + added tax complexity
- **Decision**: Stripe + manual GST handling for Japan (< ¥10M revenue threshold) → revisit with Paddle if international expansion

### In-App Purchases (Apple/Google)
- 30% platform cut on digital goods
- Freemium model technically in-app purchase, but: user trust issues, Apple review delays, no web access
- **Decision**: Stripe-only for web (Phase 1); Apple App Store in-app purchase as Phase 2 for mobile

### Direct card processing (no Stripe)
- PCI DSS compliance required (SAQ-A self-assessment minimum)
- Too much liability and compliance overhead for MVP
- **Decision**: No

---

## Implementation Readiness Checklist

When Jackson is ready to implement:
- [ ] Create Stripe test account + product + prices
- [ ] Add `.env` with Stripe credentials
- [ ] Run `schema/stripe_migration.sql` against production DB
- [ ] Implement `POST /api/create-checkout-session` endpoint
- [ ] Implement `POST /api/webhooks/stripe` endpoint (signature verification required)
- [ ] Implement `GET /api/user/subscription` endpoint
- [ ] Add `require_premium()` middleware to backend
- [ ] Add tier gates to topic and exam endpoints
- [ ] Add frontend checkout button → redirect to `/premium/success`
- [ ] Test full flow with Stripe CLI + test cards
- [ ] Switch Stripe keys from test to live mode

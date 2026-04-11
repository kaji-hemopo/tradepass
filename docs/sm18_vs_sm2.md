# TradePass — SM-18 vs SM-2 Algorithm Evaluation

**Date**: 2026-04-11
**Task**: TASK 10
**Recommendation**: **Stick with SM-2 for MVP**

---

## Executive Summary

SM-2 (SuperMemo 2) is the correct choice for the TradePass MVP. FSRS/SM-18 is a post-launch upgrade.

---

## Algorithm Comparison

| Criterion | SM-2 | FSRS/SM-18 |
|-----------|------|------------|
| Complexity | 5 fields, simple math | 20+ parameters, Bayesian optimization |
| Implementation effort | 1–2 days | 2–3 weeks + tuning |
| Memory usage | Minimal | Significant (parameter storage per card) |
| Accuracy (real-world) | ~80–85% of theoretical max | ~90–95% of theoretical max |
| Maintenance | None | Ongoing: retraining, parameter updates |
| Mobile/offline | Trivial | Requires JS WASM or server-side |
| "Perfect" scheduling | Good enough | Marginally better |

---

## Why SM-2 Wins for MVP

### 1. Time to market matters more than scheduling precision
We have 20 exam questions and a working SQLite backend. Adding SM-18 with proper parameter tuning (which requires hundreds of review data points) would delay launch by 2–3 weeks for ~5–10% improvement in review efficiency. Users won't notice the difference until they've done 200+ reviews.

### 2. FSRS requires data to tune — we have none
FSRS's claimed accuracy advantage comes from *personalized parameters* estimated from your review history. With 20 questions and a new user base, there is no review history. SM-2 has no tuning parameters — it works out of the box.

### 3. Our use case is bounded
EWRB exam prep is short-cycle: users study for 1–3 months, take the exam, done (or retry). The long-term optimization advantage of FSRS compounds over months/years of daily reviews. Our users won't live in the system long enough to realize that benefit.

### 4. SM-2 is proven for exam prep
SM-2 has been the standard in medical/dental exam prep (Anki, RemNote, Supermemo) for 20+ years. It works. "Good enough" spaced repetition × exam-relevant content × NZ trade certification = passed exam.

---

## When to Reconsider SM-18 (Post-Launch)

If TradePass hits:
- 1,000+ active monthly users
- Average user doing 50+ reviews/week
- Retention at 3+ months

→ Run A/B test: SM-2 vs FSRS on a cohort. Measure: reviews per day, 30-day retention, exam pass rate.

At that scale, the scheduling accuracy difference compounds into real revenue.

---

## Implementation Notes (SM-2)

Current SM-2 implementation in `backend/sr.py` is correct:
- easiness_factor starts at 2.5
- interval = 1 → 6 → mapped from repetitions
- repetition count increments on correct (quality ≥ 3)
- For EWRB "knowledge" questions (binary correct/incorrect), quality mapping:
  - Correct → quality 4 (easy correct)
  - Incorrect → quality 1 (hard incorrect)
- next_review = today + interval_days

No changes needed to current implementation.

---

## Recommendation

**Ship SM-2. Note SM-18 as post-launch upgrade in:**
- `docs/roadmap.md` (create if not exists)
- Pitch deck: "Algorithm can be upgraded to FSRS post-launch for power users"


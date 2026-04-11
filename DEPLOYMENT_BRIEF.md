# TradePass MVP — Railway Deployment Brief

**Author:** Kaji (COO)
**Date:** 2026-04-11 04:15 JST
**Status:** Ready to hand off to dev subagent
**Target:** Railway.app — Python/FastAPI backend
**Stack:** FastAPI + uvicorn + SQLite (MVP) → PostgreSQL (production)

---

## Context

TradePass MVP backend is **10/10 tasks complete** (all TASK_9 bugs fixed, stripe_freemium_design.md written, all endpoints delivered). The backend is production-ready but has never been deployed. No users can access it.

**What exists:**
- `/Users/jacksonhemopo/.openclaw/workspace-odie/TradePass/backend/` — FastAPI app
- Git repo initialized (remote not yet set)
- `requirements.txt` with: `fastapi==0.115.0`, `uvicorn==0.30.6`, `pydantic==2.9.2`
- SQLite DB at `backend/tradepass.db` (seeded with 20 EWRB questions)

**What does NOT exist yet:**
- Frontend (Next.js planned — not started)
- Railway project
- GitHub remote / GitHub Actions token
- Production domain

---

## Goal

Deploy the FastAPI backend to Railway so it is accessible at a live URL (e.g. `https://tradepass-backend.up.railway.app`). Frontend can be built in a subsequent task.

---

## Prerequisites (Jax or Kaji must provide)

1. **Railway account** — sign up at railway.app (GitHub login recommended)
2. **Railway token** — from railway.app → Account → Tokens
3. **GitHub remote** — either:
   - Create a GitHub repo for the backend and push, OR
   - Use Railway CLI directly (no GitHub required)

---

## Step-by-Step Deployment

### Option A — Railway CLI (fastest, no GitHub needed)

```bash
# 1. Install Railway CLI
curl -fsSL https://railway.app/install.sh | sh

# 2. Login
railway login

# 3. Go to backend directory
cd /Users/jacksonhemopo/.openclaw/workspace-odie/TradePass/backend/

# 4. Initialize Railway project (interactive)
railway init
# Choose: "Empty project" → name it "tradepass-backend"

# 5. Set environment variables
railway variables set ENVIRONMENT=production
railway variables set PORT=8000

# 6. Deploy
railway up

# 7. Get public URL
railway domain
```

**Start command** (Railway will auto-detect FastAPI if `requirements.txt` is present):
```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

To set this explicitly in Railway dashboard:
- Project → tradepass-backend → Settings → Start Command → enter:
  ```
  uvicorn main:app --host 0.0.0.0 --port $PORT
  ```

### Option B — GitHub Actions (production-ready CI/CD)

**Step 1:** Create a GitHub repo for the backend:
```bash
# In backend directory
cd /Users/jacksonhemopo/.openclaw/workspace-odie/TradePass/backend/
git init
git remote add origin https://github.com/jacksonhemopo/tradepass-backend.git
git add .
git commit -m "TradePass MVP backend - 10/10 tasks complete"
git branch -M main
git push -u origin main
```

**Step 2:** Create a Railway token:
- Go to railway.app → Account → Tokens → New Token
- Copy the token value

**Step 3:** Add the token to GitHub repo:
- GitHub repo → Settings → Secrets and variables → Actions → New repository secret
- Name: `RAILWAY_TOKEN`
- Value: `<your railway token>`

**Step 4:** Update `.github/workflows/deploy.yml` in the backend repo:
```yaml
name: Deploy to Railway

on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Railway
        run: |
          curl -fsSL https://railway.app/install.sh | sh
          echo "$HOME/.railway/bin" >> $GITHUB_PATH

      - name: Deploy
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
          RAILWAY_PROJECT_ID: ${{ vars.RAILWAY_PROJECT_ID }}
        run: |
          railway login --token $RAILWAY_TOKEN
          railway deploy --service tradepass-backend
        working-directory: ./backend
```

### Health Check

Once deployed, verify with:
```bash
curl https://<your-railway-url>.up.railway.app/docs
```
Should return the FastAPI Swagger UI.

Or:
```bash
curl https://<your-railway-url>.up.railway.app/api/topics
```

---

## Environment Variables

| Variable | Value | Notes |
|----------|-------|-------|
| `ENVIRONMENT` | `production` | |
| `PORT` | `8000` | Railway sets this automatically — don't hardcode |

**Future (PostgreSQL + Stripe — TASK 9+):**
| Variable | Value | Notes |
|----------|-------|-------|
| `DATABASE_URL` | `postgresql://...` | Supabase or Railway PostgreSQL |
| `STRIPE_SECRET_KEY` | `sk_live_...` | Stripe production key |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` | Stripe webhook endpoint secret |

---

## Database Strategy

**MVP (current):** SQLite file at `backend/tradepass.db`
- ✅ Works out of the box on Railway
- ⚠️ SQLite is file-based — not persistent on Railway's ephemeral filesystem
- **Fix:** Attach a Railway Volume OR switch to PostgreSQL

**Recommended (next step):**
1. Create PostgreSQL database in Railway: `railway add postgresql`
2. Get `DATABASE_URL` from Railway variables
3. Update `database.py` to use `DATABASE_URL` instead of SQLite path
4. Run schema: `psql $DATABASE_URL < schema/database.sql`

---

## Backend API Overview (production endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/docs` | GET | FastAPI Swagger UI |
| `/api/topics` | GET | List all topics |
| `/api/topics/{id}/questions` | GET | Questions for a topic |
| `/api/study/due/{user_id}` | GET | SM-2 due questions |
| `/api/review` | POST | Submit SM-2 review grade |
| `/api/exams/start` | POST | Start exam simulation |
| `/api/weak-zones/{user_id}` | GET | Weakness detection |
| `/api/study/dashboard/{user_id}` | GET | Progress + streaks |

---

## Verification Checklist

After deployment, verify ALL of these:

- [ ] `GET /docs` → 200 OK (Swagger UI loads)
- [ ] `GET /api/topics` → 200 OK (returns 11 topics)
- [ ] `POST /api/users` with `{id: "test-user", email: "test@test.com"}` → creates user
- [ ] `GET /api/study/due/test-user` → returns due questions
- [ ] `POST /api/review` with valid SM-2 quality grade → 200 OK
- [ ] `POST /api/exams/start` → returns exam ID
- [ ] Backend is reachable from external internet (not just localhost)

---

## Post-Deployment (Next Tasks)

These should be queued after deployment is live:

1. **Frontend Build** — Next.js app that calls the Railway API. Landing page + auth + exam UI.
2. **Custom Domain** — Point `api.tradepass.io` or similar to Railway URL
3. **PostgreSQL Migration** — Replace SQLite with Supabase/Railway PostgreSQL
4. **Stripe Integration** — TASK 9 design is ready; implement after DB migration

---

## Blockers

- **Railway token** — needs Jax to create account / generate token (if using GitHub Actions)
- **GitHub remote** — backend repo exists locally but has no GitHub remote
- **Frontend** — not started; without it, users have no UI (only API docs)

---

## Subagent Prompt (copy-paste for dev subagent)

```
Read /Users/jacksonhemopo/.openclaw/workspace-odie/TradePass/DEPLOYMENT_BRIEF.md
and deploy the TradePass FastAPI backend to Railway.

Steps:
1. cd /Users/jacksonhemopo/.openclaw/workspace-odie/TradePass/backend/
2. Install Railway CLI: curl -fsSL https://railway.app/install.sh | sh
3. railway login (interactive — use browser)
4. railway init — create project named "tradepass-backend"
5. railway variables set ENVIRONMENT=production
6. railway up (deploy from current directory)
7. railway domain — get the public URL

SUCCESS CRITERIA:
- Backend is accessible at a public URL
- GET /docs returns 200
- GET /api/topics returns the 11 EWRB topics as JSON

If Railway CLI login fails, try: railway login --browser
If deploy fails, share the error output.
```

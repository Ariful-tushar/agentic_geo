# AnswerWatch

Monitors what AI assistants say about a company, every day, automatically. Independent demo, not affiliated with the selected company.

This README only holds the deployment checklist for now. The full README (architecture, how to add a company, limits) comes in step D5.3.

## Deployment checklist (all free, no card)

Order matters: database first, then the API, then the dashboard, then the daily job.
Never paste keys or the database URL into chat, commits or screenshots.

### 1. Neon (database)

1. Create a project, enable the extension: `CREATE EXTENSION IF NOT EXISTS vector;`
2. Copy the **direct** connection string (pooling off) and write it as
   `postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require`.
3. In PowerShell, for this session only (not in `.env`):
   ```powershell
   $env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require"
   ```
4. In `backend/`, one command per line:
   ```powershell
   uv run alembic upgrade head
   uv run python -m app.cli import-profile ../seed/kemira.profile.yaml
   uv run python -m app.cli onboard --company kemira
   ```
   `onboard` needs `GEMINI_API_KEY` (from `.env`) for the embeddings.
5. Set the report address on the live Settings page after step 3 below (the YAML only has a placeholder).

### 2. Render (API)

New Web Service from the GitHub repo: runtime Docker, **root directory `backend/`**, free instance, health check path `/api/health`. The container runs `alembic upgrade head` and then starts uvicorn on Render's `PORT`.

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | the Neon string from step 1 |
| `ADMIN_PASSWORD` | a long password you choose |
| `FRONTEND_ORIGIN` | the Vercel URL, no trailing slash (several origins: comma separated) |
| `DASHBOARD_URL` | the Vercel URL |
| `JOB_RUNNER` | `github` |
| `GITHUB_REPO` | `owner/repo` |
| `GITHUB_REF` | `main` |
| `GITHUB_DISPATCH_TOKEN` | fine-grained token for this repo only, **Actions: read and write**, nothing else |
| `GEMINI_API_KEY`, `GROQ_API_KEY` | free keys |
| `SMTP_USER`, `SMTP_APP_PASSWORD` | Gmail address and app password (for "Send test email") |
| `WIKIPEDIA_CONTACT` | your email or a URL |
| `TIMEZONE` | `Europe/Helsinki` |

Open `https://<render-app>.onrender.com/api/health` (the first call can take about a minute): `{"status":"ok","db":true}`.

### 3. Vercel (dashboard)

Import the repo, root directory `frontend/`, environment variable `VITE_API_URL=https://<render-app>.onrender.com`. `vercel.json` sends every route to `index.html`. Then put the Vercel URL into Render's `FRONTEND_ORIGIN` and `DASHBOARD_URL` and redeploy Render.

On the live site: log in as admin, open Settings, set the contact email(s), press "Send test email".

### 4. GitHub (daily job)

Repository secrets (Settings, Secrets and variables, Actions):
`DATABASE_URL`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` (may be empty), `SMTP_USER`, `SMTP_APP_PASSWORD`, `DASHBOARD_URL`, `WIKIPEDIA_CONTACT`.
Optional repository variables for model names: `GEMINI_PROBE_MODEL`, `GEMINI_INTERNAL_MODEL`, `GROQ_PROBE_MODEL`, `GROQ_INTERNAL_MODEL`, `OPENROUTER_MEMORY_MODEL` (empty = defaults from `backend/app/config.py`).

First run: Actions tab, workflow `agents`, Run workflow, job `daily`, company `kemira`. With an empty company the `daily` job runs every company with monitoring on. The schedule runs every day at 07:15 Helsinki time (it can start 5 to 30 minutes late).

### 5. Check

- The live dashboard shows Kemira's data and today's accuracy points.
- "Run now" on the live site starts a run in the GitHub Actions tab.
- The report email arrives (look in spam the first time).
- Tomorrow morning: a new run in the Actions tab, a new point on the chart.

### Free-tier facts

Render sleeps after 15 minutes (wakes in about 1 minute; the dashboard shows a banner). Neon suspends after 5 minutes idle (wakes in seconds). In a public repo, scheduled workflows are switched off after 60 days without a commit. Gmail allows 500 recipients per day.

## Local development

```powershell
docker compose up -d db
```

In `backend/`:

```powershell
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

In `frontend/`:

```powershell
npm run dev
```

The list of tested engines is `backend/config/engines.yaml` (path setting `ENGINES_FILE`).

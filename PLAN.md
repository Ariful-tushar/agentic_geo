# AnswerWatch: Build Plan

Goal: **Ax live and automatic by Friday 23 Oct**, all four agents live by **Sunday 25 Oct**, submit to Kemira on **Monday 26 Oct** (deadline Tue 27 Oct).

Rule: **finish and deploy one agent before starting the next.** If time runs out, cut from the end of the list (section "If you fall behind"), never Ax.

| Day | Date | Goal by the evening |
| --- | --- | --- |
| 0 | Tue 20 Oct | Accounts, keys, empty repo with these files (1 to 2 hours) |
| 1 | Wed 21 Oct | Foundation: database, Kemira profile imported, all AI connections and the fetcher work |
| 2 | Thu 22 Oct | RAG + **Ax complete** on the command line + API |
| 3 | Fri 23 Oct | Dashboard for Ax + emails + **deployed and running daily** |
| 4 | Sat 24 Oct | **Competitor agent** + alerts page, deployed |
| 5 | Sun 25 Oct | **FAQ agent** + **Support agent**, final test, README, deployed |
| 6 | Mon 26 Oct | GEO snapshot, video, CV, submit |

## How to run each step with Claude Code

1. Open the project folder in VS Code and start a **new** Claude Code session for every step.
2. Send:
   `Read CLAUDE.md, SPEC.md, PLAN.md and PROGRESS.md. Do step <ID> only. Show me your plan first and wait for my OK.`
3. Read the plan, answer its questions, say OK.
4. When it finishes, run the step's **Check** yourself.
5. Commit: `git add -A`, `git commit -m "<ID> <short name>"`, `git push`.

Every step lists **Build** (what Claude Code does), **You** (what you do), **Check** and **Done when**.

---

## Day 0 (Tue 20 Oct): setup, 1 to 2 hours

**You:**
1. Install or check: VS Code, Claude Code, Git, Docker Desktop (WSL 2), Python 3.12, uv, Node.js 20 LTS.
2. Keys (free): Gemini (Google AI Studio, **no billing**), Groq, OpenRouter (optional). Do not enable billing anywhere.
3. Gmail: turn on 2-step verification, create an **app password** (16 characters). Use a Gmail account you are happy to send demo emails from.
4. Create a **public** GitHub repo `answerwatch`, clone it, put in the root: `CLAUDE.md`, `SPEC.md`, `PLAN.md`, `PROGRESS.md`, `START_HERE.md`, and the folder `seed/` with `kemira.profile.yaml` and `public-questions.html`.
5. Create accounts (no card): Neon, Render, Vercel (sign in with GitHub). You will use them on Day 3.
6. Commit and push.

If you still have energy on Day 0, start D1.1.

---

## Day 1 (Wed 21 Oct): foundation

### D1.1 Scaffold
- **Build:** the repository layout from SPEC §4 (empty modules are fine), `docker-compose.yml` (§13), `.env.example` (§12), `.gitignore` (`.env`, `.venv/`, `node_modules/`, `dist/`, `__pycache__/`, `logs/`), `backend/pyproject.toml` with uv (FastAPI, uvicorn, pydantic, pydantic-settings, SQLAlchemy 2 async, psycopg[binary] 3, alembic, pgvector, httpx, selectolax, tenacity, pyyaml, langchain, langgraph, langchain-google-genai, langchain-groq, langchain-postgres, langchain-text-splitters, google-genai, groq, openai, aiosmtplib, pytest, pytest-asyncio, ruff), `app/config.py`, `app/db/session.py`, `app/main.py` with `GET /api/health`, Alembic with a first migration that only runs `CREATE EXTENSION IF NOT EXISTS vector`, `backend/Dockerfile`, `.github/workflows/ci.yml` (§14).
- **You:** copy `.env.example` to `.env`, fill in your keys.
- **Check:** `docker compose up -d db`; in `backend/`: `uv run alembic upgrade head`, `uv run uvicorn app.main:app --reload`; open http://localhost:8000/api/health and http://localhost:8000/docs; `uv run pytest -q`.
- **Done when:** health is OK, tests pass, `git status` does not list `.env`.

### D1.2 Database and profiles
- **Build:** every table from SPEC §6 as SQLAlchemy models + one Alembic migration; repository helpers; Pydantic profile schema with all validation rules (§5); `import-profile` and `validate-profile` commands (§11); questions are only created, never changed by a re-import. Tests for validation and for "importing twice creates no duplicates".
- **Check:** `uv run python -m app.cli validate-profile ../seed/kemira.profile.yaml`, then `import-profile ../seed/kemira.profile.yaml`; in the main folder: `docker compose exec db psql -U answerwatch -c "select kind, count(*) from questions group by kind;"` shows 18 fact and 6 generic.
- **Done when:** the Kemira profile is in the database.

### D1.3 AI layer
- **Build:** SPEC §7 completely: `backend/config/engines.yaml`; tested engines (`groq_web` with browser_search and citations, `gemini_memory`, `openrouter_memory`); our AI via LangChain with structured Pydantic output, Gemini → Groq fallback, dev mode; embeddings 768-dim normalised (check whether LangChain's Gemini embeddings support `output_dimensionality`; if not, write the wrapper); limits, retries, daily-stop detection, cache rules (never cache tested-engine answers or errors), `llm_calls` logging; `ping` command; `ping --save-fixture` saves raw responses to `tests/fixtures/`. Tests with fakes only.
- **Check:** `uv run python -m app.cli ping --save-fixture`.
- **Done when:** `groq_web` OK with at least 1 citation, `gemini_memory` OK, all internal roles OK, embeddings return 768 numbers, fixtures saved. Disabled engines show "disabled", not an error.

### D1.4 Fetcher and Wikipedia
- **Build:** polite fetcher and extractor (SPEC §1 rule 7, `pages` table, statuses, `PAGE_CACHE_DAYS`, never cache 403/429/5xx, robots.txt unreachable after retries = blocked for this run, `date_kind`); Wikipedia client (plain-text extract of a page by title); `fetch <url>` command. Tests with `httpx.MockTransport` and saved HTML.
- **Check:** `uv run python -m app.cli fetch https://www.kemira.com/company/` shows title "About us", status ok, a few thousand characters; run it again and it comes from the cache.
- **Done when:** fetch works and tests pass. Commit "Day 1 done".

---

## Day 2 (Thu 22 Oct): RAG and Ax

### D2.1 Knowledge base (RAG)
- **Build:** SPEC §8.1: `onboard` command (chunk, embed, store in PGVector collection `kb_<company>`, update `knowledge_sources` and `onboarding_status`, replace changed pages, remove gone pages) and `rag_answer` with verified quotes; `rag-ask` command. Tests with fake embeddings.
- **Check:** `uv run python -m app.cli onboard --company kemira`; `rag-ask --company kemira "How many employees does Kemira have?"` answers about 4,900 with a quote and a kemira.com link; `rag-ask --company kemira "What is Kemira's favourite colour?"` returns "not found in our sources".
- **Done when:** both answers behave as described.

### D2.2 Ax part 1: ask, judge, accuracy
- **Build:** the Ax LangGraph graph (SPEC §8.2) with nodes 1 to 5 and 10: start, ask_engines, ask_rag, judge (one call per engine, quote check, numeric override), daily_accuracy, finish. Resumable and idempotent. `run-ax` command with `--mode dev|live`. Tests: judge scoring, quote check, numeric override, accuracy maths, resume adds nothing.
- **Check:** `uv run python -m app.cli run-ax --company kemira --mode dev` (small sample), then `run-ax --company kemira --mode live`. Look at `daily_accuracy`: `docker compose exec db psql -U answerwatch -c "select engine, accuracy, n_questions from daily_accuracy;"`.
- **Done when:** today's accuracy exists for `groq_web`, `gemini_memory` and `rag`.

### D2.3 Ax part 2: why, mentions, competitor events, alerts
- **Build:** Ax nodes 6 to 9 (SPEC §8.2): find_why (cited pages, Wikipedia, own site, model memory, suggested fixes), mentions (alias matching + other names), competitor_events, alerts (needs a previous run; test with fixtures). Tests for each rule.
- **Check:** run `run-ax --company kemira --mode live` again (it resumes and fills the new nodes). Check `why_findings`, `mentions`, `competitor_events` have rows.
- **Done when:** at least one wrong answer has a readable "why", and competitor events exist for generic questions where a competitor was ahead or Kemira was missing.

### D2.4 API for Ax
- **Build:** SPEC §9 endpoints needed for Ax: health, engines, companies, company detail, accuracy trend/today/details, answer detail (with previous day's answer), alerts, runs, admin login, settings PATCH, jobs POST, companies POST and import; admin auth; JobRunner (`local` starts the CLI in the background, `github` calls workflow_dispatch). Tests for shapes, auth and the job runner (fake GitHub call).
- **Check:** open http://localhost:8000/docs and try each endpoint; the trend endpoint returns today's points.
- **Done when:** every Ax endpoint returns real Kemira data. Commit "Day 2 done".

---

## Day 3 (Fri 23 Oct): Ax dashboard, emails, deploy

### D3.1 Dashboard skeleton and Overview
- **Build:** `frontend/` with Vite + React + TypeScript + Tailwind + shadcn/ui + Recharts + TanStack Query + React Router; layout (top bar with company selector, admin login, monitoring switch, Run now, disclaimer; sidebar); waking-up banner; typed API client; **Overview** page (SPEC §10) with the one-chart accuracy trend (7/14/30 days) and today's cards; About page. Copy `seed/public-questions.html` to `frontend/public/demo/`. `vercel.json`, `frontend/Dockerfile`.
- **Check:** `npm run dev` in `frontend/`, open http://localhost:5173; Kemira's Overview shows today's points.
- **Done when:** Overview works on laptop and phone width.

### D3.2 Accuracy details, Settings, Setup
- **Build:** **Accuracy details** page with the side panel (why, citations, previous answer side by side); **Settings** page (switches, emails, read-only questions and competitors, sources status, runs, emails log, test email); **Setup** page (create profile form + Import YAML, onboarding status polling).
- **Check:** click through every page; switch monitoring off and on; import the YAML again (it must not duplicate questions).
- **Done when:** a recruiter could understand Ax from these pages.

### D3.3 Emails and the daily command
- **Build:** SPEC §8.6: Gmail SMTP sender, HTML + text templates, daily report, alert email, `send-report`, `send-alerts`, `send-test-email`, email log; the `daily` command (§11) running Ax → competitor (stub until Day 4) → FAQ (stub until Day 5) → alerts email → daily report, each step isolated so one failure does not stop the rest.
- **Check:** `uv run python -m app.cli send-test-email --company kemira` arrives in your inbox; `uv run python -m app.cli daily --company kemira` runs and sends the report.
- **Done when:** both emails arrive and look good.

### D3.4 Deploy Ax (live)
- **Build:** `.github/workflows/agents.yml` (SPEC §14); production settings for Render (port, health path, CORS), Neon SSL with psycopg; deployment checklist in README.
- **You:** follow SPEC §15 step by step: Neon (migrate, import profile, onboard), Render, Vercel, GitHub secrets; run the `agents` workflow manually (job `daily`, company `kemira`).
- **Check:** the live dashboard shows Kemira's data; "Run now" from the live site starts a GitHub run; the report email arrives.
- **Done when:** **Ax is live and runs by itself tomorrow morning.** Commit "Day 3 done, Ax live".

---

## Day 4 (Sat 24 Oct): Competitor agent

First thing: check that the scheduled run happened this morning (GitHub Actions tab, new dot on the chart, report email).

### D4.1 Competitor agent
- **Build:** SPEC §8.3 as a LangGraph graph; `run-competitor` command; plug it into `daily`; API endpoints competitors/events and competitors/summary. Tests: no citations → nothing found; evidence-only report.
- **Check:** `uv run python -m app.cli run-competitor --company kemira`; events now have reports.
- **Done when:** every event has a report or "Nothing found by the competitor monitor".

### D4.2 Competitors and Alerts pages, deploy
- **Build:** **Competitors** page and **Alerts** page (SPEC §10); add competitor events and alerts to the daily report and alert email.
- **Check:** pages show real data; emails include the new sections.
- **Done when:** deployed (push → Render and Vercel redeploy) and live. Commit "Day 4 done".

---

## Day 5 (Sun 25 Oct): FAQ agent, Support agent, finish

### D5.1 FAQ agent
- **Build:** SPEC §8.4; `run-faq` command; plug into `daily`; API faq/questions and faq/drafts; **FAQ** page with Copy buttons. Set Kemira's `faq_source_urls` to the live demo page URL. Tests: extraction, dedupe, relevance, grounded drafts.
- **Check:** run `run-faq`; add one new question to `frontend/public/demo/public-questions.html`, deploy, run again: only the new question is added.
- **Done when:** FAQ page shows questions and drafts.

### D5.2 Support agent (AI-readiness check)
- **Build:** SPEC §8.5 as a LangGraph graph; API POST/GET readiness (background task + status); `readiness` command; **AI-readiness** page.
- **Check:** `cd backend`; `uv run ruff check .`; `uv run pytest -q tests/test_readiness.py`; `cd ../frontend`; `npm run build`. After deployment, run a check on `https://www.kemira.com/company/` from the live site; result shows X of N, missing facts and 3 suggestions.
- **Done when:** code and focused tests pass; live check remains for deployment.

### D5.3 Final check and README
- **Build:** run all tests and the frontend build, fix problems; README (what it is, live link, screenshots placeholders, architecture diagram, how to add a company, limits, disclaimer); update About page.
- **You:** click through the live site as a recruiter would; note anything confusing and fix it.
- **Done when:** everything works live. Commit "Day 5 done, all agents live".

---

## Day 6 (Mon 26 Oct): submit

1. Check this morning's scheduled run and email.
2. Screenshots for the README.
3. One-page GEO snapshot from the real data (ask Claude in chat for help).
4. 3-minute video: problem (20 s) → Overview trend (40 s) → a wrong answer and its "why" (40 s) → competitor report (30 s) → FAQ and AI-readiness (30 s) → "works for any company" (20 s).
5. Tailored CV.
6. Submit on kemira.com/careers. Tue 27 Oct is buffer.

---

## If you fall behind

Cut in this order:
1. `openrouter_memory` engine (keep it disabled).
2. Competitors summary chart (keep the history table).
3. Alerts page (keep alerts in the email).
4. Support agent.
5. FAQ agent.

Never cut: Ax, the trend chart, the details panel with "why", the daily schedule, the daily report email.

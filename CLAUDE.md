# CLAUDE.md: rules for building AnswerWatch

## At the start of every session
1. Read SPEC.md (what to build), PLAN.md (the steps) and PROGRESS.md (where we are).
2. Work ONLY on the step the user names (for example D2.2). Never start the next step.
3. Show a short plan first (files you will create or change, decisions you need) and wait for the user's OK.

## While working
- Follow SPEC.md exactly: folder names, table and column names, CLI commands, API paths, page names.
- If something in the spec is unclear, missing or seems wrong, ask. Never change the design silently. Record every agreed change in PROGRESS.md under "Decisions".
- Stack: Python 3.12, uv, FastAPI, Pydantic v2, SQLAlchemy 2 async with psycopg 3, Alembic, PostgreSQL + pgvector, LangChain + LangGraph, langchain-postgres. Frontend: React, Vite, TypeScript, Tailwind, shadcn/ui, Recharts, TanStack Query, React Router.
- When you are unsure about an SDK method, a response format or a model name, check the installed package source or the official docs page; do not guess. Tell the user which page you checked.
- Model names, keys and limits come only from settings (.env). Never hard-code or print keys. Never commit .env.
- Every AI output is parsed into a Pydantic model. Tested-engine answers are never cached; errors are never cached.
- Agents are idempotent and resumable: a second run of the same command adds nothing that already exists.
- Tests never call real AI APIs or the internet: use fakes, fixtures and httpx.MockTransport.
- Use `--mode dev` for any trial run unless the user says "live".
- Keep functions small and typed. Prefer clear code over clever code. The user is a strong Python developer and a beginner in frontend: explain frontend choices briefly.
- Windows + PowerShell: give commands that work in PowerShell (no `&&` chaining in instructions; one command per line).
- Write every project file as UTF-8 without BOM (code, Markdown, YAML, SQL). Never use a legacy encoding such as Windows-1252.

## At the end of every step
1. Run `uv run ruff check .` and `uv run pytest -q` in backend/ (and `npm run build` in frontend/ for frontend steps). Fix failures.
2. Show the results and the exact commands the user should run for the step's **Check** in PLAN.md.
3. Update PROGRESS.md: tick the step, short log entry (what was built, decisions, open issues), next step.
4. Update everything.md (see below).
5. Suggest a commit message starting with the step ID.

## everything.md (the user's personal build diary)
- Keep a file `everything.md` in the repo root. Create it if missing. It is for the user only: it must be listed in `.gitignore` and never committed.
- Purpose: the user reads it later to understand the project. Write for a reader who has forgotten everything: plain, simple words, no jargon without a few words of explanation.
- After every step, add a heading with the step ID and date, then a numbered list (1. 2. 3., restarting at 1 under each step heading), one item per script/file you created or changed, in this form:
  `` 1. Created `path/to/file.py`. Inside: what the code in it does, in easy words. Reason: why the project needs it, in easy words. ``
  Example: `` 1. Created `backend/alembic/env.py`. Inside: the setup Alembic needs to connect to the database and run migrations. Reason: Alembic builds and changes tables step by step; without this file it does not know which database to use. ``
  For changed files use "Changed `path`." instead of "Created".
- Every item must say which file, what is inside, and why. Keep each item short (2 or 3 sentences).
- Only important things: new modules, key functions, migrations, config, workflows, pages, and design decisions. Skip trivial edits, formatting, `__init__.py` files and test boilerplate (one item for a whole test file is enough).
- Never rewrite or delete earlier entries; only add new ones at the end.

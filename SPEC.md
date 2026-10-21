# AnswerWatch: Product and Technical Spec (MVP)

AnswerWatch monitors what AI assistants say about a company, every day, automatically.
It has four agents:

| Agent | Job in one line |
| --- | --- |
| **Ax** (main agent) | Every morning asks the AI engines the company's fixed questions, scores each answer against the company's correct answers, finds why wrong answers are wrong, and saves daily accuracy |
| **Competitor agent** | When a competitor is named before the company, or the company is not named at all, finds why from the sources the AI cited and writes a 2 to 3 line report |
| **FAQ agent** | Collects new public questions about the company's niche (MVP: from a demo HTML page) and writes draft FAQ answers using only the company's own information |
| **Support agent** (AI-readiness check) | For one page URL, checks how many of the company's questions an AI could answer from that page, and gives 3 concrete suggestions |

Plus: answer-change alerts, a daily report email, an alert email, and a dashboard.

Kemira is the first profile. The product works for any company: each company is a **profile** with its own data. In this MVP every created profile is selectable in the dashboard (showcase mode). Data is always stored per company, so real logins can be added later.

---

## 1. Rules of the MVP (do not change without asking)

1. **Questions are fixed** after a profile is created. No editing of questions in the MVP.
2. **Nothing is published** to the company's website. FAQ drafts and suggestions are shown in the dashboard; a human copies them if they want.
3. **No scraping of competitor websites.** The competitor agent only reads the pages the AI engines cited.
4. **One run per engine per question per day.** Accuracy per engine per day = average score of the fact questions.
5. **Zero budget.** Only free tiers. Never require a paid key. Paid engines can be added later.
6. **Agents run as Python commands** (CLI). GitHub Actions runs them daily; the API only reads data, saves settings, and triggers jobs.
7. **Polite fetching**: robots.txt respected, at most 1 request per second per domain, extracted text stored (never full HTML).
8. Every page shows: "Independent demo, not affiliated with the selected company."

---

## 2. Tech stack

| Area | Choice | Notes |
| --- | --- | --- |
| Language | Python 3.12 | |
| Package manager | uv | Same commands locally and in GitHub Actions |
| API | FastAPI | Auto docs at `/docs` |
| Schemas | Pydantic v2, pydantic-settings | Every AI output is validated with a Pydantic model |
| Database | PostgreSQL 16 + pgvector | Local: Docker. Live: Neon free |
| DB driver | **psycopg 3** (`postgresql+psycopg://`) | One driver for SQLAlchemy and langchain-postgres |
| ORM / migrations | SQLAlchemy 2 (async) + Alembic | |
| Agents | **LangChain + LangGraph** | Each agent is a LangGraph graph of small nodes |
| Our AI (judge, RAG, why, summaries, drafts) | Gemini free tier via `langchain-google-genai`; fallback Groq via `langchain-groq` | Structured output with Pydantic |
| AI engines being tested | Called with their **own SDKs** (`groq`, `google-genai`, `openai` client for OpenRouter) | We need the exact raw answer and citations |
| Embeddings | `gemini-embedding-001`, 768 dimensions, normalised | Via LangChain if it supports `output_dimensionality`; otherwise a small LangChain `Embeddings` wrapper around `google-genai` |
| Vector store (RAG) | pgvector via `langchain-postgres` (`PGVector`) | One collection per company: `kb_<company_id>` |
| Fetching | httpx + selectolax | Polite fetcher, page cache |
| Wikipedia | Wikipedia REST/Action API (free, official) | For "why" checks when an answer has no citations |
| Frontend | React + Vite + TypeScript, Tailwind + shadcn/ui, Recharts, TanStack Query, React Router | |
| Email | Gmail SMTP with an app password (`smtplib` / `aiosmtplib`) | 500 recipients/day limit |
| Scheduler | GitHub Actions (`schedule` + `workflow_dispatch`) | Daily ~07:15 Europe/Helsinki |
| Hosting | Vercel (frontend), Render free web service (API, Docker), Neon (DB) | All free, no card |
| Local dev | Docker Compose (db always; api + web optional) | Docker Desktop with WSL 2 on Windows |
| Quality | pytest, pytest-asyncio, ruff | Tests never call real AI APIs |

**Model names come only from `.env`** (they change often):

```
GEMINI_PROBE_MODEL=gemini-3.8-flash          # tested engine "gemini_memory" (no web search on free tier)
GEMINI_INTERNAL_MODEL=gemini-3.5-flash-lite  # our AI: judge, rag, why, summaries, drafts
GEMINI_EMBED_MODEL=gemini-embedding-001
EMBEDDING_DIM=768
GROQ_PROBE_MODEL=openai/gpt-oss-120b         # tested engine "groq_web" with browser_search
GROQ_INTERNAL_MODEL=openai/gpt-oss-120b      # fallback and dev mode for our AI
OPENROUTER_MEMORY_MODEL=nvidia/nemotron-3.5-super-vl:free   # optional tested engine
```

---

## 3. Architecture

```
           GitHub Actions  (daily ~07:15 Helsinki, and "run now" via workflow_dispatch)
                 │  runs:  python -m app.cli daily | onboard | run-ax | run-competitor | run-faq
                 ▼
   ┌───────────────────────── Agents (LangGraph) ─────────────────────────┐
   │  Ax  →  Competitor agent  →  FAQ agent  →  alerts + emails             │
   │  Support agent runs on demand from the dashboard (API background task) │
   └──────────────────────────────────┬────────────────────────────────────┘
                                      │ read/write
                                      ▼
                       PostgreSQL + pgvector  (Neon live, Docker local)
                                      ▲
                                      │ read data, save settings, trigger jobs
   React dashboard (Vercel)  ──────→  FastAPI (Render)
```

- Agents never call each other directly. Each reads and writes the database. The `daily` command runs them in order.
- The API triggers jobs through a **JobRunner**: `local` (starts the CLI command as a background subprocess, for development) or `github` (calls the GitHub `workflow_dispatch` API).
- All calls to AI go through `app/llm/`, which handles rate limits, retries, caching, cost logging and fallbacks.

---

## 4. Repository layout

```
answerwatch/
  CLAUDE.md  SPEC.md  PLAN.md  PROGRESS.md  START_HERE.md  README.md
  docker-compose.yml
  .env.example
  .github/workflows/
    ci.yml                  # tests on every push (Postgres+pgvector service container)
    agents.yml              # daily schedule + workflow_dispatch jobs
  seed/
    kemira.profile.yaml     # Kemira profile to import (questions, expected answers, competitors, sources)
    public-questions.html   # demo "public questions" page for the FAQ agent
  backend/
    pyproject.toml  Dockerfile  alembic.ini  alembic/versions/
    config/engines.yaml     # tested AI engines (global for all companies); path = ENGINES_FILE setting
    app/
      main.py               # FastAPI app, routers, CORS
      config.py             # settings (pydantic-settings)
      cli.py                # all commands (section 11)
      db/      session.py  models.py  repo.py
      schemas/ profile.py  agents.py  api.py
      profiles/ loader.py   # YAML/JSON profile -> validated -> DB
      llm/
        engines.py          # tested engines: ask(question) -> EngineAnswer (text + citations)
        groq_engine.py  gemini_engine.py  openrouter_engine.py
        internal.py         # our AI via LangChain: structured(prompt, schema), with fallback
        embeddings.py       # 768-dim normalised embeddings
        cache.py  limits.py  usage.py
      fetch/   fetcher.py  extract.py  wikipedia.py
      kb/      builder.py  retriever.py        # RAG (langchain-postgres PGVector)
      agents/
        ax/        graph.py  nodes.py  judge.py  why.py  mentions.py  alerts.py
        competitor/ graph.py  nodes.py
        faq/       graph.py  nodes.py
        support/   graph.py  nodes.py
      jobs/    runner.py  daily.py         # JobRunner (local | github), daily orchestration
      emails/  smtp.py  templates.py  report.py  alert.py
      api/     routes_*.py  auth.py
    tests/
      fixtures/                            # saved raw engine responses, saved HTML pages
      test_*.py
  frontend/
    package.json  vite.config.ts  index.html  Dockerfile  vercel.json
    public/demo/public-questions.html      # copy of seed/public-questions.html, served live
    src/
      api/ client.ts  types.ts
      components/ ...                      # shadcn/ui components + our own
      pages/ Overview.tsx  Accuracy.tsx  Competitors.tsx  Alerts.tsx  Faq.tsx
             Readiness.tsx  Settings.tsx  Setup.tsx  About.tsx
```

---

## 5. Profiles (one per company)

A profile is created once (from the Setup page, or by importing a YAML file) and contains:

| Field | Example (Kemira) | Notes |
| --- | --- | --- |
| `id` | `kemira` | slug, unique |
| `name`, `aliases` | Kemira; Kemira Oyj, Kemira Group | aliases used for mention matching |
| `domains` | kemira.com | to recognise the company's own pages in citations |
| `wikipedia_title` | Kemira | for "why" checks |
| `contact_emails` | the responsible person's email | daily report + alerts |
| `competitors` | Ecolab (aliases: Nalco Water; domain ecolab.com), Solenis, SNF, Kurita | name, aliases, domains |
| `knowledge_sources` | ~10 to 40 public URLs on the company's site | RAG builds from these |
| `fact_questions` | "Who is Kemira's CEO?" + expected answer "Antti Salminen" | have a correct answer; scored |
| `generic_questions` | "Who are the leading suppliers of water treatment chemicals in Europe?" | no correct answer; used for competitor monitoring |
| `faq_source_urls` | the demo public-questions page URL | FAQ agent reads these |
| `monitoring_enabled` | true | daily job skips the company when false |
| `emails_enabled` | true | report and alert emails on/off |

Fact question fields: `code` (Q01...), `text`, `expected_answer` (text), optional `expected_value` (number), optional `tolerance` (number), optional `unit`, `expected_source_url` (where the truth comes from).

Validation (Pydantic, clear errors): unique ids and codes; at least 1 fact question; every fact question has an expected answer; numbers only with `expected_value`; URLs valid; at least one competitor; emails valid.

`onboarding_status`: `pending` → `building` → `ready` (or `failed` with message). Building = fetching the knowledge sources and creating the RAG collection.

---

## 6. Database tables

All tables have `created_at`. Use UUID primary keys unless noted. Every company-owned table has `company_id`.

| Table | Main columns | Unique / notes |
| --- | --- | --- |
| `companies` | id (text PK), name, aliases text[], domains text[], wikipedia_title, contact_emails text[], faq_source_urls text[], monitoring_enabled bool, emails_enabled bool, onboarding_status, onboarding_error | |
| `competitors` | id, company_id, name, aliases text[], domains text[] | (company_id, name) |
| `questions` | id, company_id, code, kind (`fact`/`generic`), text, expected_answer, expected_value numeric, tolerance numeric, unit, expected_source_url | (company_id, code) |
| `knowledge_sources` | id, company_id, url, status, last_built_at | (company_id, url) |
| `pages` | id, url, final_url, domain, title, h1, text, published_date, date_kind (`published`/`modified`), status (`ok`/`blocked_by_robots`/`skipped_non_html`/`http_error`/`fetch_error`), http_status, fetched_at | url unique |
| `runs` | id, company_id, kind (`ax`/`competitor`/`faq`/`daily`/`onboard`), run_date (date, Helsinki), trigger (`schedule`/`manual`), status (`running`/`completed`/`partial`/`failed`/`skipped`), started_at, finished_at, details jsonb | (company_id, kind, run_date) |
| `answers` | id, run_id, company_id, question_id, engine (engine id or `rag`), asked_at, text, raw_json jsonb, latency_ms, error | (run_id, question_id, engine) |
| `citations` | id, answer_id, url, title, domain, owner (`company`/`competitor`/`third_party`), competitor_id | (answer_id, url) |
| `scores` | id, answer_id, verdict (`correct`/`partial`/`wrong`/`no_answer`), score (1, 0.5, 0), reason, quote, quote_verified bool, method (`judge`/`numeric`) | answer_id unique |
| `daily_accuracy` | id, company_id, run_id, run_date, engine, accuracy (0..1), n_questions, n_correct, n_partial, n_wrong, n_no_answer | (company_id, run_date, engine) |
| `why_findings` | id, answer_id, source_type (`cited_page`/`wikipedia`/`own_site`/`model_memory`/`not_answered`/`unknown`), source_url, evidence_quote, explanation, suggested_fix | answer_id unique |
| `mentions` | id, answer_id, brand_type (`company`/`competitor`/`other`), competitor_id, name, rank (1 = named first) | (answer_id, name) |
| `competitor_events` | id, company_id, run_date, answer_id, question_id, engine, kind (`competitor_ahead`/`company_missing`), competitors jsonb ([{name, rank}]), company_rank (null if missing), status (`new`/`analysed`), report_status (`found`/`nothing_found`), report, analysed_at | answer_id unique |
| `alerts` | id, company_id, run_date, kind (`score_drop`/`company_dropped`/`competitor_overtook`/`score_improved`), severity (`warning`/`info`), engine, question_id, before_answer_id, after_answer_id, summary, emailed bool | (company_id, run_date, kind, engine, question_id) |
| `public_questions` | id, company_id, source_url, text, normalized, first_seen_at, relevant bool, relevance_reason | (company_id, normalized) |
| `faq_drafts` | id, company_id, public_question_id, question, answer, source_urls jsonb | public_question_id unique |
| `readiness_checks` | id, company_id, url, status (`queued`/`running`/`done`/`failed`), n_questions, n_answered, n_partial, results jsonb, missing jsonb, suggestions jsonb, error | |
| `email_log` | id, company_id, kind (`daily_report`/`alert`/`test`), recipients text[], subject, status, error, sent_at | |
| `llm_calls` | id, role, provider, model, prompt_hash, tokens_in, tokens_out, latency_ms, cost_usd, cached bool, error | |
| `llm_cache` | prompt_hash (PK), provider, model, response_json | |

RAG chunks live in the tables managed by `langchain-postgres` (collection `kb_<company_id>`), with metadata: `url`, `title`, `published_date`, `date_kind`, `chunk_index`.

---

## 7. AI layer (`app/llm/`)

### 7.1 Tested engines (`backend/config/engines.yaml`)

```yaml
engines:
  - id: groq_web
    provider: groq
    model_env: GROQ_PROBE_MODEL
    web_search: true          # tools=[{"type":"browser_search"}], reasoning_effort "low"
    enabled: true
    label: "Open GPT model on Groq, with web search"
  - id: gemini_memory
    provider: gemini
    model_env: GEMINI_PROBE_MODEL
    web_search: false         # Google Search grounding is not on Gemini's free tier
    enabled: true
    label: "Gemini, model memory only"
  - id: openrouter_memory
    provider: openrouter
    model_env: OPENROUTER_MEMORY_MODEL
    web_search: false
    enabled: false            # optional; free models are limited to 50 requests/day
    label: "Free OpenRouter model, memory only"
```

Plus the pseudo-engine **`rag`** ("Our RAG on the company's own pages"), scored the same way.

Engine interface: `ask(question_text) -> EngineAnswer(text, citations[url,title], model, tokens_in, tokens_out, latency_ms, raw_json)`.

- The prompt to a tested engine is **only the question text**. No system prompt that mentions the company.
- **Groq**: `tools=[{"type":"browser_search"}]`, `tool_choice` as the docs require, `reasoning_effort="low"`, max output tokens from settings (default 800). Citations: parse URLs from the response (inline markers and any URLs); verify the exact structure against the saved fixture.
- **Gemini memory**: normal generation, no tools.
- **OpenRouter**: OpenAI-compatible client, `base_url=https://openrouter.ai/api/v1`; turn reasoning off or low; a 402 means no credit.
- Engines that fail (quota, unavailable) are **skipped with a warning** recorded in `runs.details`; the run continues.

### 7.2 Our AI (`internal.py`, LangChain)

`structured(role, prompt, schema)` returns a validated Pydantic object.
- Live mode: `ChatGoogleGenerativeAI(GEMINI_INTERNAL_MODEL)`; if Gemini is rate limited or its daily limit is reached, fall back to `ChatGroq(GROQ_INTERNAL_MODEL)` with a warning.
- Dev mode (`--mode dev`): Groq for all internal roles; tiny samples.
- On a validation error: retry once with the error appended.
- Roles: `judge`, `why`, `extract`, `summarise`, `draft`, `rag`, `readiness`.

### 7.3 Limits, cache, usage

- One asyncio semaphore per provider (settings). Groq: calls one at a time plus a tokens-per-minute budget (`GROQ_TOKENS_PER_MINUTE=8000`).
- Retries with exponential backoff on 429 and 5xx. Read rate-limit headers: if the wait is longer than 60 seconds, treat it as a **daily stop**: mark that provider exhausted for this run and keep the run resumable.
- **Cache** (`llm_cache`): only for internal roles and embeddings (key = provider + model + prompt + schema). **Never cache tested-engine answers**, and never cache errors or empty answers.
- Log every call in `llm_calls` (cost 0 on free tiers).

### 7.4 Embeddings

`gemini-embedding-001`, `output_dimensionality=768`, `task_type` `RETRIEVAL_DOCUMENT` for chunks and `RETRIEVAL_QUERY` for questions, then **normalise** each vector. Batch requests. Cached.

---

## 8. Agents

All agents are LangGraph graphs. Each node does one thing, writes to the database, and is **idempotent** (running again does not duplicate rows; work already stored is skipped). This makes every run **resumable**: if a run stops halfway (for example Groq's daily limit), running the same command again later finishes it.

### 8.1 Onboarding (knowledge base build)

`onboard --company <id>`: fetch every knowledge source with the polite fetcher → split into chunks (about 1,600 characters, overlap 240, cut at paragraph boundaries) → embed as "page title + chunk text" → store in PGVector collection `kb_<id>` with metadata → set `onboarding_status=ready`. Re-running replaces chunks of changed pages and removes chunks of pages that left the list or now return 404/410.

`rag_answer(company, question)`: retrieve the top 6 chunks → our AI answers using **only** those chunks, referring to them as C1..C6 → return `answer` (or "not found in our sources"), quotes (each must appear word for word in its chunk, otherwise dropped), source URLs. When chunks disagree, prefer the newest page.

### 8.2 Ax (`run-ax --company <id>`)

Graph nodes, in order:

1. **start**: create or resume today's `runs` row (kind `ax`); skip if `monitoring_enabled` is false and the trigger is the schedule.
2. **ask_engines**: for every enabled engine and every question (fact + generic): ask, store `answers` + `citations` (owner = company if the domain matches, competitor if it matches a competitor domain, else third_party). Skip pairs already stored today.
3. **ask_rag**: for every fact question, store the RAG answer as engine `rag`.
4. **judge** (fact questions only): **one judge call per engine** with all that engine's fact Q&A pairs. For each item the judge returns `verdict` (`correct`/`partial`/`wrong`/`no_answer`), a `quote` (the exact sentence from the answer that the verdict is based on) and a `reason` (max 25 words).
   - Score: correct 1, partial 0.5, wrong 0, no_answer 0.
   - Code check: the quote must appear in the answer text (after whitespace normalisation). If not, ask the judge once more for that item; if still not found, keep the verdict with `quote_verified=false` (shown with a warning icon).
   - Numeric questions (`expected_value` set): code extracts numbers from the answer ("4,900", "4 900", "about 5,000", "2.8 billion") and decides correct or wrong using `tolerance`, overriding the judge (`method=numeric`).
5. **daily_accuracy**: for each engine (including `rag`): accuracy = average score over fact questions answered today; store counts.
6. **find_why** (fact answers with verdict `wrong` or `partial`):
   - If the answer has citations: fetch the cited pages (max 5) and look for the wrong claim: for numbers search several formats; for text ask our AI with short page snippets. Result: `source_type=cited_page`, `source_url`, `evidence_quote` (must appear in the page text), `explanation`.
   - If no citations: check the company's Wikipedia page (Wikipedia API) and the company's own pages (RAG). Found → `wikipedia` or `own_site`; else `model_memory` ("answer from model memory, no sources to check").
   - `no_answer` → `not_answered` ("the AI did not give this fact").
   - `suggested_fix` by type: wikipedia → "Request an update on the Wikipedia Talk page with these official sources: …"; own_site → "Update this page: …"; cited_page (third party) → "Ask the publisher to correct it, or publish the fact clearly on an official page"; model_memory / not_answered → "Publish this fact clearly on an official page so AI search can find it".
7. **mentions** (generic questions): find the company and competitors in each answer by alias matching (case-insensitive, word boundaries, longest alias first); rank = order of first appearance. Ask our AI (one call per engine) for other company names; store as `other`.
8. **competitor_events**: for each generic answer: if the company is not mentioned → `company_missing` (with the competitors that were mentioned); else if any competitor has a better rank → `competitor_ahead`. Status `new`.
9. **alerts**: compare with the previous completed Ax run for the same engine and question:
   - `score_drop` (warning): the fact score went down
   - `score_improved` (info)
   - `company_dropped` (warning): the company was mentioned last time, not now
   - `competitor_overtook` (warning): a competitor is ahead now but was not last time
   Each alert keeps the before and after answer ids (for side-by-side text).
10. **finish**: status `completed` (or `partial` when an engine was skipped), store a summary in `details`.

### 8.3 Competitor agent (`run-competitor --company <id>`)

For each `competitor_events` row with status `new`:
1. Collect the citations of that answer. If none: report_status `nothing_found`, report "Nothing found by the competitor monitor: the AI gave no sources (model memory)."
2. Fetch the cited pages (polite fetcher). For each page note: does it mention the competitor(s)? the company? which one first?
3. Our AI writes a **2 to 3 line report** using **only** this evidence, e.g. "The AI cited a trade article listing Ecolab and SNF as top coagulant suppliers; Kemira is not mentioned in it." If nothing relevant is found: "Nothing found by the competitor monitor."
4. Save report, report_status, status `analysed`.

### 8.4 FAQ agent (`run-faq --company <id>`)

1. Fetch each `faq_source_urls` page (force refresh, polite).
2. Extract questions: elements with class `question` (demo page); fallback: our AI extracts question sentences from the text.
3. Normalise (lowercase, trim, remove punctuation) and skip questions already stored; also skip near-duplicates (embedding similarity > 0.92).
4. Relevance (one AI call for all new questions): is it related to the company's industry, products or region? Store `relevant` + reason.
5. For relevant new questions: draft an FAQ answer (60 to 120 words) using **only** RAG chunks and the company's expected answers, mention the company naturally, list source URLs. Store in `faq_drafts`.

### 8.5 Support agent: AI-readiness check (on demand)

Input: a page URL (admin). Runs as an API background task; the UI polls the status.
1. Fetch the page (force refresh).
2. One AI call: answer every fact question using **only** this page's text, or "not on this page".
3. Score those answers with the same judge logic as Ax.
4. Result: "This page answers X of N questions (Y partly)", list of missing facts (questions not answered), and **3 concrete suggestions** grounded in the expected answers (for example: "Add the employee number to the first paragraph", "Use a title that answers 'What does Kemira do?'").
5. Save in `readiness_checks`.

### 8.6 Emails

- **Daily report** (after the daily run, if `emails_enabled`): date; accuracy per engine today vs yesterday (with + / −); RAG accuracy; number of wrong answers and the top 3 "why" findings; competitor events count and the 2 newest reports; alerts count; new public questions and FAQ drafts; link to the dashboard.
- **Alert email**: only if there are new `warning` alerts; one email with all of them (summary + link); mark `emailed=true`.
- Gmail SMTP (`smtp.gmail.com`, port 465 SSL or 587 STARTTLS) with an app password. HTML + plain text. Log every send in `email_log`.
- `send-test-email --company <id>` for checking setup.

---

## 9. API (FastAPI)

Read endpoints are public. Write endpoints need header `X-Admin-Token` equal to `ADMIN_PASSWORD`.

| Method | Path | Returns / does |
| --- | --- | --- |
| GET | `/api/health` | status, db ok |
| GET | `/api/engines` | engines with labels and web_search flag, plus `rag` |
| GET | `/api/companies` | profiles: id, name, onboarding_status, monitoring_enabled, last run |
| GET | `/api/companies/{id}` | profile, competitors, questions, sources, settings |
| GET | `/api/companies/{id}/accuracy/trend?days=7` | [{date, engine, accuracy}] for the line chart |
| GET | `/api/companies/{id}/accuracy/today` | per engine: today, yesterday, delta |
| GET | `/api/companies/{id}/accuracy/details?from&to&engine` | questions × dates matrix of {score, verdict, answer_id} |
| GET | `/api/answers/{id}` | question, expected answer, answer text, score, reason, quote, citations, why finding, previous day's answer |
| GET | `/api/companies/{id}/competitors/events?days&engine` | event history with reports |
| GET | `/api/companies/{id}/competitors/summary?days` | per day: company mentioned in X of N generic answers, per engine |
| GET | `/api/companies/{id}/alerts?days` | alerts with before/after answer ids |
| GET | `/api/companies/{id}/faq/questions` | public questions found (history) |
| GET | `/api/companies/{id}/faq/drafts` | FAQ drafts |
| GET | `/api/companies/{id}/readiness` | readiness check history |
| GET | `/api/readiness/{id}` | one check with results |
| GET | `/api/companies/{id}/runs?limit=20` | recent runs with status |
| GET | `/api/companies/{id}/emails?limit=20` | email log |
| POST | `/api/admin/login` | checks the password |
| POST | `/api/companies` | create profile (JSON); starts `onboard` job |
| POST | `/api/companies/import` | create profile from uploaded YAML; starts `onboard` job |
| PATCH | `/api/companies/{id}/settings` | monitoring_enabled, emails_enabled, contact_emails |
| POST | `/api/companies/{id}/jobs` | body {job: `daily`/`ax`/`competitor`/`faq`/`onboard`} → triggers via JobRunner |
| POST | `/api/companies/{id}/readiness` | body {url} → starts a check, returns id |
| POST | `/api/companies/{id}/test-email` | sends a test email |

All responses are Pydantic models. CORS allows `FRONTEND_ORIGIN`. Errors are clear JSON messages.

---

## 10. Dashboard (React)

**Top bar**: company selector (only created profiles), monitoring on/off switch and "Run now" button (admin only), admin login button, disclaimer. **Sidebar**: the pages below. If the free API is waking up (health takes > 3 s), show: "Waking up the demo server, about 1 minute on the free tier." and retry.

| Page | Contents |
| --- | --- |
| **Overview** | Line chart: accuracy per day for every engine and RAG in **one chart**, buttons 7 / 14 / 30 days. Cards: today's accuracy per engine with change vs yesterday. Latest alerts (5). Last run time and status. |
| **Accuracy details** | Engine tabs. Table: rows = fact questions, columns = days, cells coloured (green 1, amber 0.5, red 0, grey no answer or error). Click a cell → side panel: question, expected answer, the AI's answer, verdict and reason, quote, citations (links), **why** finding and suggested fix, previous day's answer side by side. |
| **Competitors** | Small chart: company mentioned in X of N generic answers per day, per engine. History table: date, engine, question, who was ahead or "company not mentioned", and the competitor agent's 2 to 3 line report (or "Nothing found by the competitor monitor"). |
| **Alerts** | List of change alerts; click → yesterday's and today's answer side by side. |
| **FAQ** | Section 1: public questions found (date, source, relevant yes/no, reason). Section 2: FAQ drafts (question, answer, sources) with a Copy button. |
| **AI-readiness** | Admin: enter a URL → run check → result: X of N answered, per-question table (answered / partly / missing), missing facts, 3 suggestions. History list. |
| **Settings** | Monitoring switch, emails switch, contact emails, competitors and questions (read-only), knowledge sources and their status, last runs, last emails, "Send test email". |
| **Setup** (admin) | Create a profile: form (name, aliases, domains, Wikipedia title, emails, competitors, knowledge source URLs, fact questions with expected answers, generic questions, FAQ source URLs) **or** "Import YAML". After saving: onboarding status ("Building knowledge base…", then "Ready"). |
| **About** | How it works (4 agents), how accuracy is scored, which engines use web search vs memory, limits, disclaimer. |

Design: clean white layout, one accent colour, shadcn/ui cards and tables, readable on a phone. No business logic in the frontend; the API returns ready numbers.

---

## 11. CLI commands (`python -m app.cli <command>`)

| Command | Does |
| --- | --- |
| `import-profile <file.yaml>` | validate and create/update a profile (questions are only created, never changed) |
| `validate-profile <file.yaml>` | validation only |
| `ping` | tests every engine and every internal role once, prints a table (no cache) |
| `fetch <url>` | fetches one page and prints title, status, date, text length |
| `onboard --company <id>` | builds the knowledge base |
| `rag-ask --company <id> "question"` | RAG answer with quotes |
| `run-ax --company <id> [--mode dev\|live] [--trigger manual\|schedule]` | Ax run for today (resumable) |
| `run-competitor --company <id>` | analyse new competitor events |
| `run-faq --company <id>` | FAQ agent |
| `readiness --company <id> <url>` | AI-readiness check from the command line |
| `send-report --company <id>` / `send-alerts --company <id>` / `send-test-email --company <id>` | emails |
| `daily [--company <id>]` | for every company with monitoring on (or one): Ax → competitor → FAQ → alert email → daily report |

Dev mode: Groq for internal roles, first 4 questions only, so tests are cheap.

Every agent command (and `daily`, `onboard`) accepts `--trigger manual|schedule` (default `manual`), because the GitHub workflow always passes it. One run per company, kind and day: running again the same day resumes or completes that run; if it is already completed, nothing new is asked and the dashboard shows "Today's run is already complete".

---

## 12. Configuration (`.env.example`)

```
# database
DATABASE_URL=postgresql+psycopg://answerwatch:answerwatch@localhost:5432/answerwatch

# AI (free tiers)
GEMINI_API_KEY=
GEMINI_PROBE_MODEL=gemini-3.8-flash
GEMINI_INTERNAL_MODEL=gemini-3.5-flash-lite
GEMINI_EMBED_MODEL=gemini-embedding-001
EMBEDDING_DIM=768
GROQ_API_KEY=
GROQ_PROBE_MODEL=openai/gpt-oss-120b
GROQ_INTERNAL_MODEL=openai/gpt-oss-120b
GROQ_TOKENS_PER_MINUTE=8000
GROQ_MAX_OUTPUT_TOKENS=800
OPENROUTER_API_KEY=
OPENROUTER_MEMORY_MODEL=nvidia/nemotron-3.5-super-vl:free

# limits
GEMINI_MAX_CONCURRENCY=2
GROQ_MAX_CONCURRENCY=1
PAGE_CACHE_DAYS=7

# fetching
FETCH_USER_AGENT=AnswerWatchBot/0.1 (+your-email)

# email (Gmail with 2-step verification and an app password)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USER=
SMTP_APP_PASSWORD=
EMAIL_FROM_NAME=AnswerWatch

# app
ADMIN_PASSWORD=change-me
FRONTEND_ORIGIN=http://localhost:5173
DASHBOARD_URL=http://localhost:5173
TIMEZONE=Europe/Helsinki

# jobs: local (dev) or github (live)
JOB_RUNNER=local
GITHUB_REPO=your-user/answerwatch
GITHUB_DISPATCH_TOKEN=          # fine-grained token with Actions: read and write on this repo
```

Never commit `.env`. Live secrets go to GitHub repository secrets (agents) and Render environment variables (API).

---

## 13. Docker Compose (local)

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment: { POSTGRES_USER: answerwatch, POSTGRES_PASSWORD: answerwatch, POSTGRES_DB: answerwatch }
    ports: ["5432:5432"]
    volumes: [dbdata:/var/lib/postgresql/data]
  api:
    build: ./backend
    env_file: .env
    environment: { DATABASE_URL: "postgresql+psycopg://answerwatch:answerwatch@db:5432/answerwatch" }
    depends_on: [db]
    ports: ["8000:8000"]
    profiles: ["full"]
  web:
    build: ./frontend
    depends_on: [api]
    ports: ["5173:80"]
    profiles: ["full"]
volumes: { dbdata: {} }
```

`docker compose up -d db` for daily development; `docker compose --profile full up --build` for the one-command start.

---

## 14. GitHub Actions

**`ci.yml`**: on push and pull request: Postgres+pgvector service container, `uv sync`, `alembic upgrade head`, `ruff check`, `pytest`; frontend `npm ci && npm run build`.

**`agents.yml`**:

```yaml
name: agents
on:
  schedule:
    - cron: "15 7 * * *"
      timezone: "Europe/Helsinki"   # if GitHub rejects this field, use "15 5 * * *" (UTC, winter time)
  workflow_dispatch:
    inputs:
      job:     { description: "daily | onboard | ax | competitor | faq", required: true, default: "daily" }
      company: { description: "company id (empty = all with monitoring on)", required: false, default: "" }
concurrency:
  group: agents-${{ github.event.inputs.company || 'all' }}
  cancel-in-progress: false
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --project backend
      - run: uv run --project backend python -m app.cli job "$JOB" [--company "$COMPANY" when not empty] --trigger "$TRIGGER"   # see .github/workflows/agents.yml
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_APP_PASSWORD: ${{ secrets.SMTP_APP_PASSWORD }}
          DASHBOARD_URL: ${{ secrets.DASHBOARD_URL }}
          # model names and limits: set as repository variables or defaults in config.py
```

Check action versions and the `timezone` field against current GitHub docs when building. Scheduled runs can start 5 to 30 minutes late; in a public repo they are disabled after 60 days without commits.

---

## 15. Deployment (all free, no card)

1. **Neon**: create a project, enable `vector` (`CREATE EXTENSION IF NOT EXISTS vector;`), copy the connection string, convert to `postgresql+psycopg://...?sslmode=require`. Run `alembic upgrade head` against it from your laptop. Import the Kemira profile and run `onboard` once.
2. **Render**: new Web Service from the GitHub repo, Docker, root `backend/`, free instance. Env: `DATABASE_URL`, `ADMIN_PASSWORD`, `FRONTEND_ORIGIN`, `JOB_RUNNER=github`, `GITHUB_REPO`, `GITHUB_DISPATCH_TOKEN`, `GEMINI_API_KEY` and `GROQ_API_KEY` (needed for the on-demand AI-readiness check), model names, `TIMEZONE`. Health check path `/api/health`.
3. **Vercel**: import the repo, root `frontend/`, env `VITE_API_URL=https://<render-app>.onrender.com`. `vercel.json` rewrites all routes to `index.html`. The demo page is served at `/demo/public-questions.html`; set Kemira's `faq_source_urls` to that live URL.
4. **GitHub**: add the secrets from section 14; run the `agents` workflow manually once (job `daily`, company `kemira`); check the dashboard and the emails.
5. Free-tier facts to remember: Render sleeps after 15 minutes (wakes in about 1 minute); Neon suspends after 5 minutes idle (wakes in seconds); Render bandwidth on the free tier is small, which is fine for a demo.

---

## 16. Testing

- **No real AI or internet in tests**: fake engines, fake internal AI, fake embeddings, `httpx.MockTransport`, saved fixtures in `tests/fixtures/`.
- Must-have tests: profile validation errors; citation parsing from saved Groq/Gemini/OpenRouter responses; polite fetcher (robots, redirects, cache, non-HTML); chunking; RAG quote check; judge scoring including quote verification and numeric override; daily accuracy maths; why finder (cited page, Wikipedia, model memory); alias matching ("SNF" not inside other words) and ranks; competitor event rules; alert rules; FAQ dedupe; readiness scoring; email rendering; API shapes and admin auth; resumable runs (second run adds nothing).
- Real checks are done with CLI commands (`ping`, `fetch`, `rag-ask`, `run-ax --mode dev`).

---

## 17. Limits to show on the About page

- The tested engines are free engines; real ChatGPT/Perplexity/Gemini-with-search need paid keys and can be added as engines later.
- Only engines with web search give sources; "why" for memory-only engines can only say "model memory".
- API answers can differ from what people see in consumer apps.
- The judge is an AI; its reason and quote are shown so a person can check it.
- Root causes are likely causes, not proof.
- Facts come from the company's public publications and were not reviewed by the company.

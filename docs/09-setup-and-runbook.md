# 09 — Setup and runbook

## Prerequisites

| Tool | Version | Check |
|---|---|---|
| Linux / macOS (Windows via WSL2) | — | — |
| Python | 3.12 (`.python-version`) | `python3 --version` |
| uv | recent | `uv --version` |
| Docker + Docker Compose v2 | recent | `docker compose version` |
| Claude Code, logged in with your Claude subscription | — | `claude --version`, then run `claude` once and log in |
| A display (for headed Chromium) | — | or set `BROWSER_HEADLESS=true` |

The Claude Agent SDK drives Claude Code under the hood; it uses whatever account Claude Code is
logged in with. No API key is configured in this repo.

## First-time setup

```bash
git clone https://github.com/dhiraj849/Job_assistent.git
cd Job_assistent

# 1. Python dependencies
uv sync

# 2. Browser
uv run playwright install chromium
#   On a fresh Linux machine you may also need system libraries:
#   uv run playwright install-deps chromium

# 3. Configuration
cp .env.example .env
#   then add the POSTGRES_* variables below to .env (they are not in .env.example yet)
cp profile.example.yaml profile.yaml
#   edit profile.yaml with your real data (it is gitignored)
cp answers.example.yaml answers.yaml
#   application answers (CTC, notice period...); gitignored; validated by answers_loader
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#   put the output in .env as NAUKRI_STATE_KEY=... (only needed for the logged-in tools)

# 4. Infrastructure
docker compose up -d
docker compose ps          # postgres should become "healthy"

# 5. Database schema
uv run alembic upgrade head
```

Minimum `.env`:

```dotenv
LOG_LEVEL=INFO
LOG_FORMAT=console
POSTGRES_USER=job_agent
POSTGRES_PASSWORD=change-me-local-only
POSTGRES_DB=job_agent
```

`docker-compose.yml` reads `POSTGRES_USER/PASSWORD/DB` from `.env`; the app reads the same
variables, so one file configures both.

Apply safety settings (optional; defaults shown):

```dotenv
APPLY_MODE=dry_run          # dry_run | live — live is not implemented yet (Task 3) and ends as "failed"
MAX_APPLIES_PER_DAY=10      # per IST calendar day; dry runs and live applies are counted separately
```

`APPLY_MODE` and `MAX_APPLIES_PER_DAY` are read by the `apply_job` activity at run time; restart the
worker after changing `.env`. To confirm the mode without opening `.env`, check the startup line:
`grep worker_started .run/worker.log` → `apply_mode=dry_run max_applies_per_day=10 ...`.

## One-command stack (Makefile)

After first-time setup, the `Makefile` in the project root drives the whole stack.
Run `make` to list targets.

| Target | What it does |
|---|---|
| `make setup` | `uv sync` + `uv run playwright install chromium` |
| `make start` | Checks `docker`, `uv`, `claude` on PATH and that `.env` exists → `docker compose up -d` → polls Postgres, Qdrant, Temporal and the `default` namespace (60s timeout) → `uv sync` → `alembic upgrade head` → starts the worker in the background (skipped if already running) and checks it is still alive after 10s → prints URLs → runs discovery (blocks until the workflow finishes) |
| `make stop` | Stops the worker via `.run/worker.pid` (cleans a stale PID file), then `docker compose stop` |
| `make down` | `make stop` + `docker compose down` (never `-v`; data is kept) |
| `make worker` | Worker in the foreground (debugging) |
| `make discover` | Only trigger discovery (stack must be running) |
| `make logs` / `make status` | Tail `.run/worker.log` / `docker compose ps` + worker state |
| `make pending` | List jobs awaiting approval |
| `make approve ID=<id>` / `make reject ID=<id>` | Send a decision; optional `NOTE="..."` |

Notes:

- `.run/` (worker PID + log) is gitignored.
- `claude` comes from nvm's Node. If `make start` says it is missing, run
  `nvm alias default 20` and open a new terminal.

## Running

| Task | Command |
|---|---|
| Full pipeline (search → store → filter → rank → LLM → print) | `uv run python main.py` |
| Agent prototype (tool calling + CLI approval) | `uv run python -m app.agent.agent` |
| Count unmatched jobs / saved matches | `uv run python -m scripts.check_unmatched` |
| Rebuild Qdrant vectors from Postgres | `uv run python -m scripts.sync_jobs_to_qdrant` |
| Semantic search with your profile | `uv run python -m scripts.search_jobs` |
| Semantic search with free text | `uv run python -m scripts.search_jobs "django rest api fintech"` |
| Save one job detail page's HTML to `/tmp/naukri_job_page.html` | `uv run python -m scripts.inspect_job_page` |
| Embedding demo (no DB) | `uv run python -m scripts.embedding_demo` |
| Temporal worker (runs both workflows + activities) | `uv run python -m app.workflows.worker` |
| Start discovery workflow (needs worker; starts one `job-{id}` workflow per new job) | `uv run python -m scripts.start_discovery --keyword "Python" --location "Noida"` |
| Start the application workflow for one existing job | `uv run python -m scripts.start_job_workflow <job_id>` |
| List jobs awaiting your approval, then `needs_manual` / `failed` jobs with their reason | `uv run python -m scripts.list_pending` |
| Approve / reject a job (apply follows `APPLY_MODE`, default dry-run) | `uv run python -m scripts.decide_job <job_id> yes\|no ["note"]` |
| Log in to Naukri once and save the encrypted session (headed) | `uv run python -m scripts.naukri_login` |
| Inspect a job's apply button, logged in (saves to `artifacts/inspect/<id>/`) | `uv run python -m scripts.inspect_apply_flow <job_id>` |
| Same, and click Apply once then stop (never submits) | `uv run python -m scripts.inspect_apply_flow <job_id> --click` |
| Apply LIVE to one approved job (needs an `applications` row from `decide_job yes`; y/N) | `uv run python -m scripts.apply_one <job_id>` |
| Record an apply you did by hand (applications + `jobs.status`, y/N; never raw SQL) | `uv run python -m scripts.mark_applied <job_id> --reason "company site"` |
| One-time: create `applications` rows for jobs applied before the table existed (idempotent, y/N) | `uv run python -m scripts.backfill_applications` |
| Tests (integration tests use local Postgres in a rolled-back transaction; skipped if it is down) | `uv run pytest` (only unit: `uv run pytest -m "not integration"`) |
| New migration | `uv run alembic revision --autogenerate -m "message"` |
| Stop infra (keep data) | `docker compose down` |
| Stop infra and **delete data** | `docker compose down -v` |

Useful endpoints: Qdrant dashboard at <http://localhost:6333/dashboard>; Postgres at
`localhost:5433` (`psql -h localhost -p 5433 -U job_agent job_agent`).

## Environment variables

All settings are defined in `app/config.py` and can be set in `.env` or the environment.
Unknown variables in `.env` are ignored (`extra="ignore"`), because `.env` is shared with
docker-compose (e.g. `TEMPORAL_DB_*` used only by the Temporal containers).

| Variable | Default | Used by | Notes |
|---|---|---|---|
| `JOB_SEARCH_KEYWORD` | `Python Backend Engineer` | `main.py`, agent | Naukri search keyword |
| `JOB_SEARCH_LOCATION` | `Noida` | `main.py`, agent | Naukri location |
| `MAX_MATCH_JOBS` | `5` | pipeline | Max LLM evaluations per run (top N from Qdrant) |
| `LOG_LEVEL` | `INFO` | logging | Applies to `app.*` loggers; third-party loggers stay at WARNING |
| `LOG_FORMAT` | `console` | logging | `console` or `json` |
| `PROFILE_PATH` | `profile.yaml` | `main.py`, agent, scripts | Candidate profile YAML |
| `ANSWERS_PATH` | `answers.yaml` | `app/services/answers_loader.py` | Apply-question answers YAML (unknown keys rejected) |
| `BROWSER_HEADLESS` | `false` | Naukri source | `true` for headless Chromium |
| `BROWSER_TIMEOUT_MS` | `20000` | Naukri source | Playwright default timeout |
| `DETAIL_PAGE_DELAY_SECONDS` | `3.0` | — | **Defined but unused** (reserved for detail-page scraping) |
| `NAUKRI_STATE_KEY` | *(none)* | `session_store` | Fernet key for the saved Naukri session; `SecretStr`. Not in `.env.example` yet |
| `NAUKRI_STATE_PATH` | `secrets/naukri_state.enc` | `session_store` | Encrypted session file (gitignored folder) |
| `POSTGRES_USER` | `job_agent` | app, compose | |
| `POSTGRES_PASSWORD` | *(empty)* | app, compose | `SecretStr`; required by the Postgres container |
| `POSTGRES_DB` | `job_agent` | app, compose | |
| `POSTGRES_HOST` | `localhost` | app | |
| `POSTGRES_PORT` | `5433` | app | Compose maps host 5433 → container 5432 |
| `QDRANT_URL` | `http://localhost:6333` | ranker, scripts | |
| `TEMPORAL_ADDRESS` | `localhost:7233` | worker, `start_discovery` | Temporal frontend (gRPC) |
| `TEMPORAL_NAMESPACE` | `default` | worker, `start_discovery` | |
| `TEMPORAL_TASK_QUEUE` | `job-agent` | worker, `start_discovery` | Worker and starter must use the same queue |
| `X_CLIENT_ID` | *(none)* | — | Leftover from the MCP experiment; unused by the app |
| `X_CLIENT_SECRET` | *(none)* | — | Leftover; unused. Remove ([12](12-roadmap-and-status.md#known-issues)) |

Note: `app/agent/agent.py` passes keyword/location from settings, but `app/agent/claude_tools.py`
creates `NaukriJobSource` without `BROWSER_HEADLESS`/`BROWSER_TIMEOUT_MS`, so the prototype always
runs headed with a 20 s timeout.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'claude_agent_sdk'` | Environment out of date with `uv.lock` | `uv sync` |
| `FileNotFoundError: Profile file not found: profile.yaml` | No profile | `cp profile.example.yaml profile.yaml` |
| `NAUKRI_STATE_KEY is not set` / `No saved session` / `Cannot decrypt` | Key missing, never logged in, or key changed | Generate a key (setup step 4), then `uv run python -m scripts.naukri_login` |
| `Session expired` from `inspect_apply_flow` | Naukri logged the session out | `uv run python -m scripts.naukri_login` |
| Login script says "Not logged in" although you are | `LOGGED_IN_MARKER` selector is unverified | Inspect the header HTML and fix `LOGGED_IN_MARKER` in `app/browser/naukri_browser.py` |
| Postgres container exits / "superuser password is not specified" | `POSTGRES_PASSWORD` missing in `.env` | Add `POSTGRES_*` to `.env`, `docker compose up -d` |
| `connection refused` on port 5433 | Compose not running | `docker compose up -d`; check `docker compose ps` |
| `password authentication failed` | `.env` changed after the volume was created | Use the original password, or `docker compose down -v` (deletes data) |
| `relation "jobs" does not exist` | Migrations not applied | `uv run alembic upgrade head` |
| `relation "applications" does not exist` / `NotApprovedError` for an old approved job | Migration `f734e9e72583` not applied, or the job was approved before the table existed | `uv run alembic upgrade head`; approve again via the workflow, or `mark_applied` if you applied by hand |
| New activity `record_approval` not found / old apply behaviour after an update | Worker still runs the old code | Restart the worker (`make stop` + `make start`, or restart `app.workflows.worker`) |
| `Executable doesn't exist ... chromium` | Browser not installed | `uv run playwright install chromium` |
| Browser fails to launch on Linux (missing libs) | System dependencies | `uv run playwright install-deps chromium` |
| Headed browser fails over SSH / no display | No X server | `BROWSER_HEADLESS=true`, or use `xvfb-run` |
| Log `no_job_cards_found` | No results, or Naukri changed markup / showed a challenge | Run headed and watch; check selectors in [06](06-browser-automation.md#selectors) |
| Many cards but empty fields / `job_extraction_failed` | Selector drift | Update `app/job_sources/naukri_extractor.py` |
| "No matching jobs found" every run | Filter too strict, or no job reaches cosine ≥ 0.7 | Check `jobs_filtered` and `jobs_ranked` log events; try `scripts/search_jobs.py` to see scores |
| `matching_failed` warnings | Claude Code not logged in, rate-limited, or invalid JSON | Run `claude` interactively to check login; retry later |
| Qdrant `Not found: Collection` in scripts | Collection not created yet | Run `main.py` once or `scripts/sync_jobs_to_qdrant.py` |
| First run slow before ranking | fastembed downloads the model (~tens of MB) on first use | Wait; it is cached afterwards |

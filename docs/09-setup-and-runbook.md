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

# 2. WORKAROUND until the dependency fix lands (see Known issues):
#    claude-agent-sdk and mcp are imported but not declared in pyproject.toml.
uv pip install claude-agent-sdk mcp

# 3. Browser
uv run playwright install chromium
#   On a fresh Linux machine you may also need system libraries:
#   uv run playwright install-deps chromium

# 4. Configuration
cp .env.example .env
#   then add the POSTGRES_* variables below to .env (they are not in .env.example yet)
cp profile.example.yaml profile.yaml
#   edit profile.yaml with your real data (it is gitignored)

# 5. Infrastructure
docker compose up -d
docker compose ps          # postgres should become "healthy"

# 6. Database schema
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
| Unit tests | `uv run pytest` |
| New migration | `uv run alembic revision --autogenerate -m "message"` |
| Stop infra (keep data) | `docker compose down` |
| Stop infra and **delete data** | `docker compose down -v` |

Useful endpoints: Qdrant dashboard at <http://localhost:6333/dashboard>; Postgres at
`localhost:5433` (`psql -h localhost -p 5433 -U job_agent job_agent`).

## Environment variables

All settings are defined in `app/config.py` and can be set in `.env` or the environment.

| Variable | Default | Used by | Notes |
|---|---|---|---|
| `JOB_SEARCH_KEYWORD` | `Python Backend Engineer` | `main.py`, agent | Naukri search keyword |
| `JOB_SEARCH_LOCATION` | `Noida` | `main.py`, agent | Naukri location |
| `MAX_MATCH_JOBS` | `5` | pipeline | Max LLM evaluations per run (top N from Qdrant) |
| `LOG_LEVEL` | `INFO` | logging | Applies to `app.*` loggers; third-party loggers stay at WARNING |
| `LOG_FORMAT` | `console` | logging | `console` or `json` |
| `PROFILE_PATH` | `profile.yaml` | `main.py`, agent, scripts | Candidate profile YAML |
| `BROWSER_HEADLESS` | `false` | Naukri source | `true` for headless Chromium |
| `BROWSER_TIMEOUT_MS` | `20000` | Naukri source | Playwright default timeout |
| `DETAIL_PAGE_DELAY_SECONDS` | `3.0` | — | **Defined but unused** (reserved for detail-page scraping) |
| `POSTGRES_USER` | `job_agent` | app, compose | |
| `POSTGRES_PASSWORD` | *(empty)* | app, compose | `SecretStr`; required by the Postgres container |
| `POSTGRES_DB` | `job_agent` | app, compose | |
| `POSTGRES_HOST` | `localhost` | app | |
| `POSTGRES_PORT` | `5433` | app | Compose maps host 5433 → container 5432 |
| `QDRANT_URL` | `http://localhost:6333` | ranker, scripts | |
| `X_CLIENT_ID` | *(none)* | — | Leftover from the MCP experiment; unused by the app |
| `X_CLIENT_SECRET` | *(none)* | — | Leftover; unused. Remove ([12](12-roadmap-and-status.md#known-issues)) |

Note: `app/agent/agent.py` passes keyword/location from settings, but `app/agent/claude_tools.py`
creates `NaukriJobSource` without `BROWSER_HEADLESS`/`BROWSER_TIMEOUT_MS`, so the prototype always
runs headed with a 20 s timeout.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'claude_agent_sdk'` | `uv sync` removes packages not in the lockfile | `uv pip install claude-agent-sdk mcp` (until declared in `pyproject.toml`) |
| `FileNotFoundError: Profile file not found: profile.yaml` | No profile | `cp profile.example.yaml profile.yaml` |
| Postgres container exits / "superuser password is not specified" | `POSTGRES_PASSWORD` missing in `.env` | Add `POSTGRES_*` to `.env`, `docker compose up -d` |
| `connection refused` on port 5433 | Compose not running | `docker compose up -d`; check `docker compose ps` |
| `password authentication failed` | `.env` changed after the volume was created | Use the original password, or `docker compose down -v` (deletes data) |
| `relation "jobs" does not exist` | Migrations not applied | `uv run alembic upgrade head` |
| `Executable doesn't exist ... chromium` | Browser not installed | `uv run playwright install chromium` |
| Browser fails to launch on Linux (missing libs) | System dependencies | `uv run playwright install-deps chromium` |
| Headed browser fails over SSH / no display | No X server | `BROWSER_HEADLESS=true`, or use `xvfb-run` |
| Log `no_job_cards_found` | No results, or Naukri changed markup / showed a challenge | Run headed and watch; check selectors in [06](06-browser-automation.md#selectors) |
| Many cards but empty fields / `job_extraction_failed` | Selector drift | Update `app/job_sources/naukri_extractor.py` |
| "No matching jobs found" every run | Filter too strict, or no job reaches cosine ≥ 0.7 | Check `jobs_filtered` and `jobs_ranked` log events; try `scripts/search_jobs.py` to see scores |
| `matching_failed` warnings | Claude Code not logged in, rate-limited, or invalid JSON | Run `claude` interactively to check login; retry later |
| Qdrant `Not found: Collection` in scripts | Collection not created yet | Run `main.py` once or `scripts/sync_jobs_to_qdrant.py` |
| First run slow before ranking | fastembed downloads the model (~tens of MB) on first use | Wait; it is cached afterwards |

# 08 — Tech stack

Constraint: free, open-source, self-hosted. The only paid item is the user's existing Claude
subscription. Versions are from `pyproject.toml`, `docker-compose.yml` and `.python-version`.

| Component | Choice | Status | Why | Alternatives considered | Cost |
|---|---|---|---|---|---|
| Language | Python 3.12 | Built | Best ecosystem for Playwright, LLM SDKs, embeddings; async support | TypeScript/Node | Free |
| Package / env manager | uv (`uv.lock`) | Built | Fast, reproducible lockfile, runs scripts | pip + venv, Poetry | Free |
| Config | pydantic-settings (`.env`) | Built | Typed settings, `SecretStr` | dynaconf, python-dotenv | Free |
| Data validation | Pydantic v2 | Built | DTOs + JSON schema for LLM output | dataclasses, attrs | Free |
| Profile file | YAML (PyYAML, `safe_load`) | Built | Human-editable | JSON, TOML | Free |
| Browser automation | Playwright 1.59 (Python, Chromium) | Built | Auto-waiting, reliable locators, `storage_state`, headed/headless ([ADR-002](adr/ADR-002-playwright-for-naukri.md)) | Selenium, requests + BeautifulSoup, unofficial APIs | Free |
| Database | PostgreSQL 16 (Docker) | Built | Source of truth, JSONB, constraints ([ADR-003](adr/ADR-003-postgresql-source-of-truth.md)) | SQLite, MySQL | Free |
| ORM / driver | SQLAlchemy 2 async + asyncpg | Built | Typed `Mapped[]` models, async | SQLModel, raw asyncpg, Tortoise | Free |
| Migrations | Alembic | Built | Standard for SQLAlchemy, autogenerate | yoyo, raw SQL | Free |
| Vector DB | Qdrant v1.18.2 (Docker) | Built | Filtering by ID, payloads, per-model collections ([ADR-004](adr/ADR-004-qdrant-over-pgvector.md)) | pgvector, Chroma, FAISS | Free |
| Embeddings | fastembed, `BAAI/bge-small-en-v1.5` (384-d) | Built | Local CPU/ONNX, small, no PyTorch ([ADR-005](adr/ADR-005-fastembed-local-embeddings.md)) | sentence-transformers, Ollama embeddings, OpenAI | Free |
| LLM (primary) | Claude via `claude-agent-sdk` | Built (dependency undeclared) | Uses existing subscription, JSON-schema output ([ADR-007](adr/ADR-007-claude-agent-sdk-llm-provider.md)) | Anthropic API (paid per token), OpenAI | Existing subscription |
| LLM (fallback) | Ollama (local model) | Planned | Offline / rate-limit fallback | llama.cpp, vLLM | Free (local compute) |
| Logging | structlog (console / JSON) | Built | Structured events, contextvars | loguru, stdlib logging | Free |
| Workflow engine | Temporal (self-hosted) + `temporalio` SDK | Planned | Durable execution, signals, timers, schedules ([ADR-006](adr/ADR-006-temporal-durable-workflows.md)) | Celery/ARQ + Redis, Prefect, LangGraph | Free |
| API | FastAPI | Planned | Async, Pydantic-native ([ADR-001](adr/ADR-001-python-fastapi.md)) | Django, Litestar, Flask | Free |
| Dashboard | Next.js | Planned (later) | Approval queue UI ([ADR-012](adr/ADR-012-nextjs-dashboard.md)) | Streamlit, HTMX + Jinja, React SPA | Free |
| Artifact storage | MinIO (S3-compatible) | Planned | Screenshots, HTML, resumes ([ADR-013](adr/ADR-013-minio-artifacts.md)) | Local filesystem, Postgres bytea | Free |
| Tracing / metrics | OpenTelemetry → Grafana, Tempo, Loki, Prometheus | Planned | Free, self-hosted ([ADR-010](adr/ADR-010-self-hosted-observability.md)) | Jaeger, SigNoz, Datadog (paid) | Free |
| LLM observability | Langfuse (self-hosted) | Planned | Prompt/response traces, evals, scores | Arize Phoenix, Helicone | Free |
| Tests | pytest (+ pytest-asyncio planned) | Built (sync tests only) | Standard | unittest | Free |
| Local infra | Docker Compose | Built | Postgres + Qdrant with volumes | Podman, native installs | Free |
| CI | GitHub Actions | Planned | Repo is on GitHub; free minutes for public/personal use | GitLab CI, Woodpecker | Free (within limits) |

## Dependency gaps (verified)

- `claude-agent-sdk` and `mcp` are imported (`app/llm/claude_code.py`, `app/agent/*`, `server.py`)
  but missing from `pyproject.toml` and `uv.lock`. They are only present because they were installed
  manually into `.venv` (versions found there: `claude-agent-sdk 0.2.157`, `mcp 2.2.0`).
- `numpy` is imported by `scripts/embedding_demo.py`; it is installed transitively (fastembed) but
  not declared.
- FastAPI, Temporal, Ollama, OpenTelemetry, Langfuse and MinIO clients are not dependencies yet.

## Resource footprint (planned full stack)

Self-hosting everything is free but not light. Langfuse v3 needs its own Postgres, ClickHouse,
Redis and S3 (MinIO can serve that); Temporal needs a database (reuse the Postgres server, separate
database). Expect several GB of RAM for the full stack; keep observability optional via Compose
profiles.

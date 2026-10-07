# Job Agent

Learning project built to production standards: AI agent that finds jobs on Naukri
(Playwright), matches them to my profile (Qdrant + Claude), and applies ONLY after my
approval. Durable workflows run on Temporal. Stack must stay free / self-hosted.

## Commands
- Infra: `docker compose up -d` (Postgres :5433, Qdrant :6333, Temporal :7233, UI :8080)
- Migrations: `uv run alembic upgrade head`
- Tests: `uv run pytest`
- Pipeline: `uv run python main.py`
- Worker: `uv run python -m app.workflows.worker`
- Docs: `uv run mkdocs serve` (http://127.0.0.1:8000)

## Layout
app/job_sources, app/browser → Naukri scraping | app/services → filter, rank, match, score
app/vector → embeddings + Qdrant | app/llm, app/agent → Claude | app/db → models, repository
app/workflows → Temporal workflows + activities | alembic/ → migrations | docs/ → documentation

## Rules
- Keep code simple and readable; add short comments explaining "why".
- Workflow code must be deterministic; all I/O goes in activities.
- Never read or print `.env`; use `.env.example` for variable names.
- Show a plan before big changes and wait for my approval.
- Explain changes to me in simple Hinglish; write code and docs in English.

## Docs must follow code
After any code change, use the `sync-docs` skill before finishing the task.
Only open the doc that matches the changed path:

| Changed path | Update |
|---|---|
| app/job_sources, app/browser | docs/06-browser-automation.md |
| app/services, app/vector | docs/07-matching-and-retrieval.md |
| app/llm, app/agent, prompts | docs/05-agent-design.md |
| app/workflows | docs/03-workflows.md |
| app/db/models.py, alembic/versions | docs/04-data-model.md |
| docker-compose.yml, docker/, app/config.py | docs/09-setup-and-runbook.md |
| pyproject.toml (new dependency) | docs/08-tech-stack.md |
| new component or data flow | docs/02-architecture.md |
| feature started / finished | docs/12-roadmap-and-status.md |
| new or replaced technology | new ADR in docs/adr/ |

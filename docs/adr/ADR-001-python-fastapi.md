# ADR-001 — Use Python for the system and FastAPI for its HTTP API

- **Status:** Accepted
- **Implementation:** Python Built; FastAPI Planned (no API exists yet)
- **Date:** 2026-09-24

## Context

The core work is browser automation, LLM calls, embeddings and database access. The author is
learning production practices, so one language across all back-end parts is preferred. An HTTP API
is needed later for the dashboard and to send approval signals to workflows.

## Decision

- All back-end code is Python 3.12, async-first (`asyncio`), managed with uv.
- The HTTP API, when added, uses **FastAPI**, with Pydantic models shared with `app/models`.
- The API is a thin layer: it reads Postgres, starts/queries Temporal workflows and sends signals.
  Business logic stays in `app/services`.

## Alternatives considered

| Option | Why not |
|---|---|
| TypeScript/Node end-to-end | Playwright is equally good, but embeddings (fastembed) and the Python ML ecosystem are weaker; the Claude Agent SDK exists for both. |
| Django + DRF | Heavier; sync-first ORM duplicates SQLAlchemy/Alembic already in use. |
| Litestar | Viable; smaller community and fewer learning resources. |
| Flask | No native async / Pydantic integration. |

## Consequences

- Positive: one language; Pydantic models double as API schemas and LLM JSON schemas.
- Negative: Python async requires discipline — sync libraries (fastembed, `QdrantClient`) must be
  moved off the event loop ([known issue #5](../12-roadmap-and-status.md#known-issues)).
- Follow-up: add FastAPI in Phase 3 with endpoints for matches list and approve/reject.

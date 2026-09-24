# ADR-012 — Build the dashboard with Next.js (later)

- **Status:** Accepted
- **Implementation:** Planned (Phase 5); until then CLI and FastAPI endpoints
- **Date:** 2026-09-24

## Context

The approval flow needs a place to see match details and approve or reject quickly, and later to
review run history and artifacts (screenshots). A CLI prompt does not scale beyond a prototype.

## Decision

- A **Next.js** (TypeScript) app talks only to the FastAPI API; it never accesses Postgres, Temporal
  or MinIO directly.
- Scope for v1: approval queue, job + match detail, approve/reject with note, application history.
- Built after the API and workflows exist (Phase 5); a minimal API or server-rendered page is enough before that.

## Alternatives considered

| Option | Why not |
|---|---|
| Streamlit | Fast to build, but limited for multi-page stateful UI; pulls UI into the Python process. |
| FastAPI + Jinja + HTMX | Simple and viable; Next.js chosen for learning value and richer UI later. |
| No UI (CLI / Telegram bot) | Poor for reviewing long job descriptions and screenshots. |

## Consequences

- Positive: modern UI stack; clear API contract.
- Negative: second language and toolchain (Node, TypeScript); auth needed once exposed beyond localhost.
- Follow-ups: generate a TypeScript client from FastAPI's OpenAPI schema.

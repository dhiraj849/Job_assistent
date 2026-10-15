# Documentation

AI Job Agent is a self-hosted assistant that discovers jobs on Naukri, evaluates each one against a
candidate profile, prepares the application, and applies **only after explicit human approval**.
Today it runs as a single Python process (`main.py`) that scrapes Naukri search results with
Playwright, stores jobs in PostgreSQL, ranks them semantically with Qdrant + fastembed, scores the
top candidates with Claude (via the Claude Agent SDK) and prints a ranked list. Durable workflows
(Temporal), the approval flow, the apply step, a dashboard and observability are planned. Everything
is free / open-source / self-hosted; the only paid dependency is an existing Claude subscription.

## Status legend

Used in every document and diagram.

| Marker | Meaning |
|---|---|
| **Built** | Exists in the code on `main` and is used by `main.py` or a script. |
| **In progress** | Partial code exists (prototype, unused config, or not wired into the main flow). |
| **Planned** | Decided or proposed; no code yet. |

## Documents

| # | Document | What it answers |
|---|---|---|
| 01 | [Product overview](01-product-overview.md) | Why this exists, goals, non-goals, ToS/ethics risk, why human-in-the-loop |
| 02 | [Architecture](02-architecture.md) | C4 context / container / component views, current vs target |
| 03 | [Workflows](03-workflows.md) | Temporal workflows, activities, approval signal, job lifecycle |
| 04 | [Data model](04-data-model.md) | Tables, ERD, indexes, Alembic migrations |
| 05 | [Agent design](05-agent-design.md) | Prompts, structured output, scoring, LLM provider, guardrails, evals |
| 06 | [Browser automation](06-browser-automation.md) | Playwright flow, selectors, sessions, rate limiting, dry-run |
| 07 | [Matching and retrieval](07-matching-and-retrieval.md) | Filter → Qdrant → LLM → score → rank |
| 08 | [Tech stack](08-tech-stack.md) | Every component, why, alternatives, cost |
| 09 | [Setup and runbook](09-setup-and-runbook.md) | Install, run, env vars, troubleshooting |
| 10 | [Security](10-security.md) | Secrets, sessions, PII, logging rules |
| 11 | [Observability and testing](11-observability-and-testing.md) | Log events, tracing plan, tests, CI |
| 12 | [Roadmap and status](12-roadmap-and-status.md) | Feature status, phases, known issues, tech debt |

## Architecture Decision Records

| ADR | Decision | Implementation |
|---|---|---|
| [000](adr/ADR-000-template.md) | Template | — |
| [001](adr/ADR-001-python-fastapi.md) | Python + FastAPI | Python Built, FastAPI Planned |
| [002](adr/ADR-002-playwright-for-naukri.md) | Playwright for Naukri (no official API) | Built (search only) |
| [003](adr/ADR-003-postgresql-source-of-truth.md) | PostgreSQL as source of truth + Alembic | Built |
| [004](adr/ADR-004-qdrant-over-pgvector.md) | Qdrant over pgvector | Built |
| [005](adr/ADR-005-fastembed-local-embeddings.md) | fastembed local embeddings | Built |
| [006](adr/ADR-006-temporal-durable-workflows.md) | Temporal for durable workflows | Planned |
| [007](adr/ADR-007-claude-agent-sdk-llm-provider.md) | Claude Agent SDK behind `LLMProvider`, Ollama fallback | In progress |
| [008](adr/ADR-008-mandatory-human-approval.md) | Mandatory human approval before submit | In progress (prototype) |
| [009](adr/ADR-009-deterministic-scoring.md) | Deterministic scoring in code | Built |
| [010](adr/ADR-010-self-hosted-observability.md) | Free self-hosted observability stack | Planned (structlog Built) |
| [011](adr/ADR-011-modular-monolith.md) | Modular monolith | Built |
| [012](adr/ADR-012-nextjs-dashboard.md) | Next.js dashboard (later) | Planned |
| [013](adr/ADR-013-minio-artifacts.md) | MinIO for artifacts | Planned |
| [014](adr/ADR-014-encrypted-naukri-session.md) | Encrypted Naukri session (Fernet) | Built |
| [015](adr/ADR-015-pypdf-resume-text.md) | pypdf for resume text (grounding AI form answers) | Built |

## Conventions

- Diagrams are Mermaid and render on GitHub and in VS Code (with a Mermaid preview extension).
- Code references use `path:line` relative to the repo root, verified against commit `65c1375`.
- When code and docs disagree, the code wins — fix the doc in the same PR.
- New architectural decisions get a new ADR (copy [ADR-000](adr/ADR-000-template.md)); never edit
  an accepted ADR's decision — supersede it.

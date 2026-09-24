# ADR-003 — PostgreSQL is the source of truth, schema managed by Alembic

- **Status:** Accepted
- **Implementation:** Built (`jobs`, `job_matches`, two migrations)
- **Date:** 2026-09-24

## Context

Jobs must be remembered across runs (dedupe, "already evaluated"), match results must be queryable,
and later approvals and applications need an auditable record. Several stores are in play (Qdrant,
planned MinIO, Temporal's own DB); one must be authoritative.

## Decision

- **PostgreSQL 16** (Docker Compose, host port 5433) holds all business data.
- Qdrant vectors and MinIO objects are **derived or attached** data keyed by Postgres IDs; they can
  be rebuilt or re-captured and are never the only copy of business state.
- Access via SQLAlchemy 2 async + asyncpg, through repository classes (`app/db/job_repository.py`).
- Every schema change is an **Alembic** migration, reviewed by hand, with a working downgrade
  ([04](../04-data-model.md#migration-strategy-alembic)).
- Integrity rules (uniqueness, approval-before-submit) are enforced with DB constraints, not only in code.

## Alternatives considered

| Option | Why not |
|---|---|
| SQLite | Fine for one user, but weaker concurrency for API + worker, no JSONB, and Temporal/Langfuse need Postgres anyway. |
| MongoDB | Relational data (jobs ↔ matches ↔ applications) and constraints fit SQL better. |
| Qdrant payloads as primary store | No transactions or constraints; vectors are model-specific and disposable. |
| `Base.metadata.create_all()` instead of migrations | No history, no safe evolution of existing data. |

## Consequences

- Positive: transactional, constrained, queryable history; one backup target.
- Negative: must keep Qdrant in sync (handled lazily by `JobRanker` and by `scripts/sync_jobs_to_qdrant.py`).
- Follow-ups: `jobs.status`, planned tables, composite uniqueness for multi-user.

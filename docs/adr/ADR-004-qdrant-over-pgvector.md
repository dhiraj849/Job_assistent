# ADR-004 — Use Qdrant for vector search instead of pgvector

- **Status:** Accepted
- **Implementation:** Built (`app/vector/job_vector_store.py`, collection `jobs_bge_small_v1`)
- **Date:** 2026-09-24

## Context

The matching funnel needs semantic ranking of candidate jobs against the profile before spending LLM
calls ([07](../07-matching-and-retrieval.md)). Postgres already exists, so pgvector was the obvious
alternative.

## Decision

- Use **Qdrant** (self-hosted, Docker, `v1.18.2`), cosine distance, 384-d vectors.
- Point ID = `jobs.id`; payload holds display fields only.
- **One collection per embedding model version** (`jobs_bge_small_v1`); a model change creates a new
  collection and a backfill, never mixed vectors.
- Search is restricted to the current candidate IDs with `HasIdCondition` and a score threshold.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| pgvector | One database, joins with SQL, transactional | Extension setup; filtering + ANN tuning is more manual; learning goal favoured a dedicated vector DB |
| Chroma | Simple, embedded | Less mature server mode and filtering |
| FAISS in process | Fast, no service | No persistence/filters out of the box; index rebuilt per run |

## Consequences

- Positive: purpose-built filtering, payloads, dashboard at `:6333/dashboard`, clean per-model collections.
- Negative: second datastore to run, back up and keep in sync; no transactions with Postgres.
- Negative: at current scale (hundreds of jobs) pgvector would also be sufficient — revisit if
  operational overhead outweighs benefits (would be a superseding ADR).
- Follow-ups: `AsyncQdrantClient`; bind to localhost / API key; store semantic score in `job_matches`.

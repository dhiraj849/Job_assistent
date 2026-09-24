# ADR-013 — Store binary artifacts in MinIO

- **Status:** Accepted
- **Implementation:** Planned (Phase 4)
- **Date:** 2026-09-24

## Context

The apply flow will produce screenshots and page HTML (evidence and debugging), and resumes must be
stored for upload. These are binary, can be large, and should not bloat Postgres. Langfuse v3 also
needs S3-compatible storage.

## Decision

- Run **MinIO** (S3-compatible, self-hosted) in Docker Compose.
- Buckets: `artifacts` (screenshots, HTML: `artifacts/{job_id}/{workflow_run_id}/{step}.png`),
  `resumes` (private). No public buckets or presigned links longer than minutes.
- Postgres stores object keys (`applications.artifact_keys`, `candidate_profiles.resume_object_key`), never blobs.
- Retention policy for artifacts (e.g. 90 days) via MinIO lifecycle rules.
- Code uses an S3 API client so storage could move to any S3-compatible service.

## Alternatives considered

| Option | Why not |
|---|---|
| Local filesystem directory | Simplest; no API, harder to share between worker and API containers, no lifecycle rules. |
| Postgres `bytea` | Bloats DB and backups. |
| AWS S3 / Cloudflare R2 | Not self-hosted; possible cost. |

## Consequences

- Positive: standard S3 API; one store also usable by Langfuse.
- Negative: one more service; artifacts contain PII and need the same care as the resume ([10](../10-security.md)).
- Follow-ups: Compose service, bucket bootstrap, `ArtifactStore` interface.

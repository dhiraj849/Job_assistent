# ADR-006 — Use Temporal for durable workflows

- **Status:** Accepted
- **Implementation:** Built (discovery, application, backfill workflows + discovery Schedule; the in-process `JobMatchingPipeline` was removed 2026-10-16)
- **Date:** 2026-09-24
- **Supersedes:** earlier plans to use Celery/ARQ + Redis for background jobs and LangGraph as the orchestrator

## Context

The target flow spans hours or days: scheduled discovery, many browser and LLM steps that fail
independently, and a **human approval that may take days** before an irreversible submit. The
current pipeline is a single process with no retries and no resumability.

## Decision

- Self-host **Temporal** (server + UI) and use the `temporalio` Python SDK.
- `JobDiscoveryWorkflow` runs on a Temporal Schedule; `JobApplicationWorkflow` runs per job with ID
  `job-{job_id}` ([03](../03-workflows.md)).
- Human approval is a **signal** with a timeout; timeout = rejection.
- All I/O happens in activities with explicit retry policies; `submit_application` has
  `maximum_attempts = 1`.
- LLM agents (Claude SDK) run **inside** activities for bounded tasks; they do not orchestrate.

## Alternatives considered

| Option | Why not |
|---|---|
| Celery / ARQ + Redis | Task queue, not workflow engine: waiting days for a signal, timers and step history must be hand-built on top. Adds Redis. |
| LangGraph as orchestrator | Good for LLM control flow; durability, schedules, and long human waits need extra infrastructure; mixes business orchestration with LLM logic. |
| Prefect / Dagster | Data-pipeline oriented; human-in-the-loop signals are less natural. |
| Cron + DB state machine | Possible, but re-implements retries, timeouts, idempotency and visibility. |

## Consequences

- Positive: crash-safe runs, built-in retries/timers/schedules, workflow history in Temporal UI,
  workflow ID gives per-job idempotency.
- Negative: new service and concepts (determinism rules, versioning of workflow code); Temporal needs
  its own database (reuse the Postgres server).
- Negative: workflow code changes need `workflow.patched()` / versioning once runs are long-lived.
- Follow-ups: Phase 3 — Compose service, worker entry point, workflow tests with time-skipping.

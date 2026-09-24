# ADR-010 — Use a free, self-hosted observability stack

- **Status:** Accepted
- **Implementation:** Planned (structlog logging Built)
- **Date:** 2026-09-24

## Context

A long-running, multi-step system (browser + LLM + workflows) is hard to debug from stdout alone.
The cost constraint rules out hosted APM/LLM-tracing products.

## Decision

- **Logs:** structlog JSON to stdout (Built) → Loki.
- **Traces and metrics:** OpenTelemetry SDK → OTel Collector → Tempo (traces) + Prometheus (metrics).
- **Dashboards and alerts:** Grafana.
- **LLM tracing and evals:** self-hosted Langfuse.
- **Workflow visibility:** Temporal UI.
- All of it runs in Docker Compose under an optional `observability` profile.

## Alternatives considered

| Option | Why not |
|---|---|
| Datadog / New Relic / hosted Langfuse / LangSmith | Paid or data leaves the machine. |
| Jaeger + Prometheus only | No log aggregation; Grafana stack covers more with one UI. |
| SigNoz | Viable all-in-one; Grafana stack chosen for broader learning value. |
| Arize Phoenix instead of Langfuse | Viable; Langfuse has stronger prompt management and scoring. |

## Consequences

- Positive: no cost; full data control; industry-standard OTel instrumentation.
- Negative: significant RAM/disk footprint (Langfuse alone needs ClickHouse + Redis + object store);
  more services to upgrade.
- Follow-ups: add `run_id`/trace IDs to logs; remove PII from logs and prompts first ([10](../10-security.md)).

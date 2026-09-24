# ADR-011 — Build a modular monolith; no Kafka or microservices yet

- **Status:** Accepted
- **Implementation:** Built (single `app/` package, layered)
- **Date:** 2026-09-24

## Context

One user, one developer, low volume (tens to hundreds of jobs per day). Production-grade structure
is a goal, but distributed-systems overhead is not.

## Decision

- One Python package `app/` with clear layers (sources, services, llm, vector, db, models) and
  interfaces between them ([02](../02-architecture.md#layer-responsibilities)).
- Deployable units come from **entry points**, not separate codebases: CLI today; API and Temporal
  worker later — all importing the same `app/`.
- Asynchronous work goes through Temporal, not a message broker.
- Revisit only with evidence (e.g. independent scaling needs or multiple teams).

## Alternatives considered

| Option | Why not |
|---|---|
| Microservices (scraper, matcher, applier) | Network boundaries, deployment and consistency costs with no scaling need. |
| Kafka / RabbitMQ event bus | Temporal already provides durable async execution; a broker adds ops without benefit at this volume. |
| Unstructured single script | Not maintainable or testable. |

## Consequences

- Positive: simple deploys, refactors are cheap, one test suite.
- Negative: module boundaries are enforced only by convention — needs review discipline (and later an
  import-linter rule).
- Follow-ups: remove the duplicated flow in `app/agent/` ([known issue #10](../12-roadmap-and-status.md#known-issues)).

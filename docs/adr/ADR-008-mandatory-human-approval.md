# ADR-008 — Require explicit human approval before any application is submitted

- **Status:** Accepted
- **Implementation:** In progress — CLI prototype only (`app/agent/approval.py`); enforced flow Planned
- **Date:** 2026-09-24

## Context

Submitting an application is irreversible, visible to recruiters, and the riskiest action with
respect to Naukri's ToS. LLM evaluations are imperfect, especially on snippet-only descriptions.

## Decision

- **No application is submitted without an explicit approval by the user for that specific job.**
- Enforced at three layers:
  1. Workflow: `submit_application` is only reachable after an `approve` signal ([03](../03-workflows.md#approval-via-signal)).
  2. Database: `applications` CHECK constraint — `applying`/`applied` require `approved_at`.
  3. Tools: no LLM-callable tool can submit.
- Approval times out (placeholder 72 h) → treated as rejection. Silence never means yes.
- No "approve all" / auto-approve rules, including for `strong` matches.
- Live submission additionally requires `APPLY_DRY_RUN=false`.

## Alternatives considered

| Option | Why not |
|---|---|
| Fully autonomous applying above a score | Irreversible errors; ToS risk; contradicts product goals. |
| Approval via prompt instruction only | Not enforceable; LLM can be wrong or injected. |
| Batch approval of N jobs | Encourages rubber-stamping; kept out deliberately. |

## Consequences

- Positive: user stays in control; approvals become labelled data for evals.
- Negative: throughput limited by the user's attention; needs a UI (CLI → API → dashboard).
- Follow-ups: `applications` table, signal endpoint, tests proving no submit without approval.

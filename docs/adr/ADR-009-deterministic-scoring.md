# ADR-009 — Compute overall score, level and ranking deterministically in code

- **Status:** Accepted
- **Implementation:** Built (`job_score_service.py`, `job_match_level_service.py`, `job_ranking_service.py`, unit-tested)
- **Date:** 2026-09-24

## Context

LLMs are inconsistent at arithmetic and at applying thresholds, and their outputs vary across runs
and models. Decisions (what to show, what to ask approval for) need to be reproducible and tunable.

## Decision

- The LLM returns only three sub-scores (0–100) plus explanatory lists; the prompt explicitly says
  not to compute an overall score.
- Code computes `overall = round(0.50·skill + 0.30·role + 0.20·experience)`.
- Levels: `strong ≥ 80`, `potential ≥ 60`, else `weak`.
- Ranking: sort by `(overall, skill, role, experience)` descending.
- Weights and thresholds are constants with unit tests; changing them is a reviewed code change.

## Alternatives considered

| Option | Why not |
|---|---|
| LLM returns the overall score | Not reproducible; weights invisible; hard to tune. |
| LLM ranks the list directly | Context-size limits; unstable ordering; no per-job audit. |
| Learned model (e.g. logistic regression on approvals) | Needs labelled data first; possible later, would supersede this ADR. |

## Consequences

- Positive: explainable, testable, cheap to tune; identical inputs → identical decisions.
- Negative: sub-scores still come from the LLM, so variance moves there; needs stability evals.
- Follow-ups: tune weights/thresholds on the golden set; consider making them profile-configurable.

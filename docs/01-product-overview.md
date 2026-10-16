# 01 — Product overview

## Problem

Searching Naukri by hand is repetitive: the same searches every day, many irrelevant results
(frontend, full-stack, unrelated "software engineer" roles), and no memory of which jobs were
already reviewed. Evaluating fit against a resume is slow and inconsistent, and application
tracking lives in the candidate's head.

## What the system does

1. **Discover** — search Naukri on a schedule with Playwright. *(Built: Temporal Schedule `discovery-schedule`, or one run now via `main.py`.)*
2. **Remember** — store every job in PostgreSQL, deduplicated by URL. *(Built.)*
3. **Evaluate** — keyword filter → semantic ranking → LLM evaluation → deterministic score. *(Built.)*
4. **Prepare** — assemble what the application needs (answers, resume variant). *(Planned.)*
5. **Ask** — present the job, score and reasoning to the human and wait. *(In progress: CLI prototype.)*
6. **Apply** — submit only after approval, with screenshots as evidence. *(Planned.)*

## Goals

- Reduce daily job-search effort to reviewing a short, ranked list.
- Make every recommendation explainable (sub-scores, matching/missing skills, concerns).
- Never apply without an explicit, recorded human decision.
- Stay free and self-hosted; the only paid item is the existing Claude subscription.
- Be built to production standards (typed, tested, migrated, observable) as a learning vehicle.

## Non-goals

- Mass or unattended applying. Volume is not a goal; quality of matches is.
- Bypassing CAPTCHAs, bot detection or login challenges. If Naukri blocks, the system stops.
- Supporting job boards other than Naukri in the near term (the `JobSource` interface allows it later).
- Multi-tenant SaaS. The system is single-user until [Phase 6](12-roadmap-and-status.md#phases).
- Writing or fabricating resume content. The LLM evaluates; it does not invent experience.

## Users

| User | Needs |
|---|---|
| **Candidate (owner/operator)** — one person, runs everything locally | A short ranked list, clear reasons, a one-click approve/reject, a record of what was applied to. |
| **Developer (contributor)** | Clear architecture, reproducible setup, tests, and documented decisions. |

## Success metrics

| Metric | Target (initial) | Measured from |
|---|---|---|
| Relevant-job precision: share of `strong`/`potential` matches the user approves | ≥ 60 % | `applications` (planned) vs `job_matches` |
| Time from discovery to approval request | < 24 h | `jobs.first_seen_at` → approval requested |
| Applications submitted without approval | **0** (hard invariant) | `applications.approved_at IS NULL AND submitted_at IS NOT NULL` |
| Discovery run success rate | ≥ 95 % | `pipeline_runs` (planned) |
| LLM cost | Within Claude subscription limits; no API spend | Provider logs |
| Duplicate LLM evaluations of the same job | 0 | `job_matches` unique per job (and per user later) |

## Ethics and Naukri Terms of Service risk

Naukri has no public job-seeker API. Automating the website **may violate Naukri's Terms of
Service** and can lead to account restriction or ban. This is an accepted, personal risk for a
learning project. Mitigations that are mandatory in the design:

- **Human approval before any submission** ([ADR-008](adr/ADR-008-mandatory-human-approval.md)).
- **Human-like pace**: low volume, randomized delays, headed browser by default, no parallel sessions
  against Naukri ([06](06-browser-automation.md#rate-limiting-and-delays)).
- **No evasion**: no CAPTCHA solving, no fingerprint spoofing, no proxy rotation. A block is a stop signal.
- **Own account only**: the system acts only as the logged-in candidate.
- **Data minimisation**: store only job data needed for matching; the candidate's PII stays local
  except the profile fields sent to the LLM ([10](10-security.md)).
- **Truthfulness**: applications use the candidate's real profile; the LLM must not invent claims.

Recruiters receive applications that a human decided to send. That is the ethical line this
project holds.

## Why human-in-the-loop

- **Irreversible action**: a submitted application cannot be withdrawn cleanly and affects reputation.
- **LLM error**: scores come from a model reading a short snippet
  ([known issue](12-roadmap-and-status.md#known-issues)); it will be wrong sometimes.
- **ToS exposure**: human-paced, human-approved actions are lower risk than autonomous ones.
- **Learning signal**: approve/reject decisions are labelled data for evaluating the matcher ([05](05-agent-design.md#evals)).

Approval is enforced in the workflow layer, not in the prompt: the submit activity cannot be reached
without an approval signal ([03](03-workflows.md#approval-via-signal)).

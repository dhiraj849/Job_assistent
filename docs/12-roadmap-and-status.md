# 12 — Roadmap and status

Verified against commit `65c1375`. Update this file in the same PR that changes a feature's status.

## Feature status

| Area | Feature | Status | Evidence |
|---|---|---|---|
| Config | Typed settings from `.env` | Built | `app/config.py` |
| Config | Candidate profile from YAML | Built | `app/services/profile_loader.py`, `profile.example.yaml` |
| Discovery | Naukri search (first results page) via Playwright | Built | `app/job_sources/naukri.py`, `app/browser/naukri_browser.py` |
| Discovery | Card extraction (title, company, location, exp, snippet, skills, URL) | Built | `app/job_sources/naukri_extractor.py` |
| Discovery | Pagination | Planned | — |
| Discovery | Detail-page scraping (full JD) | In progress | `scripts/inspect_job_page.py` (HTML capture only), unused `DETAIL_PAGE_DELAY_SECONDS` |
| Discovery | Scheduled runs | Planned | — |
| Storage | `jobs` table, dedupe by URL, `last_seen_at` refresh | Built | `app/db/job_repository.py:19`, migration `e38fb9a63e38` |
| Storage | `job_matches` table | Built | migration `6fc31f68061a` |
| Storage | Job lifecycle status | Planned | — |
| Storage | `applications` table (UNIQUE job_id, outcome, reason, dry_run, approved_at, applied_at, artifacts_dir; CHECK constraints) | Built | `app/db/models.py` (`ApplicationRecord`), migration `f734e9e72583` |
| Storage | `users`, `candidate_profiles`, `pipeline_runs`; `user_id` on `applications` | Planned | — |
| Matching | Keyword filter (hardcoded) | Built | `app/services/job_filter_service.py` |
| Matching | Profile-driven filter keywords / role focus | Planned | — |
| Retrieval | fastembed bge-small embeddings | Built | `app/vector/embedder.py` |
| Retrieval | Qdrant collection per model, lazy sync, ID-filtered search | Built | `app/vector/job_vector_store.py`, `app/services/job_ranker.py` |
| Retrieval | Full re-sync script | Built | `scripts/sync_jobs_to_qdrant.py` |
| LLM | Claude structured-output evaluation | Built | `app/llm/claude_code.py`, `app/services/job_match_service.py` |
| LLM | `LLMProvider` interface | Planned | — |
| LLM | Ollama fallback | Planned | — |
| LLM | Timeouts, retries, concurrency | Planned | — |
| LLM | Prompt versioning | Planned | — |
| Scoring | Deterministic 50/30/20 score, levels, ranking | Built | `job_score_service.py`, `job_match_level_service.py`, `job_ranking_service.py` |
| Agent | Tool-calling prototype (`search_jobs`, `get_job_details`) | In progress | `app/agent/` |
| Approval | CLI yes/no prompt (not persisted) | In progress | `app/agent/approval.py` |
| Approval | Temporal `decide` signal + 3-day timeout (→ `expired`), status in `jobs.status` | Built | `app/workflows/job_application_workflow.py`, `scripts/list_pending.py`, `scripts/decide_job.py` |
| Approval | Persist decision note + time (`record_approval` activity, `workflow.now()` at the signal, patch `record-approval-v1`) | Built | `app/workflows/job_application_workflow.py`, `app/workflows/activities.py`, `tests/workflows/histories/apply_job_v1.json` |
| Approval | Persist who decided and rejections; API instead of scripts | Planned | — |
| Apply | Application preparation (answers from `answers.yaml`) | Built | `app/services/answers_loader.py`, `app/models/application_answers.py`; validated by `ApplyService` before every apply |
| Apply | Safety rails: `APPLY_MODE`, daily cap (advisory lock), idempotency, typed `ApplyResult`, no-retry apply | Built | `app/services/apply_service.py`, `app/workflows/activities.py` (`apply_job`) |
| Apply | `workflow.patched("apply-job-v1")` versioning + replay test | Built | `app/workflows/job_application_workflow.py`, `tests/workflows/histories/` |
| Apply | Remove `apply-job-v1` patch (`deprecate_patch`) once no pre-patch workflow is open | Planned | — |
| Apply | Live browser apply (`NaukriJobApplier`: session check, button classify, chatbot answers, confirmation, step artifacts) | Built (first live run OK 2026-10-07: job 25, no questions, confirmed) | `app/browser/job_applier.py`, `app/browser/apply_page.py` |
| Apply | Deterministic question mapper (no LLM; unknown → `needs_manual`) | Built | `app/browser/apply_questions.py` |
| Apply | Manual one-job live apply with y/N confirmation | Built | `scripts/apply_one.py` |
| Apply | Idempotency + daily cap from `applications` (fixes re-apply after `jobs.status` was overwritten to `approved`); result and `jobs.status` in one commit | Built | `app/services/apply_service.py`, `app/db/job_repository.py`, `tests/integration/test_applications_db.py` |
| Apply | Record manual applies / list jobs needing attention with reason / backfill of jobs 23 + 25 | Built | `scripts/mark_applied.py`, `scripts/list_pending.py`, `scripts/backfill_applications.py` |
| Apply | Remove `record-approval-v1` patch once no workflow approved before it is open | Planned | — |
| Browser | Session reuse (`storage_state`, Fernet-encrypted, manual login script) | Built | `app/browser/session_store.py`, `scripts/naukri_login.py` |
| Apply | Apply-flow inspection tool (button type, optional single click, no submit) | Built | `scripts/inspect_apply_flow.py`, `app/browser/apply_button.py` |
| Apply | Verify apply selectors on live pages (verified: login marker, company-site + Naukri apply buttons, apply confirmation; not yet: already-applied, chatbot) | In progress | `app/browser/naukri_selectors.py`, `tests/fixtures/naukri/` |
| Browser | Rate limiting / delays | Planned | — |
| Browser | Screenshots / artifacts (MinIO) | Planned | — |
| Workflows | Temporal `JobDiscoveryWorkflow` (search + save, starts one child per new job) | Built | `app/workflows/`, `scripts/start_discovery.py` |
| Workflows | Temporal `JobApplicationWorkflow` (filter → semantic score → LLM match → approval → apply with safety rails) | Built | `app/workflows/job_application_workflow.py`, `scripts/start_job_workflow.py` |
| Workflows | `jobs.status` lifecycle (`JobStatus`) + Pydantic data converter | Built | `app/models/job_status.py`, migration `b5d33dd745b3`, `app/workflows/client.py` |
| Workflows | Temporal Schedule for discovery | Planned | — |
| API / UI | FastAPI, Next.js dashboard | Planned | — |
| Observability | structlog console/JSON | Built | `app/logging_config.py` |
| Observability | OpenTelemetry, Grafana stack, Langfuse | Planned | — |
| Testing | Unit tests (63) | Built | `tests/` |
| Testing | Integration tests, evals | Planned | — |
| CI | GitHub Actions | Planned | — |
| Infra | Docker Compose: Postgres 16, Qdrant | Built | `docker-compose.yml` |
| Infra | Alembic async migrations | Built | `alembic/` |

## Phases

Proposed; adjust as priorities change.

| Phase | Goal | Scope | Exit criteria |
|---|---|---|---|
| **0 — Foundations & cleanup** | Safe, reproducible repo | Rotate + remove leaked secrets; ~~declare `claude-agent-sdk`~~ (done); complete `.env.example`; stop logging `name`; remove X settings; decide on `server.py`; fix return type; `__main__` guards in scripts; ruff + mypy + CI (unit) + gitleaks | Fresh clone → `uv sync --locked` → `main.py` works; CI green |
| **1 — Discovery quality** | Better input data | Detail-page scraping with delays; `jobs.status` + lifecycle; profile-driven filter keywords and role focus; pagination; re-embed on details; selector fixtures + tests | No job re-processed after a terminal state; JD length ≫ snippet |
| **2 — Matching hardening** | Reliable, measurable LLM step | `LLMProvider` + Ollama fallback; timeout/retry; bounded concurrency; async embedding/Qdrant; prompt files + versioning; golden-set evals; PII-minimised prompt; remove `app/agent/` duplication | Eval report per prompt version; no event-loop blocking |
| **3 — Durable workflows + approval** | Temporal in place | Temporal in Compose; discovery + application workflows; approval signal + timeout; `applications`, `pipeline_runs` tables; minimal FastAPI (list matches, approve/reject) | Kill worker mid-run → run resumes; no submit path without approval (tested) |
| **4 — Apply (dry-run first)** | Prepared applications | `storage_state` login script + encryption; apply flow; screenshots to MinIO; dry-run default; daily caps | 10 dry-run applications reviewed manually; then live behind config flag |
| **5 — Dashboard + observability** | Usable daily | Next.js approval queue; OTel + Grafana stack; Langfuse; alerts | Daily use from dashboard only; alert on failed discovery |
| **6 — Multi-user** | More than one profile/user | `users`, `candidate_profiles`; per-user `job_matches` uniqueness; per-user status; auth | Two users isolated end to end |

## Known issues

All verified in code unless marked otherwise.

| # | Issue | Evidence | Impact | Fix (phase) |
|---|---|---|---|---|
| 1 | **Secrets in comments in `server.py`, committed and pushed** | `server.py:21-26`; commit `39612aa` is on `origin/main` | Credentials compromised | Rotate all, delete lines, gitleaks ([10](10-security.md#open-incident-secrets-committed-to-git)) (0) |
| 2 | ~~`claude-agent-sdk` and `mcp` imported but not declared~~ **Fixed** | Both now in `pyproject.toml` and `uv.lock` | — | Done (0) |
| 3 | Job description is only the search-card snippet | `app/job_sources/naukri_extractor.py:25` (`.job-desc`); no detail-page code | LLM and embeddings judge on a few lines | Detail-page scraping (1) |
| 4 | `main.py` ignores `jobs.status` → rejected jobs reprocessed every run | `get_unmatched_jobs_with_ids` selects all jobs without a match; only the Temporal workflows set `jobs.status` | `main.py` path: filtered-out / below-threshold jobs re-filtered and re-ranked for 14 days | Retire `main.py` pipeline in favour of the workflows (1) |
| 5 | Blocking embedding and sync Qdrant calls inside async code (`main.py` path; the `semantic_score` activity already uses `asyncio.to_thread`) | `self.ranker.rank(...)` called without `await`/thread in `job_matching_pipeline.py:106`; `Embedder` (fastembed) and `QdrantClient` are sync | Event loop blocked during ranking | `asyncio.to_thread` + `AsyncQdrantClient` (2) |
| 6 | `job_matches.job_id` unique → single-user only | `app/db/models.py:38`, migration `6fc31f68061a:40` | Can't store matches for a second user or a new prompt version | Composite unique key (6; prompt part in 2) |
| 7 | Filter keywords and prompt role focus hardcoded | `job_filter_service.py:8-45`, `job_match_service.py:48-54`; also `app/agent/steps.py:7-10` hardcodes keyword/location | Profile changes don't affect filtering or scoring | Move to `candidate_profiles` / `profile.yaml` (1) |
| 8 | LLM calls sequential, no timeout / retry (`main.py` path; the `match_job` activity has 2 min timeout, 3 attempts, max 3 parallel activities) | `job_matching_pipeline.py:124-150`, `claude_code.py:17-25` | Slow runs; a hung call hangs the run | Timeout, retry, `asyncio.Semaphore` (2) |
| 9 | Wrong return type hint in `ClaudeCodeProvider` | `claude_code.py:13` says `-> str`, returns `JobMatchResult` (`:29`) | Misleading; type checker would flag | Fix hint / introduce `LLMProvider` (0) |
| 10 | Duplicate flows: `app/agent/` vs `JobMatchingPipeline` | `app/agent/steps.py` re-implements search/filter/score/level/rank, with demo data | Two sources of truth for the same logic | Keep one path; agent → tool use inside activities (2) |
| 11 | New jobs can miss their application workflow | `save_jobs` activity commits, then returns ids; if it fails in between, the retry sees the jobs as already seen | Those jobs stay `discovered` with no workflow | Start manually with `scripts/start_job_workflow.py`; later: return ids of the batch still `discovered` (3) |
| 12 | Every new job that passes filter + semantic threshold gets an LLM call | `JobApplicationWorkflow` has no top-N / daily budget (unlike `MAX_MATCH_JOBS` in `main.py`) | More LLM usage per discovery run | Daily LLM budget (2) |
| 13 | ~~Decision note is not persisted~~ **Fixed** (approvals only; rejection notes still are not) | `record_approval` stores note + time in `applications` | — | Done (3) |
| 14 | A re-run workflow for an applied job rewrites `jobs.status` (shortlisted → … → approved) and repeats the LLM match | `_set_status` has no guard; `applications` now blocks the second apply and `apply_job` syncs `jobs.status` back to `applied` | Wasted LLM call; `jobs.status` wrong until approval | Make `applied` terminal in `update_status`, or skip at workflow start (3) |
| 11 | Auto-apply step not implemented | No apply code anywhere; `approval.py` only sets `next_action = "apply"` | Core feature missing | Phase 4 |

## Tech debt (additional findings)

| Item | Evidence |
|---|---|
| Candidate name logged (PII) | `main.py:23`, `app/agent/agent.py:29-33` |
| Full profile incl. name sent to LLM | `job_match_service.py:31` (`model_dump()`) |
| `DETAIL_PAGE_DELAY_SECONDS` defined but unused | `app/config.py:32` |
| X API settings left over from MCP experiment | `app/config.py:48-51` |
| `.env.example` lacks `POSTGRES_*`, which Compose requires | `.env.example`, `docker-compose.yml:6-8` |
| `.mcp.json` hardcodes an absolute path to `venv/` (the project uses `.venv`) | `.mcp.json` |
| Scripts run on import (no `if __name__ == "__main__"`) | `scripts/search_jobs.py:34`, `scripts/sync_jobs_to_qdrant.py:49`, `scripts/embedding_demo.py` |
| Semantic threshold inconsistent (0.7 vs 0.07) and untuned | `job_ranker.py:10`, `scripts/search_jobs.py:25` |
| `JobMatchService` constructs its LLM provider (no injection) | `job_match_service.py:11` |
| Filter's `matched_keywords` computed then discarded; substring matching gives false positives (`rag`, `rest`) | `job_filter_service.py`, `job_matching_pipeline.py:95` |
| Agent tool ignores `BROWSER_HEADLESS` / timeout settings | `app/agent/claude_tools.py:38` |
| Imports in the middle of `app/agent/steps.py` | `steps.py:18,39,55,99,115,130` |
| No async tests; no coverage tool; no linter/type checker configured | `pyproject.toml` |
| Postgres and Qdrant ports published on all interfaces, Qdrant without API key | `docker-compose.yml` |
| Package named `mcp-server`; repo named `Job_assistent` | `pyproject.toml:2` |
| No root README (added by this documentation change) | — |
| Untracked `chat_gpt_backup.zip`, `claude_for_understand.zip`, `venv/` in the working tree | gitignored; confirm they contain no secrets before sharing the folder |

## Open questions

1. Should `server.py` / the MCP experiment move to its own repo or be deleted? (Affects whether `mcp` is declared.)
2. Rewrite git history after rotating the leaked credentials, or rotation only?
3. ~~Approval timeout~~ **Decided:** 3 days; on timeout the job becomes `expired`.
4. ~~Approval threshold~~ **Decided:** `strong` + `potential` wait for approval.
5. ~~Terminal state for weak matches~~ **Decided:** `weak` ends as `filtered_out`.
6. Is `failed` retryable by a new approval, or terminal?
7. Where does per-user lifecycle state live in Phase 6 (`jobs.status` is global)?
8. Should jobs that fall outside the top N but pass the threshold be evaluated in the same run (bounded by a budget) rather than in later runs?
9. Ollama model choice for the fallback (needs a golden-set comparison).
10. Is GitHub Actions the CI target (the remote is GitHub, but not confirmed)?

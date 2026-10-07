# 03 — Workflows

> **Status: In progress.** On Temporal today: `JobDiscoveryWorkflow` (search + save, starts one child
> per new job) and `JobApplicationWorkflow` (evaluate → human approval → apply behind safety rails,
> **dry-run by default**) — see [Discovery workflow](#discovery-workflow-built) and
> [Application workflow](#application-workflow-built-dry-run).
> Sections from [Target workflows](#target-workflows) on are the remaining design.
> [Current flow](#current-flow-built) describes the older all-in-one pipeline in `main.py`.

## Current flow (Built)

`main.py` → `JobMatchingPipeline.run()` (`app/services/job_matching_pipeline.py:38`), one process,
no retries, no persistence of intermediate state beyond `jobs` and `job_matches`.

```mermaid
sequenceDiagram
    autonumber
    participant M as main.py
    participant P as JobMatchingPipeline
    participant N as NaukriJobSource (Playwright)
    participant R as JobRepository (Postgres)
    participant F as JobFilterService
    participant K as JobRanker (fastembed + Qdrant)
    participant L as JobMatchService (Claude)
    M->>P: run(candidate, max_match_jobs)
    P->>N: get_jobs()
    N-->>P: jobs from search cards
    P->>R: save_jobs(jobs) (dedupe by url)
    P->>R: get_unmatched_jobs_with_ids(14 days)
    R-->>P: [(id, job)]
    P->>F: filter_jobs(jobs)
    P->>K: rank(candidate, jobs_with_ids, limit=N)
    K-->>P: top N with cosine ≥ 0.7
    loop each selected job (sequential)
        P->>L: match(candidate, job)
        L-->>P: JobMatchResult (JSON)
        P->>P: score 50/30/20, classify level
        P->>R: save_match(job_id, ...)
    end
    P-->>M: ranked JobMatchItems (printed)
```

## Discovery workflow (Built)

`app/workflows/` — finds and stores jobs, then hands each **new** job to its own
[application workflow](#application-workflow-built-dry-run).

| Piece | File | What it does |
|---|---|---|
| `JobDiscoveryWorkflow.run(keyword, location)` | `job_discovery_workflow.py` | Calls `discover_jobs`, then `save_jobs` (skipped if nothing found), then starts one child `JobApplicationWorkflow` (id `job-{id}`, `ParentClosePolicy.ABANDON`) per new job id. Returns `{"found": N, "new": M}`. |
| `discover_jobs(keyword, location) -> list[Job]` | `activities.py` | Wraps `NaukriJobSource.get_jobs`. start-to-close **3 min**. |
| `save_jobs(jobs) -> list[int]` | `activities.py` | Own `SessionLocal` session; `JobRepository.save_jobs(source="naukri")` + `get_ids_by_urls`; returns the ids of the new jobs. start-to-close **30 s**. |
| Client | `client.py` | `connect_client()` — the only way to connect; always uses `pydantic_data_converter`. |
| Worker | `worker.py` | Registers both workflows + all activities on `TEMPORAL_TASK_QUEUE`, `max_concurrent_activities=3` (caps parallel LLM / browser work); logs `worker_started` with `apply_mode` and `max_applies_per_day`, so the log shows which safety rails the running worker uses. |
| Starter | `scripts/start_discovery.py` | Starts the workflow with ID `discovery-{keyword}-{location}` (slugified), waits, prints the result. |

- **Retry policy** (all activities, `app/workflows/retry.py`): max 3 attempts, initial interval 10 s, backoff 2.0.
- **Payloads are our Pydantic models** (`Job`, `JobMatchItem`, `JobStatus`) via
  `temporalio.contrib.pydantic.pydantic_data_converter`. Worker, scripts and tests must all use it.
- **ABANDON** lets discovery complete while its children keep waiting (up to 3 days) for approval.
- **Determinism:** activities are imported inside `workflow.unsafe.imports_passed_through()`; all
  browser and DB I/O stays in activities.
- **Workflow ID** is stable per search, so a second start while one is running fails with
  `WorkflowAlreadyStartedError` (the script prints a message). A finished run can be started again.
- **Tests:** `tests/workflows/test_job_discovery_workflow.py` uses `WorkflowEnvironment.start_time_skipping()`
  with fake activities registered under the real names and a stub child workflow (no browser, no DB).
- **Known gap:** if `save_jobs` commits but the activity fails before returning, the retry sees those
  jobs as "already seen" and no child is started for them; start them with `scripts/start_job_workflow.py`.

```mermaid
sequenceDiagram
    autonumber
    participant S as scripts/start_discovery.py
    participant T as Temporal server
    participant W as JobDiscoveryWorkflow
    participant D as discover_jobs
    participant V as save_jobs
    S->>T: start discovery-{keyword}-{location}
    T->>W: run(keyword, location)
    W->>D: execute (3 min, 3 attempts)
    D-->>W: list[Job]
    alt jobs found
        W->>V: execute(jobs) (30 s, 3 attempts)
        V-->>W: new job ids
        loop each new id
            W->>T: start child job-{id} (ABANDON)
        end
    end
    W-->>S: {"found": N, "new": M}
```

## Application workflow (Built, dry-run)

`JobApplicationWorkflow.run(job_id) -> str` in `app/workflows/job_application_workflow.py`,
workflow id **`job-{job_id}`**. Started by discovery (child) or `scripts/start_job_workflow.py`.
Returns the final status. Apply runs through `apply_job` and its [safety rails](#apply-safety-rails-built).
`APPLY_MODE=dry_run` is the default; live browser apply is built but its chatbot selectors are not
yet verified ([06](06-browser-automation.md#live-apply-built-chatbot-selectors-not-verified)).

| Activity | Reuses | Timeout | Result |
|---|---|---|---|
| `is_applied_live(job_id)` | `JobRepository.is_applied_live` (reads `applications`) | 30 s | `bool` |
| `load_job(job_id)` | `JobRepository.get_job` | 30 s | `Job` |
| `filter_job(job)` | `JobFilterService.filter_jobs` | 30 s | `bool` |
| `semantic_score(job_id, job)` | `JobRanker.rank(..., limit=1)` (run in a thread; embedder cached per worker) | 1 min | `float`, or `None` below `MIN_SCORE` 0.7 |
| `match_job(job)` | `JobMatchService` + `JobScoreService` + `JobMatchLevelService` | 2 min | `JobMatchItem` |
| `save_match(job_id, item)` | `JobRepository.save_match` (upsert) | 30 s | — |
| `update_job_status(job_id, status)` | `JobRepository.update_status` (refused + `job_status_update_refused` warning for a job applied live, unless the status is `applied`) | 30 s | — |
| `record_approval(job_id, approved_at, note)` | `JobRepository.record_approval`: `applications` row `pending` + `job_decisions` row `approved` + `jobs.status=approved`, one commit; leaves a job applied live untouched | 30 s | — |
| `record_decision(job_id, decision, decided_at, note)` | `JobRepository.record_decision`: `job_decisions` row (`rejected` / `expired`) + `jobs.status`, one commit | 30 s | — |
| `apply_job(job_id)` | `ApplyService` (`app/services/apply_service.py`) | 5 min | `ApplyResult` |
| `apply_job_dry_run(job_id)` | `JobRepository.get_job`, logs `apply_dry_run` | 30 s | message — **old histories only** (pre-patch), still registered on the worker |

All except `apply_job` use the shared retry policy (max 3 attempts). `apply_job` uses
`APPLY_RETRY_POLICY` (**1 attempt**): retrying a half-finished apply could apply twice. The profile is loaded inside activities from
`settings.PROFILE_PATH` on every call.

- **Signal** `decide(approved: bool, note: str = "")`. Ignored (logged) unless the status is
  `awaiting_approval` and no decision was made yet, so nothing is approved early.
- **Query** `current_status() -> str`.
- **Already applied live → stop.** The first step is `is_applied_live`: if `applications` has a live
  `applied` row, the workflow returns `applied` at once (no `load_job`, no LLM, no status write, no
  approval prompt). Protects re-runs, e.g. `scripts/start_job_workflow.py` on an applied job.
- **Approval timeout: 3 days** (`workflow.wait_condition`). On timeout → `expired`, logged by
  `record_decision` with `decided_at = workflow.now()` at the timeout. Silence never means yes.
- Only `strong` and `potential` matches wait for approval; `weak` ends as `filtered_out`.
- Every status change goes through an activity (`update_job_status`, `record_approval`, `apply_job`);
  the workflow keeps only an in-memory copy for the query.
- **Approval is recorded** by `record_approval` with the note and the decision time. The time is
  `workflow.now()` taken in the signal handler: deterministic on replay, and the real decision time
  even if the activity runs later. A rejection is logged by `record_decision` (note + decision time)
  in `job_decisions`, never in `applications` (a row there means "approved").
- **Run id:** `record_approval` / `record_decision` read `activity.info().workflow_run_id` and store
  it as the `job_decisions` idempotency key, so a retried activity logs the decision once.
- If an activity gives up after its retries, the workflow sets `failed` and then fails (visible in the UI).
- **Scripts:** `scripts/list_pending.py` (jobs in `awaiting_approval` with LLM score + level, then
  `needs_manual` / `failed` jobs with their reason), `scripts/mark_applied.py <job_id> --reason`
  (records an apply done by hand),
  `scripts/decide_job.py <job_id> yes|no [note]` (checks status via the query, then signals),
  `scripts/start_job_workflow.py <job_id>` (for jobs saved before workflows existed).
- **Tests:** `tests/workflows/test_job_application_workflow.py` — approved, rejected,
  3-day timeout → expired, weak → filtered_out, needs_manual, cap wait + retry, cap → expired after
  3 days, `record_approval` gets the note and decision time (and is not called on reject),
  `record_decision` gets the rejection note/time and the timeout time, an already-applied job never
  reaches `load_job` / `match_job`, and replay of the pre-`apply-job-v1`, pre-`record-approval-v1`,
  pre-`record-decision-v1` and current histories, plus a real one (`record_approval_v1.json`, job-38
  from the local server) (time-skipping server, fake activities).

```mermaid
stateDiagram-v2
    [*] --> discovered: save_jobs
    discovered --> applied: is_applied_live true (re-run)
    discovered --> filtered_out: filter_job false
    discovered --> filtered_out: semantic_score None
    discovered --> shortlisted: passes filter + score ≥ 0.7
    shortlisted --> matched: match_job + save_match
    matched --> filtered_out: level weak
    matched --> awaiting_approval: level strong / potential
    awaiting_approval --> approved: decide(yes) + record_approval
    awaiting_approval --> rejected: decide(no) + record_decision
    awaiting_approval --> expired: no decision in 3 days + record_decision
    approved --> applied_dry_run: apply_job (dry_run)
    approved --> applied: apply_job (live) / already applied
    approved --> needs_manual: company site / unknown question
    approved --> failed: bad answers.yaml / browser error
    approved --> approved: daily cap full, sleep until next IST day
    approved --> expired: cap still full after 3 more days
    shortlisted --> failed: activity retries exhausted
    filtered_out --> [*]
    rejected --> [*]
    expired --> [*]
    applied_dry_run --> [*]
    applied --> [*]
    needs_manual --> [*]
    failed --> [*]
```

### Apply safety rails (Built)

`ApplyService.apply(job_id)` (called by the `apply_job` activity) runs these checks in order:

1. **Lock** — `JobRepository.lock_applies()` takes a Postgres advisory transaction lock
   (`pg_advisory_xact_lock`). It is held until the final result is committed, so two parallel
   activities cannot both pass the cap check ("check-then-act" race).
2. **Approval** — no `applications` row → `NotApprovedError` (the activity fails; nothing is opened).
3. **Idempotency** — from `applications`, not `jobs.status`: row applied live → `already_applied`,
   and `jobs.status` is synced back to `applied`. `jobs.status` alone could not be trusted: the
   workflow writes `approved` before every apply, so a re-run workflow (or a manual apply while it
   waited) used to wipe `applied` and the job was applied again.
4. **Daily cap** — counts `applications` rows applied (live, or dry run in dry-run mode) since the
   start of the **IST day**. At `MAX_APPLIES_PER_DAY` → `skipped_cap` with `retry_after_seconds`
   until IST midnight; the row stays `pending`. Dry runs never use up the live quota.
5. **Answers** — `answers.yaml` is loaded and validated in both modes; missing / invalid → `failed`.
6. **Apply** — `APPLY_MODE=dry_run`: logs only; the browser applier is never even built.
   `live`: `NaukriJobApplier.apply(job_id, job, answers)` (`app/browser/job_applier.py`) →
   `ApplierResult` `applied` / `needs_manual` / `already_applied` with a `reason` (e.g. the unknown
   question) copied into `ApplyResult.reason`; any exception (incl. expired session, apply not
   confirmed) → `failed`. The lock stays held during the browser apply (minutes), which is fine
   with one apply at a time.

`ApplyResult` (`app/models/apply_result.py`): `outcome` (`applied`, `needs_manual`, `failed`,
`skipped_cap`, `already_applied`), `dry_run`, `reason`, `retry_after_seconds`.

The activity writes the result itself with `JobRepository.save_apply_result`: `applications`
(`outcome`, `reason`, `dry_run`, `applied_at`, `artifacts_dir` = `artifacts/apply/<job_id>`) **and**
`jobs.status` in one commit inside the lock, so both change or neither does. The update refuses a row
already applied live (`ApplicationNotWritableError`), a DB-level backstop to step 3. The workflow only
mirrors the status for the query. Settings are read only inside the activity, never in the workflow, so a
changed env var cannot change what a replayed workflow does.

On `skipped_cap` the workflow `workflow.sleep()`s for `retry_after_seconds` (a durable timer) and
tries again, up to `MAX_CAP_WAIT_DAYS` = 3 more days, then sets `expired`.

### Versioning with `workflow.patched` (Built)

The switch from `apply_job_dry_run` to `apply_job` is guarded by `workflow.patched("apply-job-v1")`.

- Temporal recovers a workflow by **replaying** its code against its event history. If the code now
  schedules `apply_job` where the history says `apply_job_dry_run`, replay fails with a
  non-determinism error and the workflow is stuck.
- `patched()` returns `True` when the code runs for the first time at that point (and records a
  `core_patch` marker in history), or on replay of a history that has the marker. It returns `False`
  only on replay of a history **without** the marker → the old branch runs.
- So workflows that were `awaiting_approval` during the deploy take the **new** path when approved
  (that code runs for the first time). The patch protects histories that had already scheduled
  `apply_job_dry_run`.
- Test: `tests/workflows/histories/apply_dry_run_v0.json` is a history recorded with the pre-patch
  code; a `Replayer` test replays it with the current code.
- `workflow.patched("record-approval-v1")` guards the switch from `update_job_status(APPROVED)` to
  `record_approval` the same way; `tests/workflows/histories/apply_job_v1.json` (recorded with the
  code before it) is replayed in a test.
- `workflow.patched("skip-if-applied-v1")` guards the `is_applied_live` check at the very start of
  `run`. Open workflows started earlier have `load_job` as their first command, so on replay the
  patch returns `False` and they skip the check.
- `workflow.patched("record-decision-v1")` guards `update_job_status(REJECTED/EXPIRED)` →
  `record_decision`; `rejected_v1.json` / `expired_v1.json` (recorded with the code before it) replay
  in a test.
- Removal (later): once no pre-patch workflow is open, replace `patched()` with
  `workflow.deprecate_patch("apply-job-v1")` and delete the old branch; after those workflows are
  gone too, remove the call and stop registering `apply_job_dry_run`.

## Target workflows

| Workflow | Workflow ID | Started by | Purpose |
|---|---|---|---|
| `JobDiscoveryWorkflow` | `discovery-{user_id}-{scheduled_time}` | Temporal Schedule (e.g. twice a day) or API "run now" | Find, store, filter, rank and evaluate new jobs; start application workflows for good matches. |
| `JobApplicationWorkflow` | **`job-{job_id}`** | `JobDiscoveryWorkflow` (child or via client start) | Take one matched job through approval and (optionally) submission. |

Using `job-{job_id}` as the workflow ID makes the application flow **idempotent per job**: starting
it twice fails with "already started", so a job can never get two parallel application flows.
Use `WorkflowIDReusePolicy.REJECT_DUPLICATE` so a finished job is never re-applied automatically.
(Becomes `job-{user_id}-{job_id}` in the multi-user phase.)

## Activities

| Activity | Used by | Maps to current code | Retry policy | Notes |
|---|---|---|---|---|
| `search_jobs(keyword, location)` | Discovery | `NaukriJobSource.get_jobs` | 3 attempts, backoff 30 s → 5 min | Heartbeat per page. |
| `persist_jobs(jobs)` | Discovery | `JobRepository.save_jobs` | default | Idempotent (URL unique). |
| `fetch_job_details(job_id)` | Discovery | — (planned) | 3 attempts | Rate-limited; sets `details_fetched`. |
| `filter_jobs(job_ids)` | Discovery | `JobFilterService.filter_jobs` | default | Sets `filtered_out` / `shortlisted`. Profile-driven keywords. |
| `rank_jobs(job_ids, limit)` | Discovery | `JobRanker.rank` | default | Runs embedding in a thread. |
| `match_job(job_id)` | Discovery | `JobMatchService.match` + score + level + `save_match` | 3 attempts, start-to-close 120 s | LLM call; validated JSON; sets `matched`. |
| `notify_approval_requested(job_id)` | Application | — | default | Dashboard notification (later: email / push). |
| `prepare_application(job_id)` | Application | — | default | Collect answers, choose resume, store preview. |
| `submit_application(job_id, dry_run)` | Application | — | **maximum_attempts = 1** | Not idempotent on Naukri's side — never auto-retry. Screenshots before/after to MinIO. |
| `record_outcome(job_id, status, error)` | Both | — | default | Updates `applications` / job status. |

Workflow code only calls activities, timers and signals; all I/O is in activities.

## Approval via signal

- Signals: `approve(approved_by, note)`, `reject(reason)`.
- Query: `get_state()` → current status, match summary, deadline.
- Timeout: `await workflow.wait_condition(lambda: decision is not None, timeout=APPROVAL_TIMEOUT)`.
  - **Built:** `APPROVAL_TIMEOUT` = 3 days; on timeout the job moves to `expired`. Silence never means yes.
- The API sends the signal by workflow ID `job-{job_id}` after authenticating the user.
- The approval decision (who, when, note) is written to `applications` before `submit_application`
  is scheduled. `submit_application` asserts that record exists.

```mermaid
sequenceDiagram
    autonumber
    participant S as Temporal Schedule
    participant D as JobDiscoveryWorkflow
    participant A as Activities (worker)
    participant AW as JobApplicationWorkflow (job-{id})
    participant API as FastAPI
    participant U as Candidate (dashboard)

    S->>D: start
    D->>A: search_jobs → persist_jobs
    D->>A: fetch_job_details (per new job, rate-limited)
    D->>A: filter_jobs → rank_jobs
    D->>A: match_job (bounded concurrency)
    D->>AW: start for each job with level ≥ threshold
    AW->>A: notify_approval_requested
    AW->>AW: state = awaiting_approval
    U->>API: Approve job 42
    API->>AW: signal approve
    alt approved within timeout
        AW->>A: prepare_application
        AW->>A: submit_application(dry_run?)
        A-->>AW: ok / error
        AW->>A: record_outcome(applied | failed)
    else rejected or timeout
        AW->>A: record_outcome(rejected)
    end
```

### Dry-run mode

`submit_application(dry_run=True)` performs every step up to — but not including — the final
submit click, captures screenshots, and records `applied_dry_run` in `applications.dry_run`.
Dry-run is the **default** until the apply flow has been validated manually ([06](06-browser-automation.md#dry-run-mode-planned)).

## Job lifecycle state machine

```mermaid
stateDiagram-v2
    [*] --> discovered: search_jobs + persist_jobs
    discovered --> details_fetched: fetch_job_details
    details_fetched --> filtered_out: filter / rank rejects
    details_fetched --> shortlisted: passes filter + semantic threshold
    shortlisted --> matched: match_job (LLM + score + level)
    matched --> awaiting_approval: level ≥ threshold, workflow started
    awaiting_approval --> approved: signal approve
    awaiting_approval --> rejected: signal reject / timeout
    approved --> applying: submit_application started
    applying --> applied: success
    applying --> failed: error / blocked
    filtered_out --> [*]
    rejected --> [*]
    applied --> [*]
    failed --> [*]
```

| State | Meaning | Stored as (planned) | Exists today? |
|---|---|---|---|
| `discovered` | Row in `jobs` from a search card | `jobs.status` | Yes (default) |
| `details_fetched` | Detail page scraped, full description saved | `jobs.status` | No |
| `filtered_out` | Failed keyword filter, semantic threshold, or `weak` LLM level | `jobs.status` | Yes (workflow path; `main.py` still re-processes) |
| `shortlisted` | Selected for LLM evaluation | `jobs.status` | Yes (workflow path) |
| `matched` | LLM result + score saved | `jobs.status` + `job_matches` row | Yes (workflow path; migration backfilled old matches) |
| `awaiting_approval` | Application workflow waiting for signal | `jobs.status` | Yes |
| `approved` | Human said yes | `jobs.status` + `applications` row `pending` (time + note) | Yes |
| `rejected` / `expired` | Human said no, or 3-day timeout | `jobs.status` + `job_decisions` row (note + time) | Yes |
| `applied_dry_run` | Dry-run apply logged | `jobs.status` + `applications` `applied`, `dry_run=true` | Yes |
| `applied` | Applied for real (or Naukri already showed "Applied", or `mark_applied`) | `jobs.status` + `applications` `applied` | Yes |
| `needs_manual` | Approved, but a human must finish it (company site, unknown question) | `jobs.status` + `applications` (reason) | Yes |
| `failed` | Activity retries exhausted, bad `answers.yaml`, browser error, expired session, apply not confirmed | `jobs.status` (+ `applications` with reason if it failed in `apply_job`) | Yes |
| `applying` | Submission in progress | `applications.outcome` | No |

Rules:

- Transitions happen only inside activities, in the same DB transaction as the data they describe.
- `matched` jobs below the approval threshold stay in `matched` and are not surfaced (open question:
  add an explicit `not_recommended` terminal state?).
- `failed` is terminal for automation; a retry is a new human decision (open question).
- `last_seen_at` refresh does not change state.

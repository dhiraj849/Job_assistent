"""JobApplicationWorkflow tests with fake activities (no browser, DB, Qdrant or LLM).

Fakes are registered under the real activity names. The time-skipping test
server jumps over the 3-day approval timeout (and daily-cap waits) instantly.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from temporalio import activity
from temporalio.client import WorkflowHandle, WorkflowHistory
from temporalio.exceptions import ApplicationError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from app.models.apply_result import ApplyOutcome, ApplyResult
from app.models.decision import Decision
from app.models.job import Job
from app.models.job_details import JobDetails
from app.models.job_match import JobMatchResult
from app.models.job_match_item import JobMatchItem
from app.models.job_status import JobStatus
from app.workflows.job_application_workflow import (
    APPROVAL_TIMEOUT,
    DETAILS_DEADLINE,
    JobApplicationWorkflow,
)
from app.workflows.task_queues import BROWSER_TASK_QUEUE

TASK_QUEUE = "test-job-application"
JOB_ID = 42

JOB = Job(
    title="Python Backend Engineer",
    company="Acme",
    location="Noida",
    description="Django, FastAPI",
    url="https://example.com/42",
)


# What fetch_job_details returns: the same job with the full JD.
DETAILED_JOB = JOB.model_copy(
    update={
        "description": "Full JD: build FastAPI services, Postgres, Docker, AWS. " * 3,
        "details": JobDetails(source="json_ld", skills=["Python", "FastAPI"]),
    }
)

HISTORIES = Path(__file__).parent / "histories"

DRY_RUN_APPLIED = ApplyResult(outcome=ApplyOutcome.APPLIED, dry_run=True)
CAP_FULL = ApplyResult(
    outcome=ApplyOutcome.SKIPPED_CAP, dry_run=True, retry_after_seconds=3600
)


def make_activities(
    match_level: str,
    statuses: list[str],
    applied: list[int],
    apply_results: list[ApplyResult],
    applied_live: bool = False,
    calls: list[str] | None = None,
    seen_jobs: list[Job] | None = None,
):
    """Fake activities; statuses/applied record what the workflow did.

    apply_job returns apply_results one by one (last one repeats).
    applied_live is what the applications table says; calls logs
    load_job / match_job (the LLM) runs; seen_jobs gets the Job that
    semantic_score and match_job received.
    """
    calls = calls if calls is not None else []
    seen_jobs = seen_jobs if seen_jobs is not None else []

    @activity.defn(name="is_applied_live")
    async def is_applied_live(job_id: int) -> bool:
        return applied_live

    @activity.defn(name="load_job")
    async def load_job(job_id: int) -> Job:
        calls.append("load_job")
        return JOB

    @activity.defn(name="filter_job")
    async def filter_job(job: Job) -> bool:
        return True

    @activity.defn(name="semantic_score")
    async def semantic_score(job_id: int, job: Job) -> float | None:
        seen_jobs.append(job)
        return 0.82

    @activity.defn(name="match_job")
    async def match_job(job: Job) -> JobMatchItem:
        calls.append("match_job")
        seen_jobs.append(job)
        return JobMatchItem(
            job=job,
            match=JobMatchResult(
                role_match=80, skill_match=80, experience_match=80,
                matching_skills=[], missing_skills=[], strengths=[], concerns=[],
                recommendation="ok",
            ),
            overall_score=80,
            match_level=match_level,
        )

    @activity.defn(name="save_match")
    async def save_match(job_id: int, item: JobMatchItem) -> None:
        return None

    @activity.defn(name="update_job_status")
    async def update_job_status(job_id: int, status: JobStatus) -> None:
        statuses.append(status.value)

    # record_approval also sets jobs.status=approved, so it is logged as a status.
    @activity.defn(name="record_approval")
    async def record_approval(job_id: int, approved_at: datetime, note: str) -> None:
        statuses.append(JobStatus.APPROVED.value)

    # record_decision also sets jobs.status (rejected/expired).
    @activity.defn(name="record_decision")
    async def record_decision(job_id: int, decision: Decision, decided_at: datetime, note: str) -> None:
        statuses.append(decision.value)

    @activity.defn(name="apply_job")
    async def apply_job(job_id: int) -> ApplyResult:
        applied.append(job_id)
        return apply_results[min(len(applied), len(apply_results)) - 1]

    return [is_applied_live, load_job, filter_job, semantic_score, match_job,
            save_match, update_job_status, record_approval, record_decision, apply_job]


def make_browser_activities(details: str, calls: list[str]):
    """Fake fetch_job_details for the browser queue.

    details: "ok" returns DETAILED_JOB, "fail" fails like a broken page.
    """

    @activity.defn(name="fetch_job_details")
    async def fetch_job_details(job_id: int) -> Job:
        calls.append("fetch_job_details")
        if details == "fail":
            raise ApplicationError("no job description found", type="DetailParseError", non_retryable=True)
        return DETAILED_JOB

    return [fetch_job_details]


async def wait_for_status(handle: WorkflowHandle, expected: str) -> None:
    for _ in range(100):
        if await handle.query(JobApplicationWorkflow.current_status) == expected:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"workflow never reached {expected}")


async def run_workflow(
    match_level: str,
    decision: bool | None,
    apply_results: list[ApplyResult] = [DRY_RUN_APPLIED],
    applied_live: bool = False,
    calls: list[str] | None = None,
    details: str = "ok",
    seen_jobs: list[Job] | None = None,
):
    """Run one workflow. decision=None means nobody answers (timeout).

    details: what fetch_job_details does ("ok" / "fail").
    Returns (result, statuses, applied, history).
    """
    statuses: list[str] = []
    applied: list[int] = []
    calls = calls if calls is not None else []
    activities = make_activities(
        match_level, statuses, applied, apply_results, applied_live, calls, seen_jobs
    )

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[JobApplicationWorkflow],
            activities=activities,
        ), Worker(
            env.client,
            task_queue=BROWSER_TASK_QUEUE,
            activities=make_browser_activities(details, calls),
        ):
            handle = await env.client.start_workflow(
                JobApplicationWorkflow.run,
                JOB_ID,
                id=f"job-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )

            if decision is not None:
                await wait_for_status(handle, "awaiting_approval")
                await handle.signal(JobApplicationWorkflow.decide, args=[decision, "test"])

            result = await handle.result()
            history = await handle.fetch_history()

    return result, statuses, applied, history


PRE_APPROVAL = ["shortlisted", "matched", "awaiting_approval"]


def test_approved_job_is_applied_in_dry_run():
    result, statuses, applied, _ = asyncio.run(run_workflow("strong", decision=True))

    assert result == "applied_dry_run"
    # The final status is written by apply_job itself, not update_job_status.
    assert statuses == PRE_APPROVAL + ["approved"]
    assert applied == [JOB_ID]


def test_needs_manual_result_is_returned():
    needs_manual = ApplyResult(outcome=ApplyOutcome.NEEDS_MANUAL, dry_run=False)
    result, _, _, _ = asyncio.run(
        run_workflow("strong", decision=True, apply_results=[needs_manual])
    )

    assert result == "needs_manual"


def test_daily_cap_waits_a_day_and_retries():
    result, statuses, applied, _ = asyncio.run(
        run_workflow("strong", decision=True, apply_results=[CAP_FULL, DRY_RUN_APPLIED])
    )

    assert result == "applied_dry_run"
    assert applied == [JOB_ID, JOB_ID]


def test_daily_cap_gives_up_after_3_days():
    result, statuses, applied, _ = asyncio.run(
        run_workflow("strong", decision=True, apply_results=[CAP_FULL])
    )

    assert result == "expired"
    assert statuses == PRE_APPROVAL + ["approved", "expired"]
    assert applied == [JOB_ID] * 4  # first try + 3 next days


# --- Versioning (workflow.patched) ---------------------------------------
# apply_dry_run_v0.json was recorded with the workflow code from BEFORE the
# "apply-job-v1" patch: its history schedules apply_job_dry_run. Replaying it
# with today's code must take the old branch, or Temporal raises a
# non-determinism error and every such in-flight workflow gets stuck.


def replayer() -> Replayer:
    return Replayer(workflows=[JobApplicationWorkflow], data_converter=pydantic_data_converter)


def test_pre_patch_history_replays_on_old_path():
    history = WorkflowHistory.from_json(
        "job-pre-patch", (HISTORIES / "apply_dry_run_v0.json").read_text()
    )
    # Raises on non-determinism.
    asyncio.run(replayer().replay_workflow(history))


def test_patched_history_replays_on_new_path():
    _, _, _, history = asyncio.run(run_workflow("strong", decision=True))

    # The new path leaves patch markers (skip-if-applied + details + approval
    # + apply) and never schedules the old activities.
    markers = [e for e in history.events if e.HasField("marker_recorded_event_attributes")]
    assert [m.marker_recorded_event_attributes.marker_name for m in markers] == ["core_patch"] * 4
    assert "apply_job_dry_run" not in history.to_json()
    assert '"approved"' not in history.to_json()  # no update_job_status(APPROVED)

    asyncio.run(replayer().replay_workflow(history))


def test_rejected_job_is_not_applied():
    result, statuses, applied, _ = asyncio.run(run_workflow("potential", decision=False))

    assert result == "rejected"
    assert statuses == PRE_APPROVAL + ["rejected"]
    assert applied == []


def test_no_decision_in_3_days_expires():
    result, statuses, applied, _ = asyncio.run(run_workflow("strong", decision=None))

    assert result == "expired"
    assert statuses == PRE_APPROVAL + ["expired"]
    assert applied == []


def test_weak_match_is_filtered_out_without_approval():
    result, statuses, applied, _ = asyncio.run(run_workflow("weak", decision=None))

    assert result == "filtered_out"
    assert statuses == ["shortlisted", "matched", "filtered_out"]
    assert applied == []


# apply_job_v1.json was recorded with the code from BEFORE "record-approval-v1":
# it wrote update_job_status(APPROVED) and then ran apply_job. A workflow in
# that state (e.g. sleeping on the daily cap) must still replay.


def test_pre_approval_patch_history_replays_on_old_path():
    history = WorkflowHistory.from_json(
        "job-apply-v1", (HISTORIES / "apply_job_v1.json").read_text()
    )
    asyncio.run(replayer().replay_workflow(history))


def _scheduled_inputs(history: WorkflowHistory, activity_name: str) -> list[list]:
    """Decoded arguments of every scheduled activity with this name."""
    inputs = []
    for event in history.events:
        if not event.HasField("activity_task_scheduled_event_attributes"):
            continue
        attributes = event.activity_task_scheduled_event_attributes
        if attributes.activity_type.name == activity_name:
            inputs.append([json.loads(p.data) for p in attributes.input.payloads])
    return inputs


def test_approval_is_recorded_with_note_and_decision_time():
    _, _, _, history = asyncio.run(run_workflow("strong", decision=True))

    [(job_id, approved_at, note)] = _scheduled_inputs(history, "record_approval")
    assert job_id == JOB_ID
    assert note == "test"
    # The time comes from workflow.now() at the signal, not from the activity.
    signal = next(e for e in history.events if e.HasField("workflow_execution_signaled_event_attributes"))
    decided = datetime.fromisoformat(approved_at)
    assert decided >= signal.event_time.ToDatetime().replace(tzinfo=decided.tzinfo)


def test_rejection_records_no_approval():
    _, _, _, history = asyncio.run(run_workflow("potential", decision=False))

    assert _scheduled_inputs(history, "record_approval") == []


# --- Gap #14: a job already applied live --------------------------------


def test_already_applied_job_stops_before_the_llm():
    calls: list[str] = []
    result, statuses, applied, history = asyncio.run(
        run_workflow("strong", decision=None, applied_live=True, calls=calls)
    )

    assert result == "applied"
    assert calls == []  # no load_job, no match_job: no LLM money spent
    assert statuses == []  # jobs.status is never rewritten
    assert applied == []
    asyncio.run(replayer().replay_workflow(history))


def test_not_applied_job_runs_the_full_pipeline():
    calls: list[str] = []
    result, _, _, _ = asyncio.run(
        run_workflow("strong", decision=True, applied_live=False, calls=calls)
    )

    assert result == "applied_dry_run"
    assert calls == ["load_job", "fetch_job_details", "match_job"]


# record_approval_v1.json is a REAL history (job-38 on the local Temporal
# server, 2026-10-07): started before "record-approval-v1", approved after it,
# so it has the approval + apply markers but no "skip-if-applied-v1" marker.


def test_real_record_approval_history_replays():
    history = WorkflowHistory.from_json(
        "job-38", (HISTORIES / "record_approval_v1.json").read_text()
    )
    asyncio.run(replayer().replay_workflow(history))


# --- Decisions (rejected / expired) are logged ------------------------------


def _signal_time(history: WorkflowHistory) -> datetime:
    signal = next(e for e in history.events if e.HasField("workflow_execution_signaled_event_attributes"))
    return signal.event_time.ToDatetime()


def test_rejection_is_recorded_with_note_and_decision_time():
    _, _, _, history = asyncio.run(run_workflow("potential", decision=False))

    [(job_id, decision, decided_at, note)] = _scheduled_inputs(history, "record_decision")
    assert (job_id, decision, note) == (JOB_ID, "rejected", "test")
    decided = datetime.fromisoformat(decided_at)
    assert decided >= _signal_time(history).replace(tzinfo=decided.tzinfo)
    # The old status-only write is gone on the new path.
    assert [s for _, s in _scheduled_inputs(history, "update_job_status")] == PRE_APPROVAL


def test_expiry_is_recorded_at_the_timeout():
    _, _, _, history = asyncio.run(run_workflow("strong", decision=None))

    [(job_id, decision, decided_at, note)] = _scheduled_inputs(history, "record_decision")
    assert (job_id, decision, note) == (JOB_ID, "expired", "")
    started = history.events[0].event_time.ToDatetime(tzinfo=timezone.utc)
    # workflow.now() after the (time-skipped) 3-day timer, not the worker's clock.
    assert datetime.fromisoformat(decided_at) - started >= APPROVAL_TIMEOUT


def test_decision_histories_replay_on_new_path():
    for decision in (False, None):
        _, _, _, history = asyncio.run(run_workflow("potential", decision=decision))
        asyncio.run(replayer().replay_workflow(history))


# rejected_v1.json / expired_v1.json were recorded with the code from BEFORE
# "record-decision-v1" (they end with update_job_status(REJECTED/EXPIRED)).


def test_pre_decision_patch_histories_replay_on_old_path():
    for name in ("rejected_v1", "expired_v1"):
        history = WorkflowHistory.from_json(name, (HISTORIES / f"{name}.json").read_text())
        asyncio.run(replayer().replay_workflow(history))
        assert "record_decision" not in history.to_json()


# --- Detail page (patch "fetch-details-v1") -----------------------------------


def test_full_jd_reaches_semantic_score_and_the_llm():
    calls: list[str] = []
    seen: list[Job] = []
    result, _, _, history = asyncio.run(
        run_workflow("strong", decision=True, calls=calls, seen_jobs=seen)
    )

    assert result == "applied_dry_run"
    # After load_job (and the filter), before the LLM.
    assert calls == ["load_job", "fetch_job_details", "match_job"]
    assert [job.description for job in seen] == [DETAILED_JOB.description] * 2
    assert all(job.details is not None for job in seen)
    asyncio.run(replayer().replay_workflow(history))


def test_broken_detail_page_falls_back_to_the_snippet():
    seen: list[Job] = []
    result, statuses, _, _ = asyncio.run(
        run_workflow("strong", decision=True, details="fail", seen_jobs=seen)
    )

    # The job is not failed: it goes on with the card snippet.
    assert result == "applied_dry_run"
    assert "failed" not in statuses
    assert [job.description for job in seen] == [JOB.description] * 2


def test_details_run_on_the_browser_queue_with_a_deadline():
    _, _, _, history = asyncio.run(run_workflow("strong", decision=True))

    [scheduled] = [
        e.activity_task_scheduled_event_attributes for e in history.events
        if e.HasField("activity_task_scheduled_event_attributes")
        and e.activity_task_scheduled_event_attributes.activity_type.name == "fetch_job_details"
    ]
    # One-at-a-time queue, and a deadline so a down browser worker cannot
    # park the workflow forever (Temporal then fails the activity and we
    # fall back to the snippet, like test_broken_detail_page_...).
    assert scheduled.task_queue.name == BROWSER_TASK_QUEUE
    assert scheduled.schedule_to_close_timeout.ToTimedelta() == DETAILS_DEADLINE


def test_filtered_out_job_reads_no_detail_page():
    calls: list[str] = []

    async def run():
        # filter_job says no: swap in a filter that rejects.
        statuses: list[str] = []
        activities = make_activities("strong", statuses, [], [DRY_RUN_APPLIED], calls=calls)

        @activity.defn(name="filter_job")
        async def reject(job: Job) -> bool:
            return False

        activities = [reject if a.__name__ == "filter_job" else a for a in activities]
        async with await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        ) as env:
            async with Worker(
                env.client, task_queue=TASK_QUEUE,
                workflows=[JobApplicationWorkflow], activities=activities,
            ), Worker(
                env.client, task_queue=BROWSER_TASK_QUEUE,
                activities=make_browser_activities("ok", calls),
            ):
                return await env.client.execute_workflow(
                    JobApplicationWorkflow.run, JOB_ID,
                    id=f"job-{uuid.uuid4()}", task_queue=TASK_QUEUE,
                )

    assert asyncio.run(run()) == "filtered_out"
    assert "fetch_job_details" not in calls


# awaiting_approval_v1.json is a REAL history (job-37 on the local Temporal
# server, exported 2026-10-08 while it waited for approval): one of the 7
# workflows in flight when "fetch-details-v1" shipped. It already ran
# semantic_score and match_job without a detail fetch, so it must replay on
# the old path.


def test_real_in_flight_history_replays_without_details():
    history = WorkflowHistory.from_json(
        "job-37", (HISTORIES / "awaiting_approval_v1.json").read_text()
    )
    asyncio.run(replayer().replay_workflow(history))
    assert "fetch_job_details" not in history.to_json()

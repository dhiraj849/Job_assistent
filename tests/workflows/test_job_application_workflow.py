"""JobApplicationWorkflow tests with fake activities (no browser, DB, Qdrant or LLM).

Fakes are registered under the real activity names. The time-skipping test
server jumps over the 3-day approval timeout (and daily-cap waits) instantly.
"""

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path

from temporalio import activity
from temporalio.client import WorkflowHandle, WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from app.models.apply_result import ApplyOutcome, ApplyResult
from app.models.job import Job
from app.models.job_match import JobMatchResult
from app.models.job_match_item import JobMatchItem
from app.models.job_status import JobStatus
from app.workflows.job_application_workflow import JobApplicationWorkflow

TASK_QUEUE = "test-job-application"
JOB_ID = 42

JOB = Job(
    title="Python Backend Engineer",
    company="Acme",
    location="Noida",
    description="Django, FastAPI",
    url="https://example.com/42",
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
):
    """Fake activities; statuses/applied record what the workflow did.

    apply_job returns apply_results one by one (last one repeats).
    applied_live is what the applications table says; calls logs
    load_job / match_job (the LLM) runs.
    """
    calls = calls if calls is not None else []

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
        return 0.82

    @activity.defn(name="match_job")
    async def match_job(job: Job) -> JobMatchItem:
        calls.append("match_job")
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

    @activity.defn(name="apply_job")
    async def apply_job(job_id: int) -> ApplyResult:
        applied.append(job_id)
        return apply_results[min(len(applied), len(apply_results)) - 1]

    return [is_applied_live, load_job, filter_job, semantic_score, match_job,
            save_match, update_job_status, record_approval, apply_job]


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
):
    """Run one workflow. decision=None means nobody answers (timeout).

    Returns (result, statuses, applied, history).
    """
    statuses: list[str] = []
    applied: list[int] = []
    activities = make_activities(
        match_level, statuses, applied, apply_results, applied_live, calls
    )

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[JobApplicationWorkflow],
            activities=activities,
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

    # The new path leaves patch markers (skip-if-applied + approval + apply)
    # and never schedules the old activities.
    markers = [e for e in history.events if e.HasField("marker_recorded_event_attributes")]
    assert [m.marker_recorded_event_attributes.marker_name for m in markers] == ["core_patch"] * 3
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
    assert calls == ["load_job", "match_job"]


# record_approval_v1.json is a REAL history (job-38 on the local Temporal
# server, 2026-10-07): started before "record-approval-v1", approved after it,
# so it has the approval + apply markers but no "skip-if-applied-v1" marker.


def test_real_record_approval_history_replays():
    history = WorkflowHistory.from_json(
        "job-38", (HISTORIES / "record_approval_v1.json").read_text()
    )
    asyncio.run(replayer().replay_workflow(history))

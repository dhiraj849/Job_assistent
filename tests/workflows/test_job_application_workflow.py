"""JobApplicationWorkflow tests with fake activities (no browser, DB, Qdrant or LLM).

Fakes are registered under the real activity names. The time-skipping test
server jumps over the 3-day approval timeout (and daily-cap waits) instantly.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
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
    CAP_EXPIRED_REASON,
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

    # expire_approval also sets jobs.status=expired.
    @activity.defn(name="expire_approval")
    async def expire_approval(job_id: int, reason: str) -> None:
        statuses.append(JobStatus.EXPIRED.value)

    return [is_applied_live, load_job, filter_job, semantic_score, match_job,
            save_match, update_job_status, record_approval, record_decision, apply_job,
            expire_approval]


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


# --- Versioning (workflow.patched / deprecate_patch) ---------------------
# "apply-job-v1" and "record-approval-v1" are fully removed (step 2 of 2).
# Histories whose marker for them came from patched() (deprecated=false), or
# that predate them, were moved to histories/retired/ and must now FAIL to
# replay (proves the removal is real).


def replayer() -> Replayer:
    return Replayer(workflows=[JobApplicationWorkflow], data_converter=pydantic_data_converter)


def test_retired_histories_no_longer_replay():
    for path in sorted((HISTORIES / "retired").glob("*.json")):
        history = WorkflowHistory.from_json(path.stem, path.read_text())
        with pytest.raises(Exception, match="[Nn]ondetermin"):
            asyncio.run(replayer().replay_workflow(history))


def test_patched_history_replays_on_new_path():
    _, _, _, history = asyncio.run(run_workflow("strong", decision=True))

    # The new path leaves patch markers (skip-if-applied + details only; the
    # approval and apply patches are gone) and never schedules old activities.
    markers = [e for e in history.events if e.HasField("marker_recorded_event_attributes")]
    assert [m.marker_recorded_event_attributes.marker_name for m in markers] == ["core_patch"] * 2
    assert set(_marker_flags(history)) == {"skip-if-applied-v1", "fetch-details-v1"}
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


def _marker_flags(history: WorkflowHistory) -> dict[str, bool]:
    """Patch id -> its "deprecated" flag, for every patch marker in history."""
    flags = {}
    for event in history.events:
        if event.HasField("marker_recorded_event_attributes"):
            for payloads in event.marker_recorded_event_attributes.details.values():
                for payload in payloads.payloads:
                    data = json.loads(payload.data)
                    flags[data["id"]] = data["deprecated"]
    return flags


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


# deprecated_markers_v1.json was recorded on step-1 code: deprecate_patch
# wrote "apply-job-v1" / "record-approval-v1" markers flagged deprecated=true.
# Core skips such markers when no code asks for them, so a workflow that ran
# on step-1 code replays fine now that the calls are gone.


def test_deprecated_marker_history_replays_without_the_calls():
    history = WorkflowHistory.from_json(
        "deprecated_markers_v1", (HISTORIES / "deprecated_markers_v1.json").read_text()
    )
    assert _marker_flags(history)["apply-job-v1"] is True
    assert _marker_flags(history)["record-approval-v1"] is True
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


# --- Cap expiry (patch "cap-expiry-outcome-v1", known issue #15) -------------


def test_cap_expiry_expires_the_application():
    _, _, _, history = asyncio.run(
        run_workflow("strong", decision=True, apply_results=[CAP_FULL])
    )

    # applications + jobs.status in one activity, with a reason for apply_one.
    assert _scheduled_inputs(history, "expire_approval") == [[JOB_ID, CAP_EXPIRED_REASON]]
    # The old status-only write is gone on the new path.
    assert [s for _, s in _scheduled_inputs(history, "update_job_status")] == PRE_APPROVAL
    asyncio.run(replayer().replay_workflow(history))


# cap_expired_v2.json was recorded on step-1 code (new path: expire_approval).
# The pre-patch cap_expired_v1.json is retired: it also carried non-deprecated
# "apply-job-v1" markers, so no saved history covers the old
# update_job_status(EXPIRED) path any more.


def test_cap_expired_history_replays():
    history = WorkflowHistory.from_json(
        "cap_expired_v2", (HISTORIES / "cap_expired_v2.json").read_text()
    )
    asyncio.run(replayer().replay_workflow(history))
    assert _scheduled_inputs(history, "expire_approval") == [[JOB_ID, CAP_EXPIRED_REASON]]


def test_every_saved_history_replays():
    # Safety net: a new patch must not break ANY history kept in histories/,
    # including ones added later without their own test.
    files = sorted(HISTORIES.glob("*.json"))
    assert len(files) >= 6
    for path in files:
        history = WorkflowHistory.from_json(path.stem, path.read_text())
        asyncio.run(replayer().replay_workflow(history))


# --- Company site: ready_for_you ---------------------------------------------------
# apply_job may now return READY_FOR_YOU. The workflow only mirrors it in its
# query state (no new command), so no patch; ready_for_you_v2.json was
# recorded on step-1 code and must keep replaying.


def test_company_site_ready_ends_the_workflow():
    ready = ApplyResult(outcome=ApplyOutcome.READY_FOR_YOU, dry_run=False, reason="form ready")
    result, statuses, applied, history = asyncio.run(
        run_workflow("strong", decision=True, apply_results=[ready])
    )

    assert result == "ready_for_you"
    assert statuses == PRE_APPROVAL + ["approved"]
    assert applied == [JOB_ID]
    asyncio.run(replayer().replay_workflow(history))


def test_ready_for_you_history_replays():
    history = WorkflowHistory.from_json(
        "ready_for_you_v2", (HISTORIES / "ready_for_you_v2.json").read_text()
    )
    asyncio.run(replayer().replay_workflow(history))
    completed = history.events[-1].workflow_execution_completed_event_attributes
    assert completed.result.payloads[0].data == b'"ready_for_you"'

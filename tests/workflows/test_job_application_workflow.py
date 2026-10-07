"""JobApplicationWorkflow tests with fake activities (no browser, DB, Qdrant or LLM).

Fakes are registered under the real activity names. The time-skipping test
server jumps over the 3-day approval timeout (and daily-cap waits) instantly.
"""

import asyncio
import uuid
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
):
    """Fake activities; statuses/applied record what the workflow did.

    apply_job returns apply_results one by one (last one repeats).
    """

    @activity.defn(name="load_job")
    async def load_job(job_id: int) -> Job:
        return JOB

    @activity.defn(name="filter_job")
    async def filter_job(job: Job) -> bool:
        return True

    @activity.defn(name="semantic_score")
    async def semantic_score(job_id: int, job: Job) -> float | None:
        return 0.82

    @activity.defn(name="match_job")
    async def match_job(job: Job) -> JobMatchItem:
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

    @activity.defn(name="apply_job")
    async def apply_job(job_id: int) -> ApplyResult:
        applied.append(job_id)
        return apply_results[min(len(applied), len(apply_results)) - 1]

    return [load_job, filter_job, semantic_score, match_job, save_match,
            update_job_status, apply_job]


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
):
    """Run one workflow. decision=None means nobody answers (timeout).

    Returns (result, statuses, applied, history).
    """
    statuses: list[str] = []
    applied: list[int] = []

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[JobApplicationWorkflow],
            activities=make_activities(match_level, statuses, applied, apply_results),
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

    # The new path leaves a patch marker and never schedules the old activity.
    markers = [e for e in history.events if e.HasField("marker_recorded_event_attributes")]
    assert [m.marker_recorded_event_attributes.marker_name for m in markers] == ["core_patch"]
    assert "apply_job_dry_run" not in history.to_json()

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

"""JobApplicationWorkflow tests with fake activities (no browser, DB, Qdrant or LLM).

Fakes are registered under the real activity names. The time-skipping test
server jumps over the 3-day approval timeout instantly.
"""

import asyncio
import uuid

from temporalio import activity
from temporalio.client import WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

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


def make_activities(match_level: str, statuses: list[str], applied: list[int]):
    """Fake activities; statuses/applied record what the workflow did."""

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

    @activity.defn(name="apply_job_dry_run")
    async def apply_job_dry_run(job_id: int) -> str:
        applied.append(job_id)
        return "dry-run"

    return [load_job, filter_job, semantic_score, match_job, save_match,
            update_job_status, apply_job_dry_run]


async def wait_for_status(handle: WorkflowHandle, expected: str) -> None:
    for _ in range(100):
        if await handle.query(JobApplicationWorkflow.current_status) == expected:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"workflow never reached {expected}")


async def run_workflow(match_level: str, decision: bool | None):
    """Run one workflow. decision=None means nobody answers (timeout)."""
    statuses: list[str] = []
    applied: list[int] = []

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[JobApplicationWorkflow],
            activities=make_activities(match_level, statuses, applied),
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

    return result, statuses, applied


PRE_APPROVAL = ["shortlisted", "matched", "awaiting_approval"]


def test_approved_job_is_applied_in_dry_run():
    result, statuses, applied = asyncio.run(run_workflow("strong", decision=True))

    assert result == "applied_dry_run"
    assert statuses == PRE_APPROVAL + ["approved", "applied_dry_run"]
    assert applied == [JOB_ID]


def test_rejected_job_is_not_applied():
    result, statuses, applied = asyncio.run(run_workflow("potential", decision=False))

    assert result == "rejected"
    assert statuses == PRE_APPROVAL + ["rejected"]
    assert applied == []


def test_no_decision_in_3_days_expires():
    result, statuses, applied = asyncio.run(run_workflow("strong", decision=None))

    assert result == "expired"
    assert statuses == PRE_APPROVAL + ["expired"]
    assert applied == []


def test_weak_match_is_filtered_out_without_approval():
    result, statuses, applied = asyncio.run(run_workflow("weak", decision=None))

    assert result == "filtered_out"
    assert statuses == ["shortlisted", "matched", "filtered_out"]
    assert applied == []

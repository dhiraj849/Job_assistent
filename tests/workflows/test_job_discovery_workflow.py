"""JobDiscoveryWorkflow tests with fake activities (no browser, no DB).

The fakes are registered under the real activity names, so the workflow
calls them exactly as it would call the real ones. A stub child workflow
stands in for JobApplicationWorkflow. The time-skipping test server makes
retry back-off instant.
"""

import asyncio
import uuid

from temporalio import activity, workflow
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.models.job import Job
from app.workflows.job_discovery_workflow import JobDiscoveryWorkflow

TASK_QUEUE = "test-job-agent"

FAKE_JOBS = [
    Job(title="Backend Engineer", company="A", location="Noida",
        description="Python", url="https://example.com/1"),
    Job(title="Python Developer", company="B", location="Noida",
        description="FastAPI", url="https://example.com/2"),
]


@workflow.defn(name="JobApplicationWorkflow")
class StubApplicationWorkflow:
    """Same name as the real child, but finishes immediately."""

    @workflow.run
    async def run(self, job_id: int) -> str:
        return f"stub-{job_id}"


async def run_workflow(activities, child_ids: list[int] = ()) -> tuple[dict, list[str]]:
    """Run discovery; also return the results of the expected child workflows."""
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[JobDiscoveryWorkflow, StubApplicationWorkflow],
            activities=activities,
        ):
            result = await env.client.execute_workflow(
                JobDiscoveryWorkflow.run,
                args=["Python", "Noida"],
                id=f"test-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )
            children = [
                await env.client.get_workflow_handle(f"job-{job_id}").result()
                for job_id in child_ids
            ]
    return result, children


def test_returns_counts_and_starts_one_child_per_new_job():

    @activity.defn(name="discover_jobs")
    async def fake_discover(keyword: str, location: str) -> list[Job]:
        return FAKE_JOBS

    @activity.defn(name="save_jobs")
    async def fake_save(jobs: list[Job]) -> list[int]:
        return [11]

    result, children = asyncio.run(run_workflow([fake_discover, fake_save], [11]))

    assert result == {"found": 2, "new": 1}
    assert children == ["stub-11"]


def test_no_jobs_skips_save():
    save_calls = []

    @activity.defn(name="discover_jobs")
    async def fake_discover(keyword: str, location: str) -> list[Job]:
        return []

    @activity.defn(name="save_jobs")
    async def fake_save(jobs: list[Job]) -> list[int]:
        save_calls.append(jobs)
        return []

    result, _ = asyncio.run(run_workflow([fake_discover, fake_save]))

    assert result == {"found": 0, "new": 0}
    assert save_calls == []


def test_failed_activity_is_retried():
    attempts = []

    @activity.defn(name="discover_jobs")
    async def flaky_discover(keyword: str, location: str) -> list[Job]:
        attempts.append(activity.info().attempt)
        if len(attempts) == 1:
            raise RuntimeError("page did not load")
        return FAKE_JOBS

    @activity.defn(name="save_jobs")
    async def fake_save(jobs: list[Job]) -> list[int]:
        return [11, 12]

    result, children = asyncio.run(run_workflow([flaky_discover, fake_save], [11, 12]))

    assert result == {"found": 2, "new": 2}
    assert children == ["stub-11", "stub-12"]
    assert attempts == [1, 2]

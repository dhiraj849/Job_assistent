"""BackfillDetailsWorkflow with fake activities (no browser, DB or Qdrant)."""

import asyncio
import uuid
from pathlib import Path

from temporalio import activity
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from app.models.job import Job
from app.workflows.backfill_details_workflow import BackfillDetailsWorkflow
from app.workflows.task_queues import BROWSER_TASK_QUEUE

TASK_QUEUE = "test-job-agent"
HISTORY = Path(__file__).parent / "histories" / "backfill_details_v1.json"
GONE = 2  # this job's page cannot be parsed (e.g. expired posting)


async def run_backfill(job_ids: list[int]):
    calls = []

    @activity.defn(name="fetch_job_details")
    async def fetch_job_details(job_id: int) -> Job:
        calls.append(("fetch", job_id))
        if job_id == GONE:
            raise ApplicationError("no JobPosting", type="DetailParseError", non_retryable=True)
        return Job(title="T", company="C", location="L", description="full JD")

    @activity.defn(name="embed_job")
    async def embed_job(job_id: int) -> None:
        calls.append(("embed", job_id))

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as env:
        async with Worker(
            env.client, task_queue=TASK_QUEUE, workflows=[BackfillDetailsWorkflow], activities=[embed_job]
        ), Worker(env.client, task_queue=BROWSER_TASK_QUEUE, activities=[fetch_job_details]):
            handle = await env.client.start_workflow(
                BackfillDetailsWorkflow.run, job_ids, id=f"test-{uuid.uuid4()}", task_queue=TASK_QUEUE
            )
            result = await handle.result()
            history = await handle.fetch_history()
    return result, calls, history


def test_fetches_and_embeds_one_job_at_a_time():
    result, calls, _ = asyncio.run(run_backfill([1, 3]))

    assert result == {"fetched": [1, 3], "failed": []}
    assert calls == [("fetch", 1), ("embed", 1), ("fetch", 3), ("embed", 3)]


def test_failed_fetch_is_reported_not_embedded_and_the_rest_continues():
    result, calls, _ = asyncio.run(run_backfill([1, GONE, 3]))

    assert result == {"fetched": [1, 3], "failed": [GONE]}
    assert ("embed", GONE) not in calls
    assert calls[-2:] == [("fetch", 3), ("embed", 3)]


def test_never_runs_matching_or_approval():
    _, _, history = asyncio.run(run_backfill([1]))

    for name in ("filter_job", "semantic_score", "match_job", "update_job_status", "record_approval"):
        assert name not in history.to_json()


def test_saved_history_replays():
    history = WorkflowHistory.from_json("backfill_details_v1", HISTORY.read_text())
    replayer = Replayer(workflows=[BackfillDetailsWorkflow], data_converter=pydantic_data_converter)

    asyncio.run(replayer.replay_workflow(history))

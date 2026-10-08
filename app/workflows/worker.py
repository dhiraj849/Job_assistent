"""Temporal worker: polls the task queue and runs workflows + activities.

Run with: uv run python -m app.workflows.worker
"""

import asyncio

import structlog
from temporalio.worker import Worker

from app.config import settings
from app.logging_config import setup_logging
from app.workflows import activities
from app.workflows.client import connect_client
from app.workflows.job_application_workflow import JobApplicationWorkflow
from app.workflows.job_discovery_workflow import JobDiscoveryWorkflow
from app.workflows.task_queues import BROWSER_TASK_QUEUE

# Fixed name, not __name__: under `python -m` that is "__main__", which is
# outside the "app" logger tree and its INFO lines get dropped.
logger = structlog.get_logger("app.workflows.worker")


async def main() -> None:
    setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)

    client = await connect_client()

    worker = Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[JobDiscoveryWorkflow, JobApplicationWorkflow],
        activities=[
            activities.discover_jobs,
            activities.save_jobs,
            activities.load_job,
            activities.filter_job,
            activities.semantic_score,
            activities.match_job,
            activities.save_match,
            activities.update_job_status,
            activities.is_applied_live,
            activities.record_approval,
            activities.record_decision,
            activities.apply_job,
            activities.apply_job_dry_run,  # old histories (pre "apply-job-v1")
        ],
        # Many application workflows can start at once; cap parallel
        # activities so we never run a flood of LLM calls or browsers.
        max_concurrent_activities=3,
    )

    # Detail-page reads: one browser page at a time (see task_queues.py).
    browser_worker = Worker(
        client,
        task_queue=BROWSER_TASK_QUEUE,
        activities=[activities.fetch_job_details],
        max_concurrent_activities=1,
    )

    logger.info(
        "worker_started",
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        browser_task_queue=BROWSER_TASK_QUEUE,
        namespace=settings.TEMPORAL_NAMESPACE,
        # Log the safety rails so "is this worker live?" is answered by the
        # log, not by reading .env.
        apply_mode=settings.APPLY_MODE,
        max_applies_per_day=settings.MAX_APPLIES_PER_DAY,
        detail_page_delay_seconds=settings.DETAIL_PAGE_DELAY_SECONDS,
    )
    # Both workers share the process; if one stops, gather stops the other.
    await asyncio.gather(worker.run(), browser_worker.run())


if __name__ == "__main__":
    asyncio.run(main())

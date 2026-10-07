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

logger = structlog.get_logger(__name__)


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
            activities.record_approval,
            activities.apply_job,
            activities.apply_job_dry_run,  # old histories (pre "apply-job-v1")
        ],
        # Many application workflows can start at once; cap parallel
        # activities so we never run a flood of LLM calls or browsers.
        max_concurrent_activities=3,
    )

    logger.info(
        "worker_started",
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        namespace=settings.TEMPORAL_NAMESPACE,
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

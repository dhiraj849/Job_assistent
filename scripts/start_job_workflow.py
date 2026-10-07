"""Start the application workflow for one existing job (e.g. jobs saved before
workflows existed). Returns immediately; the workflow may wait days for approval.

Usage: uv run python -m scripts.start_job_workflow <job_id>
"""

import argparse
import asyncio

from temporalio.exceptions import WorkflowAlreadyStartedError

from app.config import settings
from app.workflows.client import connect_client
from app.workflows.job_application_workflow import JobApplicationWorkflow


async def main(job_id: int) -> None:
    client = await connect_client()
    workflow_id = f"job-{job_id}"

    try:
        await client.start_workflow(
            JobApplicationWorkflow.run,
            job_id,
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )
    except WorkflowAlreadyStartedError:
        print(f"Workflow {workflow_id} is already running.")
        return

    print(f"Started {workflow_id}. Watch it at http://localhost:8080")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=int)
    args = parser.parse_args()

    asyncio.run(main(args.job_id))

"""Start a JobDiscoveryWorkflow and print its result.

Needs a running worker: uv run python -m app.workflows.worker
Usage: uv run python -m scripts.start_discovery --keyword "Python" --location "Noida"
"""

import argparse
import asyncio
import re

from temporalio.exceptions import WorkflowAlreadyStartedError

from app.config import settings
from app.workflows.client import connect_client
from app.workflows.job_discovery_workflow import JobDiscoveryWorkflow


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


async def main(keyword: str, location: str) -> None:
    client = await connect_client()

    # Stable ID per search: Temporal refuses a second run with the same
    # ID while one is still running, so we never scrape the same search twice at once.
    workflow_id = f"discovery-{slugify(keyword)}-{slugify(location)}"

    try:
        result = await client.execute_workflow(
            JobDiscoveryWorkflow.run,
            args=[keyword, location],
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )
    except WorkflowAlreadyStartedError:
        print(f"Workflow {workflow_id} is already running. Check the UI at http://localhost:8080")
        return

    print(f"Workflow {workflow_id} finished: {result}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", default=settings.JOB_SEARCH_KEYWORD)
    parser.add_argument("--location", default=settings.JOB_SEARCH_LOCATION)
    args = parser.parse_args()

    asyncio.run(main(args.keyword, args.location))

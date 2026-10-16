"""Start a JobDiscoveryWorkflow and print its result.

Needs a running worker: uv run python -m app.workflows.worker
Usage: uv run python -m scripts.start_discovery [--keyword "Python"] [--location "Noida"]
Without flags it uses search.keyword / search.location from the profile.
"""

import argparse
import asyncio

from temporalio.exceptions import WorkflowAlreadyStartedError

from app.config import settings
from app.services.profile_loader import load_profile
from app.workflows.client import connect_client
from app.workflows.ids import discovery_workflow_id
from app.workflows.job_discovery_workflow import JobDiscoveryWorkflow


async def main(keyword: str, location: str) -> None:
    client = await connect_client()

    # Same ID as the scheduled runs' prefix: never two scrapes of one search at once.
    workflow_id = discovery_workflow_id(keyword, location)

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
    parser.add_argument("--keyword", help="default: profile search.keyword")
    parser.add_argument("--location", help="default: profile search.location")
    args = parser.parse_args()

    search = load_profile(settings.PROFILE_PATH).search
    asyncio.run(main(args.keyword or search.keyword, args.location or search.location))

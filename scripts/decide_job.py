"""Approve or reject a job waiting in its application workflow.

Usage: uv run python -m scripts.decide_job <job_id> yes|no [note]
"""

import argparse
import asyncio

from temporalio.service import RPCError

from app.workflows.client import connect_client
from app.workflows.job_application_workflow import JobApplicationWorkflow


async def main(job_id: int, approved: bool, note: str) -> None:
    client = await connect_client()
    handle = client.get_workflow_handle(f"job-{job_id}")

    try:
        status = await handle.query(JobApplicationWorkflow.current_status)
    except RPCError as error:
        print(f"No running workflow for job {job_id}: {error.message}")
        return

    # The workflow ignores decisions outside awaiting_approval; warn early.
    if status != "awaiting_approval":
        print(f"Job {job_id} is '{status}', not awaiting approval. Nothing sent.")
        return

    await handle.signal(JobApplicationWorkflow.decide, args=[approved, note])
    print(f"Sent {'APPROVE' if approved else 'REJECT'} to job-{job_id}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=int)
    parser.add_argument("decision", choices=["yes", "no"])
    parser.add_argument("note", nargs="?", default="")
    args = parser.parse_args()

    asyncio.run(main(args.job_id, args.decision == "yes", args.note))

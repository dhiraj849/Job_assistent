"""Fetch the detail page (full JD) of jobs saved before detail fetching, and
re-embed them in Qdrant. No LLM match, no approvals, statuses unchanged.

Needs a running worker: uv run python -m app.workflows.worker
Usage:
  uv run python -m scripts.backfill_details --dry-run          # list only
  uv run python -m scripts.backfill_details --limit 10         # start the workflow

Safe to re-run: only jobs whose details are still NULL are picked, a fetched
job costs no request, and the vector write overwrites. Failed jobs (e.g. an
expired posting) stay NULL and are tried again next time.
"""

import argparse
import asyncio

from temporalio.exceptions import WorkflowAlreadyStartedError

from app.config import settings
from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository
from app.workflows.backfill_details_workflow import BackfillDetailsWorkflow
from app.workflows.client import connect_client

# Stable ID: Temporal refuses a second backfill while one is still running.
WORKFLOW_ID = "backfill-details"


async def load_candidates(limit: int) -> list[tuple[int, str, str]]:
    try:
        async with SessionLocal() as session:
            return await JobRepository(session).get_jobs_without_details(limit)
    finally:
        await engine.dispose()


async def main(limit: int, dry_run: bool) -> None:
    jobs = await load_candidates(limit)
    if not jobs:
        print("Nothing to backfill: every job has its details.")
        return

    for job_id, status, title in jobs:
        print(f"job {job_id:>5}  {status:<16} {title}")

    if dry_run:
        print(f"\nDry run: {len(jobs)} job(s) would be fetched and re-embedded. Nothing changed.")
        return

    client = await connect_client()
    try:
        result = await client.execute_workflow(
            BackfillDetailsWorkflow.run,
            [job_id for job_id, _, _ in jobs],
            id=WORKFLOW_ID,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )
    except WorkflowAlreadyStartedError:
        print(f"Workflow {WORKFLOW_ID} is already running. Check the UI at http://localhost:8080")
        return

    print(f"\nFetched + re-embedded: {result['fetched']}")
    print(f"Failed (still no details): {result['failed']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=10, help="max jobs per run (default 10)")
    parser.add_argument("--dry-run", action="store_true", help="only list the jobs; change nothing")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    asyncio.run(main(args.limit, args.dry_run))

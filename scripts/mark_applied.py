"""Record an apply I did by hand (on Naukri, a company site, inspect --click).

Writes applications (outcome=applied) and jobs.status=applied in one
transaction, after a y/N confirmation, so I never need raw SQL for this.
If the job's workflow is still waiting, a later approval then ends as
already_applied instead of applying twice.

Usage: uv run python -m scripts.mark_applied <job_id> --reason "applied on company site"
"""

import argparse
import asyncio
import sys

from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository


async def main(job_id: int, reason: str) -> int:
    try:
        async with SessionLocal() as session:
            repo = JobRepository(session)
            job = await repo.get_job(job_id)
            status = await repo.get_status(job_id)
            application = await repo.get_application(job_id)

        if job is None:
            print(f"Job {job_id} not found.")
            return 1

        print(f"Job {job_id}: {job.title} @ {job.company}")
        print(f"Status:      {status}")
        if application is None:
            print("Application: none (doing it myself counts as the approval)")
        else:
            print(f"Application: {application.outcome.value} {application.reason}".rstrip())
            if application.applied_live:
                print("Already recorded as applied. Nothing to do.")
                return 0

        answer = input(f"Mark job {job_id} as APPLIED (reason: {reason!r})? [y/N] ").strip().lower()
        if answer != "y":
            print("Cancelled. Nothing was changed.")
            return 0

        async with SessionLocal() as session:
            written = await JobRepository(session).record_manual_apply(job_id, reason)

        # False only if something marked it applied between the look and the write.
        print("Recorded." if written else "Already recorded as applied. Nothing changed.")
        print(f"If workflow job-{job_id} is still running, you can terminate it in the Temporal UI.")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job_id", type=int)
    parser.add_argument("--reason", required=True, help="how it was applied, e.g. 'company site'")
    args = parser.parse_args()

    if not args.reason.strip():
        parser.error("--reason must not be empty")
    sys.exit(asyncio.run(main(args.job_id, args.reason.strip())))

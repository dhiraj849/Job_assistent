"""Apply LIVE to one job, by hand, with a y/N confirmation. For first runs.

Runs the same ApplyService as the workflow (lock, idempotency, daily cap,
answers.yaml), but always in live mode and without Temporal. Only jobs I
already approved can be applied to. A headed browser opens; artifacts go to
artifacts/apply/<job_id>/.

First live run, capped at one apply today:
    MAX_APPLIES_PER_DAY=1 uv run python -m scripts.apply_one <job_id>
"""

import argparse
import asyncio
import sys
from datetime import datetime

from app.browser.job_applier import NaukriJobApplier
from app.config import settings
from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository
from app.logging_config import setup_logging
from app.models.job_status import JobStatus
from app.services.apply_service import CAP_TIMEZONE, ApplyService, start_of_day

# Statuses a job can only reach after my approval. FAILED / NEEDS_MANUAL are
# allowed so a job can be retried after a fix (e.g. a fresh login).
APPLYABLE = {JobStatus.APPROVED, JobStatus.FAILED, JobStatus.NEEDS_MANUAL}


async def main(job_id: int) -> int:
    setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
    try:
        # Read-only look first, in its own session: no transaction (and no
        # apply lock) stays open while waiting for my answer.
        async with SessionLocal() as session:
            repo = JobRepository(session)
            job = await repo.get_job(job_id)
            status = await repo.get_status(job_id)
            used = await repo.count_status_since(
                JobStatus.APPLIED, start_of_day(datetime.now(CAP_TIMEZONE))
            )

        if job is None:
            print(f"Job {job_id} not found.")
            return 1

        print(f"Job {job_id}: {job.title} @ {job.company}")
        print(f"URL:     {job.url}")
        print(f"Status:  {status}")
        print(f"Applied today: {used}/{settings.MAX_APPLIES_PER_DAY}")

        if status not in APPLYABLE:
            print(f"Refusing: status must be one of {sorted(APPLYABLE)} (approve it first).")
            return 1
        if status == JobStatus.FAILED:
            print("Note: a previous attempt FAILED. Check artifacts/apply/ first.")

        answer = input("Apply LIVE to this job on Naukri? [y/N] ").strip().lower()
        if answer != "y":
            print("Cancelled. Nothing was done.")
            return 0

        async with SessionLocal() as session:
            service = ApplyService(
                repository=JobRepository(session),
                mode="live",
                max_per_day=settings.MAX_APPLIES_PER_DAY,
                answers_path=settings.ANSWERS_PATH,
                applier_factory=NaukriJobApplier,
            )
            result = await service.apply(job_id)

        print(f"Outcome: {result.outcome.value}")
        if result.reason:
            print(f"Reason:  {result.reason}")
        print(f"Artifacts: artifacts/apply/{job_id}/")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job_id", type=int)
    args = parser.parse_args()

    sys.exit(asyncio.run(main(args.job_id)))

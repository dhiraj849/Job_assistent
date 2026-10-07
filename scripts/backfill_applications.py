"""One-time: create applications rows for jobs applied before the table existed.

Not an Alembic migration on purpose: these facts are true only for my local
database, and a migration must behave the same on an empty one (CI).
Idempotent (jobs that already have a row are skipped) and asks y/N first.

Usage: uv run python -m scripts.backfill_applications
"""

import asyncio
import sys
from datetime import datetime, timezone

from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository
from app.models.application import ApplicationOutcome

UTC = timezone.utc

# What really happened, from the sources noted per job (all 2026-10-07, UTC).
KNOWN_APPLIES = {
    # Clicked Apply in scripts/inspect_apply_flow.py --click; the click was
    # the approval. Time: artifacts/inspect/23/02_after_click.html.
    23: dict(
        approved_at=datetime(2026, 10, 7, 9, 32, 53, tzinfo=UTC),
        applied_at=datetime(2026, 10, 7, 9, 32, 53, tzinfo=UTC),
        reason="applied manually via inspect --click",
        approval_note="manual apply (inspect --click)",
        artifacts_dir="artifacts/inspect/23",
    ),
    # Workflow terminated with "approved by user; apply_one" (Temporal
    # history), then scripts/apply_one.py; Naukri confirmed at 02_success.html.
    25: dict(
        approved_at=datetime(2026, 10, 7, 9, 46, 26, tzinfo=UTC),
        applied_at=datetime(2026, 10, 7, 9, 48, 20, tzinfo=UTC),
        reason="live apply via scripts/apply_one.py, confirmed by Naukri",
        approval_note="approved by user; apply_one",
        artifacts_dir="artifacts/apply/25/20261007-151808",
    ),
}


def build_backfill_rows(
    applied_jobs: list[tuple[int, datetime]],
    known: dict[int, dict] = KNOWN_APPLIES,
) -> dict[int, dict]:
    """{job_id: row values} for applied jobs that have no applications row.

    Unknown jobs fall back to status_updated_at: the best time we have.
    """
    rows = {}
    for job_id, status_updated_at in applied_jobs:
        base = dict(
            approved_at=status_updated_at,
            applied_at=status_updated_at,
            reason="backfilled from jobs.status",
            approval_note="",
            artifacts_dir=None,
        )
        rows[job_id] = {
            **base,
            **known.get(job_id, {}),
            "outcome": ApplicationOutcome.APPLIED.value,
            "dry_run": False,
        }
    return rows


async def main() -> int:
    try:
        async with SessionLocal() as session:
            applied_jobs = await JobRepository(session).get_applied_jobs_without_application()

        rows = build_backfill_rows(applied_jobs)
        if not rows:
            print("Nothing to backfill: every applied job has an applications row.")
            return 0

        for job_id, row in rows.items():
            print(f"job {job_id}: applied_at={row['applied_at']:%Y-%m-%d %H:%M:%S%z}  {row['reason']}")
        if input(f"Insert {len(rows)} applications row(s)? [y/N] ").strip().lower() != "y":
            print("Cancelled. Nothing was changed.")
            return 0

        async with SessionLocal() as session:
            repo = JobRepository(session)
            for job_id, row in rows.items():
                written = await repo.insert_application_if_missing(job_id, **row)
                print(f"job {job_id}: {'inserted' if written else 'already had a row'}")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

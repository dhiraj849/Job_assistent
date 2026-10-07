"""List everything waiting on me: approvals, and jobs that need a human.

Usage: uv run python -m scripts.list_pending
Then decide: uv run python -m scripts.decide_job <job_id> yes|no [note]
Fixed one by hand? uv run python -m scripts.mark_applied <job_id> --reason "..."
"""

import asyncio

from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository


async def main() -> None:
    async with SessionLocal() as session:
        repo = JobRepository(session)
        pending = await repo.get_pending_approvals()
        attention = await repo.get_jobs_needing_attention()
    await engine.dispose()

    print("== Awaiting approval")
    if not pending:
        print("No jobs awaiting approval.")
    else:
        print(f"{'ID':>6}  {'SCORE':>5}  {'LEVEL':<9}  TITLE @ COMPANY")
        for job_id, title, company, score, level in pending:
            print(f"{job_id:>6}  {score:>5}  {level:<9}  {title} @ {company}")

    print("\n== Needs attention (needs_manual / failed)")
    if not attention:
        print("Nothing needs attention.")
        return
    for job_id, title, company, status, reason, artifacts_dir in attention:
        print(f"{job_id:>6}  {status:<12}  {title} @ {company}")
        # No reason: the workflow failed before apply (no applications row).
        print(f"{'':>8}reason: {reason or '(none recorded, see Temporal UI)'}")
        if artifacts_dir:
            print(f"{'':>8}artifacts: {artifacts_dir}")


if __name__ == "__main__":
    asyncio.run(main())

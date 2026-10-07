"""List jobs waiting for your approval.

Usage: uv run python -m scripts.list_pending
Then decide: uv run python -m scripts.decide_job <job_id> yes|no [note]
"""

import asyncio

from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository


async def main() -> None:
    async with SessionLocal() as session:
        pending = await JobRepository(session).get_pending_approvals()
    await engine.dispose()

    if not pending:
        print("No jobs awaiting approval.")
        return

    print(f"{'ID':>6}  {'SCORE':>5}  {'LEVEL':<9}  TITLE @ COMPANY")
    for job_id, title, company, score, level in pending:
        print(f"{job_id:>6}  {score:>5}  {level:<9}  {title} @ {company}")


if __name__ == "__main__":
    asyncio.run(main())

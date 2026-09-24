"""Show how many jobs are still waiting to be matched, and how many matches are saved.

Run: uv run python -m scripts.check_unmatched
"""

import asyncio

from sqlalchemy import text

from app.db.database import SessionLocal, engine
from app.db.job_repository import JobRepository


async def main() -> None:
    try:
        async with SessionLocal() as session:
            repository = JobRepository(session)
            unmatched = await repository.get_unmatched_jobs_with_ids()

            print(f"Unmatched jobs: {len(unmatched)}")
            for job_id, job in unmatched[:5]:
                print(f"  [{job_id}] {job.title}")

            result = await session.execute(text("SELECT COUNT(*) FROM job_matches"))
            print(f"Saved matches: {result.scalar_one()}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

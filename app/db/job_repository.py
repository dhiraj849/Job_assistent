import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobRecord
from app.models.job import Job

logger = structlog.get_logger(__name__)


class JobRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_jobs(self, jobs: list[Job], source: str) -> list[Job]:
        """Save jobs to the database. Returns only the NEW jobs."""

        # 1. Skip jobs without a URL, and remove duplicates in this batch
        unique_jobs = {}
        for job in jobs:
            if not job.url:
                logger.warning("job_without_url_skipped", title=job.title)
                continue
            unique_jobs[job.url] = job

        if not unique_jobs:
            return []

        # 2. Ask the database which of these URLs it already has
        result = await self.session.execute(
            select(JobRecord.url).where(JobRecord.url.in_(unique_jobs.keys()))
        )
        existing_urls = set(result.scalars().all())

        # 3. Jobs we've seen before: only update last_seen_at
        if existing_urls:
            await self.session.execute(
                update(JobRecord)
                .where(JobRecord.url.in_(existing_urls))
                .values(last_seen_at=func.now())
            )

        # 4. New jobs: insert them
        new_jobs = [
            job for url, job in unique_jobs.items() if url not in existing_urls
        ]

        for job in new_jobs:
            self.session.add(
                JobRecord(
                    source=source,
                    url=job.url,
                    title=job.title,
                    company=job.company,
                    location=job.location,
                    experience=job.experience,
                    description=job.description,
                    skills=job.skills,
                )
            )

        # 5. Save everything in one transaction
        await self.session.commit()

        logger.info(
            "jobs_saved",
            received=len(jobs),
            unique=len(unique_jobs),
            new=len(new_jobs),
            already_seen=len(existing_urls),
        )

        return new_jobs
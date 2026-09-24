from datetime import timedelta

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobMatchRecord, JobRecord
from app.models.job import Job
from app.models.job_match import JobMatchResult

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
    
    async def get_ids_by_urls(self, urls: list[str]) -> dict[str, int]:
        """Return {url: job id} for jobs saved in the database."""
        result = await self.session.execute(
            select(JobRecord.url, JobRecord.id).where(JobRecord.url.in_(urls))
        )
        return {url: job_id for url, job_id in result.all()}

    async def get_unmatched_jobs_with_ids(
        self, max_age_days: int = 14
    ) -> list[tuple[int, Job]]:
        """All recently seen jobs that have NO saved match yet, as (id, Job)."""
        result = await self.session.execute(
            select(JobRecord)
            .outerjoin(JobMatchRecord, JobMatchRecord.job_id == JobRecord.id)
            .where(JobMatchRecord.id.is_(None))
            .where(JobRecord.last_seen_at >= func.now() - timedelta(days=max_age_days))
            .order_by(JobRecord.id)
        )
        records = result.scalars().all()

        jobs_with_ids = [
            (
                record.id,
                Job(
                    title=record.title,
                    company=record.company,
                    location=record.location or "",
                    description=record.description or "",
                    experience=record.experience,
                    skills=record.skills or [],
                    url=record.url,
                ),
            )
            for record in records
        ]

        logger.info(
            "unmatched_jobs_loaded",
            count=len(jobs_with_ids),
            max_age_days=max_age_days,
        )
        return jobs_with_ids

    async def save_match(
        self,
        job_id: int,
        match: JobMatchResult,
        overall_score: int,
        match_level: str,
    ) -> None:
        """Save the LLM match result for one job."""
        self.session.add(
            JobMatchRecord(
                job_id=job_id,
                role_match=match.role_match,
                skill_match=match.skill_match,
                experience_match=match.experience_match,
                overall_score=overall_score,
                match_level=match_level,
                matching_skills=match.matching_skills,
                missing_skills=match.missing_skills,
                strengths=match.strengths,
                concerns=match.concerns,
                recommendation=match.recommendation,
            )
        )

        await self.session.commit()

        logger.info("match_saved", job_id=job_id, overall_score=overall_score)

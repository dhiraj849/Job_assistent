"""Job detail columns on the REAL local Postgres (rolled back; see test_applications_db)."""

from datetime import date

import pytest
from sqlalchemy import select

from app.db.job_repository import JobRepository
from app.db.models import JobRecord
from app.models.job_details import JobDetailPage, JobDetails
from tests.integration.test_applications_db import new_job, run_in_rollback

pytestmark = pytest.mark.integration

PAGE = JobDetailPage(
    description="Full JD. " * 20,
    details=JobDetails(
        source="json_ld", skills=["Python"], salary="15-25 Lacs P.A",
        experience_months=72, date_posted=date(2026, 9, 25),
    ),
)


def test_new_job_has_no_details_and_uses_the_snippet():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        await session.execute(
            JobRecord.__table__.update().where(JobRecord.id == job_id).values(description="snippet")
        )

        job = await repo.get_job(job_id)
        assert job.description == "snippet"
        assert job.details is None and job.salary is None

    run_in_rollback(test)


def test_saved_details_win_over_the_snippet_and_round_trip():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)

        await repo.save_details(job_id, PAGE)
        session.expire_all()
        job = await repo.get_job(job_id)

        assert job.description == PAGE.description
        assert job.details == PAGE.details  # JSONB -> JobDetails, dates included
        assert job.salary == "15-25 Lacs P.A"
        record = await session.scalar(select(JobRecord).where(JobRecord.id == job_id))
        assert record.details_fetched_at is not None
        # The card snippet is kept, never overwritten.
        assert record.description is None or record.description != PAGE.description

    run_in_rollback(test)


def test_saving_twice_is_idempotent():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)

        await repo.save_details(job_id, PAGE)
        await repo.save_details(job_id, PAGE)
        session.expire_all()

        assert (await repo.get_job(job_id)).details == PAGE.details

    run_in_rollback(test)

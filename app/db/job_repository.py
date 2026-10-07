from datetime import datetime, timedelta

import structlog
from sqlalchemy import and_, func, not_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApplicationRecord, JobDecisionRecord, JobMatchRecord, JobRecord
from app.models.application import Application, ApplicationOutcome
from app.models.decision import Decision, JobDecision
from app.models.job import Job
from app.models.job_match import JobMatchResult
from app.models.job_status import JobStatus

logger = structlog.get_logger(__name__)

# Rows that must never be overwritten: a real (not dry-run) apply happened.
# Used as a WHERE guard on every applications write, so even buggy code
# cannot turn an applied job back into pending/failed.
_NOT_APPLIED_LIVE = not_(
    and_(
        ApplicationRecord.outcome == ApplicationOutcome.APPLIED.value,
        ApplicationRecord.dry_run.is_(False),
    )
)


def _applied_live_exists(job_id):
    """EXISTS(a live-applied applications row for job_id); job_id may be a column."""
    return (
        select(ApplicationRecord.id)
        .where(ApplicationRecord.job_id == job_id)
        .where(~_NOT_APPLIED_LIVE)
        .exists()
    )


class ApplicationNotWritableError(RuntimeError):
    """The applications row is missing (never approved) or already applied live."""


# Any fixed number works; it just names "the apply lock" for pg_advisory_xact_lock.
APPLY_LOCK_KEY = 4201


def _to_job(record: JobRecord) -> Job:
    """Turn a database row into the Job DTO used by services."""
    return Job(
        title=record.title,
        company=record.company,
        location=record.location or "",
        description=record.description or "",
        experience=record.experience,
        skills=record.skills or [],
        url=record.url,
    )


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

        jobs_with_ids = [(record.id, _to_job(record)) for record in records]

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
        """Save the LLM match result for one job (latest evaluation wins).

        Upsert, so a retried activity or a re-run workflow for the same job
        does not fail on the unique job_id.
        """
        values = dict(
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
        stmt = insert(JobMatchRecord).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[JobMatchRecord.job_id],
            set_={k: v for k, v in values.items() if k != "job_id"},
        )
        await self.session.execute(stmt)

        await self.session.commit()

        logger.info("match_saved", job_id=job_id, overall_score=overall_score)

    async def get_job(self, job_id: int) -> Job | None:
        """Load one job by id, or None if it does not exist."""
        record = await self.session.get(JobRecord, job_id)
        return _to_job(record) if record else None

    async def update_status(self, job_id: int, status: JobStatus) -> bool:
        """Set a job's lifecycle status and when it changed.

        Returns False if refused: "applied" (live) is terminal (see _set_job_status).
        """
        written = await self._set_job_status(job_id, status)
        await self.session.commit()

        if written:
            logger.info("job_status_updated", job_id=job_id, status=status.value)
        return written

    async def is_applied_live(self, job_id: int) -> bool:
        """True if this job was really applied (not a dry run). Reads applications."""
        return await self.session.scalar(select(_applied_live_exists(job_id)))

    async def get_status(self, job_id: int) -> str | None:
        return await self.session.scalar(
            select(JobRecord.status).where(JobRecord.id == job_id)
        )

    async def lock_applies(self) -> None:
        """Serialize applies until this transaction ends (commit or rollback).

        Without it, two apply activities could both see "9 of 10 used" and
        both apply. The lock is released automatically with the transaction.
        """
        await self.session.execute(select(func.pg_advisory_xact_lock(APPLY_LOCK_KEY)))

    async def get_pending_approvals(self) -> list[tuple[int, str, str, int, str]]:
        """Jobs waiting for a human decision: (id, title, company, score, level)."""
        result = await self.session.execute(
            select(
                JobRecord.id,
                JobRecord.title,
                JobRecord.company,
                JobMatchRecord.overall_score,
                JobMatchRecord.match_level,
            )
            .join(JobMatchRecord, JobMatchRecord.job_id == JobRecord.id)
            .where(JobRecord.status == JobStatus.AWAITING_APPROVAL.value)
            .order_by(JobMatchRecord.overall_score.desc())
        )
        return [tuple(row) for row in result.all()]

    # ---------------------------------------------------------------
    # Applications
    #
    # applied_at / updated_at use clock_timestamp(), not now(): now() is the
    # start of the transaction, and an apply holds its transaction open
    # (lock) for the whole browser run.
    # ---------------------------------------------------------------

    async def get_application(self, job_id: int) -> Application | None:
        record = await self.session.scalar(
            select(ApplicationRecord).where(ApplicationRecord.job_id == job_id)
        )
        if record is None:
            return None
        return Application(
            outcome=ApplicationOutcome(record.outcome),
            reason=record.reason,
            dry_run=record.dry_run,
            approved_at=record.approved_at,
            approval_note=record.approval_note,
            applied_at=record.applied_at,
            artifacts_dir=record.artifacts_dir,
        )

    async def record_approval(
        self, job_id: int, approved_at: datetime, note: str, workflow_run_id: str
    ) -> bool:
        """Store my approval (pending row), the decision log row and
        jobs.status=approved, atomically.

        A re-approval (e.g. after failed) resets the row to pending. A job
        already applied live is left untouched; returns False then (the
        decision is still logged: I did say yes).
        """
        values = dict(
            outcome=ApplicationOutcome.PENDING.value,
            reason="",
            dry_run=False,
            approved_at=approved_at,
            approval_note=note,
            applied_at=None,
            artifacts_dir=None,
        )
        stmt = insert(ApplicationRecord).values(job_id=job_id, **values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[ApplicationRecord.job_id],
            set_={**values, "updated_at": func.clock_timestamp()},
            where=_NOT_APPLIED_LIVE,
        ).returning(ApplicationRecord.id)
        written = await self.session.scalar(stmt) is not None

        await self._insert_decision(job_id, Decision.APPROVED, approved_at, note, workflow_run_id)
        if written:
            await self._set_job_status(job_id, JobStatus.APPROVED)
        await self.session.commit()

        logger.info("approval_recorded", job_id=job_id, written=written)
        return written

    async def record_decision(
        self,
        job_id: int,
        decision: Decision,
        decided_at: datetime,
        note: str,
        workflow_run_id: str,
    ) -> None:
        """Log a rejection / expiry and set the matching jobs.status, in one commit.

        Approvals go through record_approval (they also need an applications row).
        """
        if decision == Decision.APPROVED:
            raise ValueError("use record_approval for approvals")
        await self._insert_decision(job_id, decision, decided_at, note, workflow_run_id)
        await self._set_job_status(job_id, JobStatus(decision.value))
        await self.session.commit()

        logger.info("decision_recorded", job_id=job_id, decision=decision.value)

    async def get_decisions(self, job_id: int) -> list[JobDecision]:
        """All decisions for one job, oldest first."""
        records = await self.session.scalars(
            select(JobDecisionRecord)
            .where(JobDecisionRecord.job_id == job_id)
            .order_by(JobDecisionRecord.decided_at, JobDecisionRecord.id)
        )
        return [
            JobDecision(
                decision=Decision(r.decision),
                note=r.note,
                decided_at=r.decided_at,
                workflow_run_id=r.workflow_run_id,
            )
            for r in records
        ]

    async def _insert_decision(
        self,
        job_id: int,
        decision: Decision,
        decided_at: datetime,
        note: str,
        workflow_run_id: str,
    ) -> None:
        # No commit. DO NOTHING on the run id: a retried activity (same run)
        # must not log the same decision twice.
        await self.session.execute(
            insert(JobDecisionRecord)
            .values(
                job_id=job_id,
                decision=decision.value,
                note=note,
                decided_at=decided_at,
                workflow_run_id=workflow_run_id,
            )
            .on_conflict_do_nothing(index_elements=[JobDecisionRecord.workflow_run_id])
        )

    async def save_apply_result(
        self,
        job_id: int,
        outcome: ApplicationOutcome,
        job_status: JobStatus,
        reason: str,
        dry_run: bool,
        artifacts_dir: str | None,
    ) -> None:
        """Write the apply result to applications AND jobs.status in ONE commit.

        Either both change or neither does. Called inside the apply lock,
        so this commit also releases the lock.
        """
        applied = outcome == ApplicationOutcome.APPLIED
        stmt = (
            update(ApplicationRecord)
            .where(ApplicationRecord.job_id == job_id)
            .where(_NOT_APPLIED_LIVE)
            .values(
                outcome=outcome.value,
                reason=reason,
                dry_run=dry_run,
                applied_at=func.clock_timestamp() if applied else None,
                artifacts_dir=artifacts_dir,
                updated_at=func.clock_timestamp(),
            )
            .returning(ApplicationRecord.id)
        )
        if await self.session.scalar(stmt) is None:
            await self.session.rollback()
            raise ApplicationNotWritableError(
                f"job {job_id}: no approved application row, or already applied live"
            )

        await self._set_job_status(job_id, job_status)
        await self.session.commit()

        logger.info("apply_result_saved", job_id=job_id, outcome=outcome.value, dry_run=dry_run)

    async def record_manual_apply(self, job_id: int, reason: str) -> bool:
        """Record an apply I did by hand (outside ApplyService). False if
        the job is already recorded as applied live.

        Doing it myself is the approval, so a missing row gets approved_at=now.
        """
        stmt = insert(ApplicationRecord).values(
            job_id=job_id,
            outcome=ApplicationOutcome.APPLIED.value,
            reason=reason,
            dry_run=False,
            approved_at=func.clock_timestamp(),
            approval_note="manual apply",
            applied_at=func.clock_timestamp(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ApplicationRecord.job_id],
            # approved_at is kept: the earlier approval is the real one.
            set_=dict(
                outcome=ApplicationOutcome.APPLIED.value,
                reason=reason,
                dry_run=False,
                applied_at=func.clock_timestamp(),
                updated_at=func.clock_timestamp(),
            ),
            where=_NOT_APPLIED_LIVE,
        ).returning(ApplicationRecord.id)
        written = await self.session.scalar(stmt) is not None

        if written:
            await self._set_job_status(job_id, JobStatus.APPLIED)
        await self.session.commit()

        logger.info("manual_apply_recorded", job_id=job_id, written=written)
        return written

    async def insert_application_if_missing(self, job_id: int, **values) -> bool:
        """Backfill helper: insert a row unless the job already has one."""
        stmt = (
            insert(ApplicationRecord)
            .values(job_id=job_id, **values)
            .on_conflict_do_nothing(index_elements=[ApplicationRecord.job_id])
            .returning(ApplicationRecord.id)
        )
        written = await self.session.scalar(stmt) is not None
        await self.session.commit()
        return written

    async def get_applied_jobs_without_application(self) -> list[tuple[int, datetime]]:
        """Jobs marked applied before the applications table existed: (id, status_updated_at)."""
        result = await self.session.execute(
            select(JobRecord.id, JobRecord.status_updated_at)
            .outerjoin(ApplicationRecord, ApplicationRecord.job_id == JobRecord.id)
            .where(JobRecord.status == JobStatus.APPLIED.value)
            .where(ApplicationRecord.id.is_(None))
            .order_by(JobRecord.id)
        )
        return [tuple(row) for row in result.all()]

    async def count_applied_since(self, dry_run: bool, since: datetime) -> int:
        """Applies (live or dry-run) done at or after `since`, for the daily cap."""
        return await self.session.scalar(
            select(func.count())
            .select_from(ApplicationRecord)
            .where(ApplicationRecord.outcome == ApplicationOutcome.APPLIED.value)
            .where(ApplicationRecord.dry_run.is_(dry_run))
            .where(ApplicationRecord.applied_at >= since)
        )

    async def get_jobs_needing_attention(
        self,
    ) -> list[tuple[int, str, str, str, str, str | None]]:
        """needs_manual / failed jobs: (id, title, company, status, reason, artifacts_dir).

        Outer join: a workflow can fail before approval, so there is no row (and no reason).
        """
        result = await self.session.execute(
            select(
                JobRecord.id,
                JobRecord.title,
                JobRecord.company,
                JobRecord.status,
                func.coalesce(ApplicationRecord.reason, ""),
                ApplicationRecord.artifacts_dir,
            )
            .outerjoin(ApplicationRecord, ApplicationRecord.job_id == JobRecord.id)
            .where(JobRecord.status.in_([JobStatus.NEEDS_MANUAL.value, JobStatus.FAILED.value]))
            .order_by(JobRecord.status_updated_at.desc())
        )
        return [tuple(row) for row in result.all()]

    async def _set_job_status(self, job_id: int, status: JobStatus) -> bool:
        """Write jobs.status; no commit, the caller commits it with its other writes.

        "applied" (live) is terminal: any other status is refused for such a
        job (returns False). The guard sits in the UPDATE's WHERE, so there is
        no check-then-write race. Defense in depth behind the workflow's own
        already-applied check.
        """
        stmt = (
            update(JobRecord)
            .where(JobRecord.id == job_id)
            .values(status=status.value, status_updated_at=func.clock_timestamp())
            .returning(JobRecord.id)
        )
        if status != JobStatus.APPLIED:
            stmt = stmt.where(~_applied_live_exists(JobRecord.id))
        written = await self.session.scalar(stmt) is not None
        if not written:
            # Loud on purpose: a refused write means some caller has a bug.
            logger.warning("job_status_update_refused", job_id=job_id, status=status.value)
        return written

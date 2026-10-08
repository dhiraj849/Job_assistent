"""applications rules on the REAL local Postgres (needs `alembic upgrade head`).

Every test runs inside one outer transaction that is always rolled back:
the repository's commit() only releases a SAVEPOINT, so nothing is kept.
Skipped when Postgres is not running.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.database import database_url
from app.db.job_repository import ApplicationNotWritableError, JobRepository
from app.db.models import JobRecord
from app.models.application import ApplicationOutcome
from app.models.decision import Decision
from app.models.job_status import JobStatus

pytestmark = pytest.mark.integration

APPROVED_AT = datetime.now(timezone.utc) - timedelta(hours=1)


def run_in_rollback(test):
    """Run `await test(repo, session)` in a transaction that is rolled back."""

    async def main():
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                outer = await connection.begin()
                session = AsyncSession(
                    bind=connection,
                    join_transaction_mode="create_savepoint",
                    expire_on_commit=False,
                )
                try:
                    await test(JobRepository(session), session)
                finally:
                    await session.close()
                    await outer.rollback()
        finally:
            await engine.dispose()

    try:
        asyncio.run(main())
    except OSError as error:  # connection refused: stack not running
        pytest.skip(f"Postgres not reachable: {error}")


def run_id() -> str:
    """A fresh Temporal workflow run id (the job_decisions idempotency key)."""
    return str(uuid.uuid4())


async def new_job(session: AsyncSession, status: JobStatus = JobStatus.AWAITING_APPROVAL) -> int:
    job = JobRecord(
        source="test", url=f"https://test/{uuid.uuid4()}", title="T", company="C",
        skills=[], status=status.value,
    )
    session.add(job)
    await session.flush()
    return job.id


async def job_status(session: AsyncSession, job_id: int) -> str:
    return await session.scalar(select(JobRecord.status).where(JobRecord.id == job_id))


def test_approval_then_apply_writes_both_tables():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)

        assert await repo.record_approval(job_id, APPROVED_AT, "looks good", run_id())
        application = await repo.get_application(job_id)
        assert application.outcome == ApplicationOutcome.PENDING
        assert application.approval_note == "looks good"
        assert await job_status(session, job_id) == "approved"

        await repo.save_apply_result(
            job_id, ApplicationOutcome.APPLIED, JobStatus.APPLIED, "", False, "artifacts/apply/x"
        )
        application = await repo.get_application(job_id)
        assert application.applied_live
        assert application.applied_at > APPROVED_AT
        assert await job_status(session, job_id) == "applied"
        assert await repo.count_applied_since(False, APPROVED_AT) >= 1

    run_in_rollback(test)


def test_live_applied_row_is_never_overwritten():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        await repo.record_approval(job_id, APPROVED_AT, "", run_id())
        await repo.save_apply_result(job_id, ApplicationOutcome.APPLIED, JobStatus.APPLIED, "", False, None)

        # A second apply result is refused...
        with pytest.raises(ApplicationNotWritableError):
            await repo.save_apply_result(
                job_id, ApplicationOutcome.FAILED, JobStatus.FAILED, "boom", False, None
            )
        # ...and so is a re-approval (the workflow-restart case from the bug).
        assert not await repo.record_approval(job_id, APPROVED_AT, "again", run_id())
        assert not await repo.record_manual_apply(job_id, "by hand")

        assert (await repo.get_application(job_id)).applied_live
        assert await job_status(session, job_id) == "applied"

    run_in_rollback(test)


def test_unique_job_id_allows_one_application_per_job():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        row = dict(outcome="pending", approved_at=APPROVED_AT)
        assert await repo.insert_application_if_missing(job_id, **row)
        assert not await repo.insert_application_if_missing(job_id, **row)

        # Without ON CONFLICT, the UNIQUE constraint itself refuses it.
        with pytest.raises(IntegrityError, match="applications_job_id_key"):
            await session.execute(
                text("INSERT INTO applications (job_id, outcome, approved_at) VALUES (:j, 'pending', now())"),
                {"j": job_id},
            )
        await session.rollback()

    run_in_rollback(test)


def test_status_and_application_change_together_or_not_at_all(monkeypatch):
    """Fail AFTER the applications write: the rollback must undo it too."""

    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        await repo.record_approval(job_id, APPROVED_AT, "", run_id())

        async def broken_status_write(job_id, status):
            raise RuntimeError("jobs update failed")

        monkeypatch.setattr(repo, "_set_job_status", broken_status_write)
        with pytest.raises(RuntimeError):
            await repo.save_apply_result(
                job_id, ApplicationOutcome.APPLIED, JobStatus.APPLIED, "", False, None
            )
        await session.rollback()  # what closing the activity's session does

        assert (await repo.get_application(job_id)).outcome == ApplicationOutcome.PENDING
        assert await job_status(session, job_id) == "approved"

    run_in_rollback(test)


@pytest.mark.parametrize(
    ("row", "constraint"),
    [
        (dict(outcome="applied"), "ck_applications_applied_at"),  # applied without applied_at
        (dict(outcome="pending", applied_at=APPROVED_AT), "ck_applications_applied_at"),
        (dict(outcome="needs_manual", reason=""), "ck_applications_reason"),
        (dict(outcome="typo"), "ck_applications_outcome"),
        (
            dict(outcome="applied", applied_at=APPROVED_AT - timedelta(minutes=1)),
            "ck_applications_applied_after_approval",
        ),
    ],
)
def test_check_constraints_reject_impossible_rows(row, constraint):
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        with pytest.raises(IntegrityError, match=constraint):
            await repo.insert_application_if_missing(job_id, approved_at=APPROVED_AT, **row)
        await session.rollback()

    run_in_rollback(test)


def test_manual_apply_records_row_and_status():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)

        assert await repo.record_manual_apply(job_id, "company site")
        application = await repo.get_application(job_id)
        assert application.applied_live
        assert application.reason == "company site"
        assert await job_status(session, job_id) == "applied"

    run_in_rollback(test)


# --- update_status guard: "applied" (live) is terminal --------------------


def test_status_of_live_applied_job_is_never_rewritten():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        await repo.record_manual_apply(job_id, "by hand")
        assert await repo.is_applied_live(job_id)

        # What a re-started workflow (gap #14) or its failure handler would write.
        for status in (JobStatus.SHORTLISTED, JobStatus.REJECTED, JobStatus.FAILED):
            assert not await repo.update_status(job_id, status)
        assert await job_status(session, job_id) == "applied"

        # Syncing back TO applied stays allowed (ApplyService does this).
        assert await repo.update_status(job_id, JobStatus.APPLIED)

    run_in_rollback(test)


def test_dry_run_apply_does_not_lock_the_status():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        await repo.record_approval(job_id, APPROVED_AT, "", run_id())
        await repo.save_apply_result(
            job_id, ApplicationOutcome.APPLIED, JobStatus.APPLIED_DRY_RUN, "dry", True, None
        )

        # A dry run must never block the real apply later.
        assert not await repo.is_applied_live(job_id)
        assert await repo.update_status(job_id, JobStatus.AWAITING_APPROVAL)
        assert await job_status(session, job_id) == "awaiting_approval"

    run_in_rollback(test)


def test_guard_only_looks_at_its_own_job():
    async def test(repo: JobRepository, session):
        applied_job = await new_job(session)
        other_job = await new_job(session)
        await repo.record_manual_apply(applied_job, "by hand")

        # The correlated EXISTS must match on job_id, not "any applied row".
        assert not await repo.is_applied_live(other_job)
        assert await repo.update_status(other_job, JobStatus.SHORTLISTED)

    run_in_rollback(test)


# --- job_decisions ----------------------------------------------------------


def test_rejection_is_logged_with_status_in_one_commit():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)

        await repo.record_decision(job_id, Decision.REJECTED, APPROVED_AT, "too junior", run_id())

        [decision] = await repo.get_decisions(job_id)
        assert decision.decision == Decision.REJECTED
        assert decision.note == "too junior"
        assert decision.decided_at == APPROVED_AT
        assert await job_status(session, job_id) == "rejected"
        # A rejection never creates an applications row (= never approved).
        assert await repo.get_application(job_id) is None

    run_in_rollback(test)


def test_retried_decision_is_logged_once():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        run = run_id()

        # Same workflow run = an activity retry.
        await repo.record_decision(job_id, Decision.EXPIRED, APPROVED_AT, "", run)
        await repo.record_decision(job_id, Decision.EXPIRED, APPROVED_AT, "", run)

        assert len(await repo.get_decisions(job_id)) == 1
        assert await job_status(session, job_id) == "expired"

    run_in_rollback(test)


def test_approval_is_logged_and_history_is_kept():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)

        # Rejected in one run, approved in a later run: both stay.
        await repo.record_decision(job_id, Decision.REJECTED, APPROVED_AT, "not now", run_id())
        await repo.record_approval(job_id, APPROVED_AT + timedelta(days=1), "ok now", run_id())

        decisions = await repo.get_decisions(job_id)
        assert [d.decision for d in decisions] == [Decision.REJECTED, Decision.APPROVED]
        assert decisions[1].note == "ok now"
        assert await job_status(session, job_id) == "approved"

    run_in_rollback(test)


def test_decision_on_live_applied_job_keeps_status_applied():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        await repo.record_manual_apply(job_id, "by hand")

        # The decision is still logged (it happened), but the guard keeps "applied".
        await repo.record_decision(job_id, Decision.REJECTED, APPROVED_AT, "", run_id())
        assert [d.decision for d in await repo.get_decisions(job_id)] == [Decision.REJECTED]
        assert await job_status(session, job_id) == "applied"

    run_in_rollback(test)


def test_record_decision_refuses_approvals():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        with pytest.raises(ValueError, match="record_approval"):
            await repo.record_decision(job_id, Decision.APPROVED, APPROVED_AT, "", run_id())

    run_in_rollback(test)


def test_check_constraint_rejects_unknown_decision():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        with pytest.raises(IntegrityError, match="ck_job_decisions_decision"):
            await session.execute(
                text(
                    "INSERT INTO job_decisions (job_id, decision, decided_at, workflow_run_id)"
                    " VALUES (:j, 'maybe', now(), :r)"
                ),
                {"j": job_id, "r": run_id()},
            )
        await session.rollback()

    run_in_rollback(test)


# --- expire_approval (daily cap stayed full, known issue #15) -------------

CAP_REASON = "daily cap full on 4 days in a row; never tried"


def test_pending_approval_expires_with_reason_and_status_in_one_commit(monkeypatch):
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        await repo.record_approval(job_id, APPROVED_AT, "", run_id())

        commits = []
        real_commit = session.commit

        async def counting_commit():
            commits.append(1)
            await real_commit()

        monkeypatch.setattr(session, "commit", counting_commit)
        assert await repo.expire_approval(job_id, CAP_REASON)

        assert len(commits) == 1
        application = await repo.get_application(job_id)
        assert application.outcome == ApplicationOutcome.EXPIRED
        assert application.reason == CAP_REASON
        assert application.applied_at is None
        assert await job_status(session, job_id) == "expired"

    run_in_rollback(test)


def test_expire_rolls_back_both_when_status_write_fails(monkeypatch):
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        await repo.record_approval(job_id, APPROVED_AT, "", run_id())

        async def broken_status_write(job_id, status):
            raise RuntimeError("jobs update failed")

        monkeypatch.setattr(repo, "_set_job_status", broken_status_write)
        with pytest.raises(RuntimeError):
            await repo.expire_approval(job_id, CAP_REASON)
        await session.rollback()  # what closing the activity's session does

        assert (await repo.get_application(job_id)).outcome == ApplicationOutcome.PENDING
        assert await job_status(session, job_id) == "approved"

    run_in_rollback(test)


def test_expire_never_touches_a_live_applied_row():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        await repo.record_manual_apply(job_id, "by hand")

        assert not await repo.expire_approval(job_id, CAP_REASON)
        application = await repo.get_application(job_id)
        assert application.applied_live
        assert application.reason == "by hand"
        assert await job_status(session, job_id) == "applied"

    run_in_rollback(test)


def test_expire_leaves_a_failed_row_untouched():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        await repo.record_approval(job_id, APPROVED_AT, "", run_id())
        await repo.save_apply_result(
            job_id, ApplicationOutcome.FAILED, JobStatus.FAILED, "boom", False, None
        )

        assert not await repo.expire_approval(job_id, CAP_REASON)
        application = await repo.get_application(job_id)
        assert application.outcome == ApplicationOutcome.FAILED
        assert application.reason == "boom"
        assert await job_status(session, job_id) == "failed"

    run_in_rollback(test)


def test_expired_approval_can_be_approved_again():
    async def test(repo: JobRepository, session):
        job_id = await new_job(session)
        await repo.record_approval(job_id, APPROVED_AT, "", run_id())
        await repo.expire_approval(job_id, CAP_REASON)

        # A later "yes" (new workflow run) starts over from pending.
        assert await repo.record_approval(job_id, APPROVED_AT + timedelta(days=5), "again", run_id())
        application = await repo.get_application(job_id)
        assert application.outcome == ApplicationOutcome.PENDING
        assert application.reason == ""
        assert await job_status(session, job_id) == "approved"

    run_in_rollback(test)


def test_daily_cap_does_not_count_expired_rows():
    async def test(repo: JobRepository, session):
        before = await repo.count_applied_since(False, APPROVED_AT)
        before_dry = await repo.count_applied_since(True, APPROVED_AT)

        job_id = await new_job(session)
        await repo.record_approval(job_id, APPROVED_AT, "", run_id())
        await repo.expire_approval(job_id, CAP_REASON)

        assert await repo.count_applied_since(False, APPROVED_AT) == before
        assert await repo.count_applied_since(True, APPROVED_AT) == before_dry

    run_in_rollback(test)

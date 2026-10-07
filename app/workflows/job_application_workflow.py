import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError

from app.workflows.retry import RETRY_POLICY

# Activities import browser/DB/LLM libraries. Passing them through keeps the
# workflow sandbox from re-importing them (they are never called here directly).
with workflow.unsafe.imports_passed_through():
    from app.models.job_status import JobStatus
    from app.workflows.activities import (
        apply_job_dry_run,
        filter_job,
        load_job,
        match_job,
        save_match,
        semantic_score,
        update_job_status,
    )

APPROVAL_TIMEOUT = timedelta(days=3)
DB_TIMEOUT = timedelta(seconds=30)

# Only these LLM levels are worth a human's time; "weak" ends as filtered_out.
APPROVAL_LEVELS = {"strong", "potential"}


@workflow.defn
class JobApplicationWorkflow:
    """One job from evaluation to (dry-run) apply. Workflow id: job-{job_id}.

    Nothing is applied without a human "yes" via the decide signal.
    """

    def __init__(self) -> None:
        self._status = JobStatus.DISCOVERED
        self._approved: bool | None = None
        self._note = ""

    @workflow.run
    async def run(self, job_id: int) -> str:
        try:
            return await self._run(job_id)
        except ActivityError:
            # An activity gave up after its retries: record it, then fail
            # the workflow so the error stays visible in the Temporal UI.
            await self._set_status(job_id, JobStatus.FAILED)
            raise

    async def _run(self, job_id: int) -> str:
        job = await workflow.execute_activity(
            load_job, job_id, start_to_close_timeout=DB_TIMEOUT, retry_policy=RETRY_POLICY
        )

        # 1. Cheap keyword filter
        keep = await workflow.execute_activity(
            filter_job, job, start_to_close_timeout=DB_TIMEOUT, retry_policy=RETRY_POLICY
        )
        if not keep:
            return await self._set_status(job_id, JobStatus.FILTERED_OUT)

        # 2. Semantic similarity to the profile (Qdrant)
        score = await workflow.execute_activity(
            semantic_score,
            args=[job_id, job],
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RETRY_POLICY,
        )
        if score is None:
            return await self._set_status(job_id, JobStatus.FILTERED_OUT)

        await self._set_status(job_id, JobStatus.SHORTLISTED)

        # 3. LLM match (the expensive step) + save
        item = await workflow.execute_activity(
            match_job,
            job,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RETRY_POLICY,
        )
        await workflow.execute_activity(
            save_match,
            args=[job_id, item],
            start_to_close_timeout=DB_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        await self._set_status(job_id, JobStatus.MATCHED)

        if item.match_level not in APPROVAL_LEVELS:
            return await self._set_status(job_id, JobStatus.FILTERED_OUT)

        # 4. Wait for a human decision (durable: survives worker restarts)
        await self._set_status(job_id, JobStatus.AWAITING_APPROVAL)
        try:
            await workflow.wait_condition(
                lambda: self._approved is not None, timeout=APPROVAL_TIMEOUT
            )
        except asyncio.TimeoutError:
            return await self._set_status(job_id, JobStatus.EXPIRED)

        if not self._approved:
            return await self._set_status(job_id, JobStatus.REJECTED)

        # 5. Apply (DRY-RUN only: logs, no clicks)
        await self._set_status(job_id, JobStatus.APPROVED)
        await workflow.execute_activity(
            apply_job_dry_run,
            job_id,
            start_to_close_timeout=DB_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        return await self._set_status(job_id, JobStatus.APPLIED_DRY_RUN)

    async def _set_status(self, job_id: int, status: JobStatus) -> str:
        # All DB writes go through an activity; the workflow only keeps a copy
        # for the current_status query.
        await workflow.execute_activity(
            update_job_status,
            args=[job_id, status],
            start_to_close_timeout=DB_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        self._status = status
        return status.value

    @workflow.signal
    def decide(self, approved: bool, note: str = "") -> None:
        # Ignore early (or repeated) decisions so nothing gets approved
        # before the human has actually seen the match.
        if self._status != JobStatus.AWAITING_APPROVAL or self._approved is not None:
            workflow.logger.warning(
                "decision ignored: status is %s", self._status.value
            )
            return
        self._approved = approved
        self._note = note

    @workflow.query
    def current_status(self) -> str:
        return self._status.value

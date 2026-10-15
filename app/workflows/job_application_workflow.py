import asyncio
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError

from app.workflows.retry import APPLY_RETRY_POLICY, RETRY_POLICY
from app.workflows.task_queues import BROWSER_TASK_QUEUE

# Activities import browser/DB/LLM libraries. Passing them through keeps the
# workflow sandbox from re-importing them (they are never called here directly).
with workflow.unsafe.imports_passed_through():
    from app.models.apply_result import ApplyOutcome, ApplyResult
    from app.models.decision import Decision
    from app.models.job import Job
    from app.models.job_status import JobStatus
    from app.workflows.activities import (
        apply_job,
        apply_job_dry_run,
        expire_approval,
        fetch_job_details,
        filter_job,
        is_applied_live,
        load_job,
        match_job,
        record_approval,
        record_decision,
        save_match,
        semantic_score,
        update_job_status,
    )

APPROVAL_TIMEOUT = timedelta(days=3)
DB_TIMEOUT = timedelta(seconds=30)
# Covers waiting for the apply lock plus (later) a real browser apply.
APPLY_TIMEOUT = timedelta(minutes=5)
# One page: delay + browser start + load. Time waiting in the browser
# queue is not counted (start_to_close starts when a worker picks it up).
DETAILS_TIMEOUT = timedelta(minutes=2)
# Queue wait + all attempts. Without it a down browser worker would park
# the workflow here forever; after it we go on with the snippet. A burst of
# ~20 new jobs drains in a few minutes, so 30 minutes is plenty.
DETAILS_DEADLINE = timedelta(minutes=30)

# Version marker for the apply_job_dry_run -> apply_job change (see _run).
APPLY_PATCH = "apply-job-v1"
# Version marker for update_job_status(APPROVED) -> record_approval.
APPROVAL_PATCH = "record-approval-v1"
# Version marker for the already-applied check at the start of _run.
SKIP_APPLIED_PATCH = "skip-if-applied-v1"
# Version marker for update_job_status(REJECTED/EXPIRED) -> record_decision.
DECISION_PATCH = "record-decision-v1"
# Version marker for the fetch_job_details step between filter and semantic score.
DETAILS_PATCH = "fetch-details-v1"
# Version marker for update_job_status(EXPIRED) -> expire_approval after the cap wait.
CAP_EXPIRY_PATCH = "cap-expiry-outcome-v1"

# If the daily cap is full, try again on this many following days, then give up:
# an approval older than that is probably stale.
MAX_CAP_WAIT_DAYS = 3
# Stored in applications.reason, so `apply_one` / lists show why it never ran.
CAP_EXPIRED_REASON = f"daily cap full on {MAX_CAP_WAIT_DAYS + 1} days in a row; never tried"

# Only these LLM levels are worth a human's time; "weak" ends as filtered_out.
APPROVAL_LEVELS = {"strong", "potential"}


@workflow.defn
class JobApplicationWorkflow:
    """One job from evaluation to apply. Workflow id: job-{job_id}.

    Nothing is applied without a human "yes" via the decide signal.
    """

    def __init__(self) -> None:
        self._status = JobStatus.DISCOVERED
        self._approved: bool | None = None
        self._note = ""
        self._decided_at: datetime | None = None

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
        # 0. A job applied live is done: a re-started workflow (e.g. via
        # scripts.start_job_workflow) must not re-run the LLM, ask me again,
        # or rewrite jobs.status. Behind a patch: in-flight histories started
        # with load_job as their first command and must replay unchanged.
        if workflow.patched(SKIP_APPLIED_PATCH):
            already_applied = await workflow.execute_activity(
                is_applied_live, job_id, start_to_close_timeout=DB_TIMEOUT, retry_policy=RETRY_POLICY
            )
            if already_applied:
                # Read-only on purpose: applications is the source of truth,
                # and the update_status guard keeps jobs.status at "applied".
                self._status = JobStatus.APPLIED
                return self._status.value

        job = await workflow.execute_activity(
            load_job, job_id, start_to_close_timeout=DB_TIMEOUT, retry_policy=RETRY_POLICY
        )

        # 1. Cheap keyword filter
        keep = await workflow.execute_activity(
            filter_job, job, start_to_close_timeout=DB_TIMEOUT, retry_policy=RETRY_POLICY
        )
        if not keep:
            return await self._set_status(job_id, JobStatus.FILTERED_OUT)

        # 1b. Full JD from the detail page, so embeddings and the LLM judge
        # the real job, not the 90-char card snippet. After the filter on
        # purpose: it only reads title + skills, so filtered-out jobs cost
        # no page request. Behind a patch: workflows already past this
        # point (e.g. waiting for approval) replay without it.
        if workflow.patched(DETAILS_PATCH):
            job = await self._fetch_details(job_id, job)

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
            # No answer is a decision too: logged so stats can tell it from "no".
            return await self._record_decision(job_id, Decision.EXPIRED, workflow.now(), "")

        if not self._approved:
            return await self._record_decision(
                job_id, Decision.REJECTED, self._decided_at, self._note
            )

        # 5. Record the approval (applications row + jobs.status), then apply.
        # Same patching idea as APPLY_PATCH below: old histories that already
        # ran update_job_status(APPROVED) replay the old path.
        if workflow.patched(APPROVAL_PATCH):
            await workflow.execute_activity(
                record_approval,
                args=[job_id, self._decided_at, self._note],
                start_to_close_timeout=DB_TIMEOUT,
                retry_policy=RETRY_POLICY,
            )
            self._status = JobStatus.APPROVED
        else:
            await self._set_status(job_id, JobStatus.APPROVED)

        # patched() is True for new code paths and records a marker in history.
        # On replay of a history WITHOUT the marker (it already ran the old
        # apply_job_dry_run), it returns False, so replay takes the old path
        # instead of failing with a non-determinism error.
        if workflow.patched(APPLY_PATCH):
            return await self._apply(job_id)

        # Pre-patch path, only for old histories. Remove with deprecate_patch later.
        await workflow.execute_activity(
            apply_job_dry_run,
            job_id,
            start_to_close_timeout=DB_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        return await self._set_status(job_id, JobStatus.APPLIED_DRY_RUN)

    async def _apply(self, job_id: int) -> str:
        for day in range(MAX_CAP_WAIT_DAYS + 1):
            result: ApplyResult = await workflow.execute_activity(
                apply_job,
                job_id,
                start_to_close_timeout=APPLY_TIMEOUT,
                retry_policy=APPLY_RETRY_POLICY,
            )
            if result.outcome != ApplyOutcome.SKIPPED_CAP:
                # The activity already wrote the final status in its locked
                # transaction; only mirror it here for the query.
                self._status = _final_status(result)
                return self._status.value

            if day < MAX_CAP_WAIT_DAYS:
                # Durable timer: survives worker restarts. The wait comes from
                # the activity result, so it is replay-safe.
                workflow.logger.info("daily cap reached, retrying in %ss", result.retry_after_seconds)
                await workflow.sleep(timedelta(seconds=result.retry_after_seconds))

        # New path: applications pending -> expired together with jobs.status,
        # so the row no longer looks queued (known issue #15). Histories that
        # already ran update_job_status(EXPIRED) replay the old path.
        if not workflow.patched(CAP_EXPIRY_PATCH):
            return await self._set_status(job_id, JobStatus.EXPIRED)

        await workflow.execute_activity(
            expire_approval,
            args=[job_id, CAP_EXPIRED_REASON],
            start_to_close_timeout=DB_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        self._status = JobStatus.EXPIRED
        return self._status.value

    async def _fetch_details(self, job_id: int, job: Job) -> Job:
        try:
            return await workflow.execute_activity(
                fetch_job_details,
                job_id,
                task_queue=BROWSER_TASK_QUEUE,
                start_to_close_timeout=DETAILS_TIMEOUT,
                schedule_to_close_timeout=DETAILS_DEADLINE,
                retry_policy=RETRY_POLICY,
            )
        except ActivityError as error:
            # Details improve the match but are not required: go on with the
            # snippet instead of failing the job. Visible in the log and as
            # jobs.details_fetched_at IS NULL.
            workflow.logger.warning(
                "job %s: details not fetched (%s), using the search snippet", job_id, error.cause
            )
            return job

    async def _record_decision(
        self, job_id: int, decision: Decision, decided_at: datetime, note: str
    ) -> str:
        status = JobStatus(decision.value)
        # Same patching idea as APPROVAL_PATCH: histories that already ran
        # update_job_status(REJECTED/EXPIRED) replay the old path.
        if not workflow.patched(DECISION_PATCH):
            return await self._set_status(job_id, status)

        await workflow.execute_activity(
            record_decision,
            args=[job_id, decision, decided_at, note],
            start_to_close_timeout=DB_TIMEOUT,
            retry_policy=RETRY_POLICY,
        )
        self._status = status
        return status.value

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
        # workflow.now() is deterministic (replay gives the same value) and is
        # when I decided, even if the activity that stores it runs later.
        self._decided_at = workflow.now()

    @workflow.query
    def current_status(self) -> str:
        return self._status.value


def _final_status(result: ApplyResult) -> JobStatus:
    if result.outcome == ApplyOutcome.APPLIED:
        return JobStatus.APPLIED_DRY_RUN if result.dry_run else JobStatus.APPLIED
    if result.outcome == ApplyOutcome.ALREADY_APPLIED:
        return JobStatus.APPLIED
    if result.outcome == ApplyOutcome.NEEDS_MANUAL:
        return JobStatus.NEEDS_MANUAL
    # Query mirror only (apply_job already wrote it): no new command, so no patch.
    if result.outcome == ApplyOutcome.READY_FOR_YOU:
        return JobStatus.READY_FOR_YOU
    return JobStatus.FAILED

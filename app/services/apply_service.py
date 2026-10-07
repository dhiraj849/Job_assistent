"""Safety rails around applying to one approved job.

Order of checks: lock → already applied? → daily cap → answers.yaml → apply.
Dependencies are injected so tests run without Postgres or a browser.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

import structlog
import yaml
from pydantic import ValidationError

from app.browser.job_applier import JobApplier
from app.models.apply_result import ApplyOutcome, ApplyResult
from app.models.job import Job
from app.models.job_status import JobStatus
from app.services.answers_loader import load_answers

logger = structlog.get_logger(__name__)

# "Today" for the daily cap is the Indian calendar day, like Naukri itself.
CAP_TIMEZONE = ZoneInfo("Asia/Kolkata")

# Final job status for each outcome. SKIPPED_CAP and ALREADY_APPLIED
# leave the status untouched.
STATUS_FOR_OUTCOME = {
    ApplyOutcome.NEEDS_MANUAL: JobStatus.NEEDS_MANUAL,
    ApplyOutcome.FAILED: JobStatus.FAILED,
}


class ApplyRepository(Protocol):
    async def lock_applies(self) -> None: ...
    async def get_job(self, job_id: int) -> Job | None: ...
    async def get_status(self, job_id: int) -> str | None: ...
    async def count_status_since(self, status: JobStatus, since: datetime) -> int: ...
    async def update_status(self, job_id: int, status: JobStatus) -> None: ...


def start_of_day(now: datetime) -> datetime:
    local = now.astimezone(CAP_TIMEZONE)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


class ApplyService:

    def __init__(
        self,
        repository: ApplyRepository,
        mode: Literal["dry_run", "live"],
        max_per_day: int,
        answers_path: Path,
        applier_factory: Callable[[], JobApplier],
        clock: Callable[[], datetime] = lambda: datetime.now(CAP_TIMEZONE),
    ):
        self.repository = repository
        self.dry_run = mode == "dry_run"
        self.max_per_day = max_per_day
        self.answers_path = answers_path
        # A factory, not an instance: in dry_run the browser is never even built.
        self.applier_factory = applier_factory
        self.clock = clock

    async def apply(self, job_id: int) -> ApplyResult:
        # Held until update_status commits, so check-cap-then-apply is atomic
        # across parallel activities.
        await self.repository.lock_applies()

        job = await self.repository.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        # 1. Idempotency: never apply twice, whatever the mode.
        if await self.repository.get_status(job_id) == JobStatus.APPLIED:
            return self._result(job_id, ApplyOutcome.ALREADY_APPLIED, "already applied")

        # 2. Daily cap. Dry runs count only dry runs, so testing never
        # eats the real quota.
        applied_status = JobStatus.APPLIED_DRY_RUN if self.dry_run else JobStatus.APPLIED
        now = self.clock()
        today = start_of_day(now)
        used = await self.repository.count_status_since(applied_status, today)
        if used >= self.max_per_day:
            tomorrow = today + timedelta(days=1)
            return self._result(
                job_id,
                ApplyOutcome.SKIPPED_CAP,
                f"daily cap reached ({used}/{self.max_per_day})",
                retry_after_seconds=int((tomorrow - now).total_seconds()) + 1,
            )

        # 3. Answers are validated in dry_run too, so a dry run proves the file is good.
        try:
            answers = load_answers(self.answers_path)
        except (FileNotFoundError, yaml.YAMLError, ValidationError) as error:
            return await self._finish(job_id, ApplyOutcome.FAILED, f"bad answers file: {error}")

        # 4. Apply
        if self.dry_run:
            logger.info("apply_dry_run", job_id=job_id, url=job.url)
            await self.repository.update_status(job_id, JobStatus.APPLIED_DRY_RUN)
            return self._result(job_id, ApplyOutcome.APPLIED, "dry run: nothing clicked")

        try:
            applied = await self.applier_factory().apply(job_id, job, answers)
        except Exception as error:
            # Recorded, not retried: a half-finished apply must be checked by a human.
            # Also covers an expired session (the reason says to log in again).
            logger.exception("apply_failed", job_id=job_id)
            return await self._finish(job_id, ApplyOutcome.FAILED, repr(error))

        if applied.outcome in (ApplyOutcome.APPLIED, ApplyOutcome.ALREADY_APPLIED):
            # ALREADY_APPLIED: Naukri says so (e.g. applied by hand): sync our status.
            await self.repository.update_status(job_id, JobStatus.APPLIED)
            return self._result(job_id, applied.outcome, applied.reason)
        return await self._finish(job_id, applied.outcome, applied.reason)

    async def _finish(self, job_id: int, outcome: ApplyOutcome, reason: str = "") -> ApplyResult:
        await self.repository.update_status(job_id, STATUS_FOR_OUTCOME[outcome])
        return self._result(job_id, outcome, reason)

    def _result(
        self,
        job_id: int,
        outcome: ApplyOutcome,
        reason: str = "",
        retry_after_seconds: int | None = None,
    ) -> ApplyResult:
        logger.info("apply_result", job_id=job_id, outcome=outcome.value, reason=reason)
        return ApplyResult(
            outcome=outcome,
            dry_run=self.dry_run,
            reason=reason,
            retry_after_seconds=retry_after_seconds,
        )

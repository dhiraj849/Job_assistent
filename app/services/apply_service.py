"""Safety rails around applying to one approved job.

Order of checks: lock → approved? → already applied? → company site already
opened? → daily cap → answers.yaml → apply.
The applications row (not jobs.status) is the source of truth: the workflow
rewrites jobs.status (e.g. to "approved") before every apply, so it cannot
prove a job was never applied. Dependencies are injected so tests run
without Postgres or a browser.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

import structlog
import yaml
from pydantic import ValidationError

from app.browser.job_applier import ARTIFACTS_DIR, JobApplier
from app.models.application import Application, ApplicationOutcome
from app.models.apply_result import ApplyOutcome, ApplyResult, CompanySite
from app.models.job import Job
from app.models.job_status import JobStatus
from app.services.answers_loader import load_answers

logger = structlog.get_logger(__name__)

# "Today" for the daily cap is the Indian calendar day, like Naukri itself.
CAP_TIMEZONE = ZoneInfo("Asia/Kolkata")

# Final (applications.outcome, jobs.status) for each browser outcome.
# SKIPPED_CAP writes nothing: the row stays pending.
RESULT_FOR_OUTCOME = {
    ApplyOutcome.NEEDS_MANUAL: (ApplicationOutcome.NEEDS_MANUAL, JobStatus.NEEDS_MANUAL),
    ApplyOutcome.FAILED: (ApplicationOutcome.FAILED, JobStatus.FAILED),
    # Naukri says "already applied" (e.g. applied by hand): record it as applied.
    ApplyOutcome.ALREADY_APPLIED: (ApplicationOutcome.APPLIED, JobStatus.APPLIED),
    ApplyOutcome.READY_FOR_YOU: (ApplicationOutcome.READY_FOR_YOU, JobStatus.READY_FOR_YOU),
}


class NotApprovedError(RuntimeError):
    """No applications row: the job was never approved. Never apply then."""


class ApplyRepository(Protocol):
    async def lock_applies(self) -> None: ...
    async def get_job(self, job_id: int) -> Job | None: ...
    async def get_application(self, job_id: int) -> Application | None: ...
    async def count_applied_since(self, dry_run: bool, since: datetime) -> int: ...
    async def save_apply_result(
        self,
        job_id: int,
        outcome: ApplicationOutcome,
        job_status: JobStatus,
        reason: str,
        dry_run: bool,
        artifacts_dir: str | None,
        company_site: CompanySite | None = None,
    ) -> None: ...
    async def mark_company_site_opened(self, job_id: int, url: str | None = None) -> None: ...
    async def get_company_site_click(self, job_id: int) -> tuple[datetime | None, str | None]: ...
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
        # Held until the result is committed, so check-cap-then-apply is
        # atomic across parallel activities.
        await self.repository.lock_applies()

        job = await self.repository.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        # 1. Approval is a DB fact, not a status that anything can overwrite.
        application = await self.repository.get_application(job_id)
        if application is None:
            raise NotApprovedError(f"Job {job_id} has no approval recorded; refusing to apply")

        # 2. Idempotency: never apply twice, whatever the mode.
        if application.applied_live:
            # jobs.status may have been rewritten (e.g. a re-run workflow): sync it back.
            await self.repository.update_status(job_id, JobStatus.APPLIED)
            return self._result(job_id, ApplyOutcome.ALREADY_APPLIED, "already applied")

        # 2b. Company site already checked: nothing for the browser to do.
        if application.outcome == ApplicationOutcome.READY_FOR_YOU:
            return self._result(job_id, ApplyOutcome.READY_FOR_YOU, application.reason)
        # Clicked before (by the worker or the inspector): Naukri now shows
        # "Applied" because of OUR click (issue #18), which must never be
        # recorded as an apply. Re-check the company page from its URL
        # instead, without Naukri.
        opened_at, company_url = await self.repository.get_company_site_click(job_id)
        if opened_at is not None and not company_url:
            return await self._finish(
                job_id,
                ApplyOutcome.NEEDS_MANUAL,
                f"company site was opened on {opened_at:%Y-%m-%d} (Naukri now shows Applied), "
                "but its URL is unknown: apply by hand, then run scripts.mark_applied",
            )

        # 3. Daily cap. Dry runs count only dry runs, so testing never
        # eats the real quota.
        now = self.clock()
        today = start_of_day(now)
        used = await self.repository.count_applied_since(self.dry_run, today)
        if used >= self.max_per_day:
            tomorrow = today + timedelta(days=1)
            return self._result(
                job_id,
                ApplyOutcome.SKIPPED_CAP,
                f"daily cap reached ({used}/{self.max_per_day})",
                retry_after_seconds=int((tomorrow - now).total_seconds()) + 1,
            )

        # 4. Answers are validated in dry_run too, so a dry run proves the file is good.
        try:
            answers = load_answers(self.answers_path)
        except (FileNotFoundError, yaml.YAMLError, ValidationError) as error:
            return await self._finish(job_id, ApplyOutcome.FAILED, f"bad answers file: {error}")

        # 5. Apply
        if self.dry_run:
            logger.info("apply_dry_run", job_id=job_id, url=job.url)
            reason = "dry run: nothing clicked"
            await self.repository.save_apply_result(
                job_id, ApplicationOutcome.APPLIED, JobStatus.APPLIED_DRY_RUN,
                reason, dry_run=True, artifacts_dir=None,
            )
            return self._result(job_id, ApplyOutcome.APPLIED, reason)

        # Job-level folder: known even if the browser crashes; each run
        # inside it has its own timestamped subfolder.
        artifacts_dir = str(ARTIFACTS_DIR / str(job_id))
        try:
            applied = await self.applier_factory().apply(
                job_id,
                job,
                answers,
                # Committed with the result below, even a FAILED one.
                on_company_site_click=lambda: self.repository.mark_company_site_opened(job_id),
                # Set: check this page directly, never Naukri's button again.
                company_site_url=company_url if opened_at is not None else None,
            )
        except Exception as error:
            # Recorded, not retried: a half-finished apply must be checked by a human.
            # Also covers an expired session (the reason says to log in again).
            logger.exception("apply_failed", job_id=job_id)
            return await self._finish(job_id, ApplyOutcome.FAILED, repr(error), artifacts_dir)

        if applied.company_site is not None:
            # Where Naukri's button led, for a re-check without Naukri later.
            await self.repository.mark_company_site_opened(job_id, applied.company_site.url)
        if applied.outcome == ApplyOutcome.APPLIED:
            await self.repository.save_apply_result(
                job_id, ApplicationOutcome.APPLIED, JobStatus.APPLIED,
                applied.reason, dry_run=False, artifacts_dir=artifacts_dir,
            )
            return self._result(job_id, applied.outcome, applied.reason)
        return await self._finish(
            job_id, applied.outcome, applied.reason, artifacts_dir, applied.company_site
        )

    async def _finish(
        self,
        job_id: int,
        outcome: ApplyOutcome,
        reason: str,
        artifacts_dir: str | None = None,
        company_site: CompanySite | None = None,
    ) -> ApplyResult:
        application_outcome, job_status = RESULT_FOR_OUTCOME[outcome]
        await self.repository.save_apply_result(
            job_id, application_outcome, job_status, reason,
            dry_run=self.dry_run, artifacts_dir=artifacts_dir, company_site=company_site,
        )
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

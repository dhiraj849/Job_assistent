"""ApplyService safety rails, with a fake repository and fake browser applier."""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from app.models.application import Application, ApplicationOutcome
from app.models.apply_result import ApplierResult, ApplyOutcome
from app.models.job import Job
from app.models.job_status import JobStatus
from app.services.apply_service import CAP_TIMEZONE, ApplyService, NotApprovedError

JOB_ID = 7
JOB = Job(title="Python Dev", company="Acme", location="Noida", description="", url="https://x/7")
# 22:00 IST: two hours before the cap resets.
NOW = datetime(2026, 10, 7, 22, 0, tzinfo=CAP_TIMEZONE)

VALID_ANSWERS = """
notice_period_days: 30
current_ctc_lpa: 10
expected_ctc_lpa: 14
current_location: Noida
willing_to_relocate: true
total_experience_years: 4
"""


APPROVED_AT = datetime(2026, 10, 7, 9, 0, tzinfo=CAP_TIMEZONE)


def approved() -> Application:
    return Application(outcome=ApplicationOutcome.PENDING, approved_at=APPROVED_AT)


def applied_live() -> Application:
    return Application(
        outcome=ApplicationOutcome.APPLIED, approved_at=APPROVED_AT, applied_at=APPROVED_AT
    )


class FakeRepository:
    """In-memory jobs.status + one applications row, with the DB's guard:
    a row applied live is never overwritten (like _NOT_APPLIED_LIVE)."""

    def __init__(
        self,
        application: Application | None = None,
        status: str = JobStatus.APPROVED,
        applied_today: int = 0,
    ):
        self.application = application if application is not None else approved()
        self.status = status
        self.applied_today = applied_today
        self.counted: list[bool] = []
        self.saves = 0
        self.locked = False

    async def lock_applies(self) -> None:
        self.locked = True

    async def get_job(self, job_id: int) -> Job | None:
        return JOB

    async def get_application(self, job_id: int) -> Application | None:
        return self.application

    async def count_applied_since(self, dry_run: bool, since: datetime) -> int:
        assert since == datetime(2026, 10, 7, tzinfo=CAP_TIMEZONE)
        self.counted.append(dry_run)
        return self.applied_today

    async def save_apply_result(self, job_id, outcome, job_status, reason, dry_run, artifacts_dir):
        if self.application is None or self.application.applied_live:
            raise ApplicationNotWritableError("refused")
        # Both "tables" change together, like the single commit in the real repo.
        self.application = self.application.model_copy(update=dict(
            outcome=outcome,
            reason=reason,
            dry_run=dry_run,
            applied_at=NOW if outcome == ApplicationOutcome.APPLIED else None,
            artifacts_dir=artifacts_dir,
        ))
        self.status = job_status
        self.saves += 1

    async def update_status(self, job_id: int, status: JobStatus) -> None:
        self.status = status


class FakeApplier:
    def __init__(
        self,
        outcome: ApplyOutcome = ApplyOutcome.APPLIED,
        error: Exception | None = None,
        reason: str = "",
    ):
        self.outcome = outcome
        self.error = error
        self.reason = reason
        self.calls = 0

    async def apply(self, job_id, job, answers) -> ApplierResult:
        self.calls += 1
        if self.error:
            raise self.error
        return ApplierResult(outcome=self.outcome, reason=self.reason)


@pytest.fixture
def answers_path(tmp_path: Path) -> Path:
    path = tmp_path / "answers.yaml"
    path.write_text(VALID_ANSWERS)
    return path


def run(repo, answers_path, mode="live", applier=None, max_per_day=10):
    built: list[FakeApplier] = []
    applier = applier or FakeApplier()

    def factory():
        built.append(applier)
        return applier

    service = ApplyService(
        repository=repo,
        mode=mode,
        max_per_day=max_per_day,
        answers_path=answers_path,
        applier_factory=factory,
        clock=lambda: NOW,
    )
    return asyncio.run(service.apply(JOB_ID)), built


def test_live_apply_marks_job_applied(answers_path):
    repo = FakeRepository()
    result, built = run(repo, answers_path)

    assert result.outcome == ApplyOutcome.APPLIED
    assert not result.dry_run
    assert repo.status == JobStatus.APPLIED
    assert repo.application.applied_live
    assert repo.application.artifacts_dir == "artifacts/apply/7"
    assert repo.locked
    assert built[0].calls == 1


def test_cap_hit_does_not_apply(answers_path):
    repo = FakeRepository(applied_today=10)
    result, built = run(repo, answers_path, max_per_day=10)

    assert result.outcome == ApplyOutcome.SKIPPED_CAP
    assert result.retry_after_seconds == 2 * 3600 + 1  # until IST midnight
    assert built == []
    assert repo.status == JobStatus.APPROVED
    assert repo.application.outcome == ApplicationOutcome.PENDING


def test_dry_run_never_builds_the_browser(answers_path):
    repo = FakeRepository()
    result, built = run(repo, answers_path, mode="dry_run")

    assert result.outcome == ApplyOutcome.APPLIED
    assert result.dry_run
    assert built == []
    assert repo.status == JobStatus.APPLIED_DRY_RUN


def test_dry_run_cap_counts_only_dry_runs(answers_path):
    repo = FakeRepository()
    run(repo, answers_path, mode="dry_run")

    assert repo.counted == [True]


def test_live_cap_counts_only_live_applies(answers_path):
    repo = FakeRepository()
    run(repo, answers_path)

    assert repo.counted == [False]


def test_already_applied_job_is_skipped(answers_path):
    repo = FakeRepository(application=applied_live(), status=JobStatus.APPLIED)
    result, built = run(repo, answers_path)

    assert result.outcome == ApplyOutcome.ALREADY_APPLIED
    assert built == []
    assert repo.counted == []  # skipped before even checking the cap
    assert repo.saves == 0


def test_idempotency_survives_status_overwritten_to_approved(answers_path):
    """Regression: the workflow writes jobs.status=approved before apply_job.
    That used to wipe 'applied' and the job was applied a second time."""
    repo = FakeRepository(application=applied_live(), status=JobStatus.APPROVED)
    result, built = run(repo, answers_path)

    assert result.outcome == ApplyOutcome.ALREADY_APPLIED
    assert built == []
    assert repo.status == JobStatus.APPLIED  # synced back


def test_dry_run_applied_does_not_block_live_apply(answers_path):
    dry = applied_live().model_copy(update=dict(dry_run=True))
    repo = FakeRepository(application=dry)
    result, built = run(repo, answers_path)

    assert result.outcome == ApplyOutcome.APPLIED
    assert built[0].calls == 1
    assert repo.application.applied_live


def test_job_without_approval_is_refused(answers_path):
    repo = FakeRepository()
    repo.application = None
    with pytest.raises(NotApprovedError):
        run(repo, answers_path)


def test_invalid_answers_fail_without_browser(tmp_path):
    path = tmp_path / "answers.yaml"
    path.write_text(VALID_ANSWERS.replace("expected_ctc_lpa: 14", "expected_ctc_lpa: 5"))
    repo = FakeRepository()
    result, built = run(repo, path)

    assert result.outcome == ApplyOutcome.FAILED
    assert "answers" in result.reason
    assert built == []
    assert repo.status == JobStatus.FAILED


def test_missing_answers_file_fails(tmp_path):
    result, _ = run(FakeRepository(), tmp_path / "nope.yaml", mode="dry_run")

    assert result.outcome == ApplyOutcome.FAILED


def test_company_site_job_needs_manual(answers_path):
    repo = FakeRepository()
    result, _ = run(repo, answers_path, applier=FakeApplier(ApplyOutcome.NEEDS_MANUAL))

    assert result.outcome == ApplyOutcome.NEEDS_MANUAL
    assert repo.status == JobStatus.NEEDS_MANUAL


def test_browser_error_is_recorded_as_failed(answers_path):
    repo = FakeRepository()
    result, _ = run(repo, answers_path, applier=FakeApplier(error=RuntimeError("boom")))

    assert result.outcome == ApplyOutcome.FAILED
    assert "boom" in result.reason
    assert repo.status == JobStatus.FAILED


def test_naukri_already_applied_syncs_status(answers_path):
    repo = FakeRepository()
    result, _ = run(repo, answers_path, applier=FakeApplier(ApplyOutcome.ALREADY_APPLIED))

    assert result.outcome == ApplyOutcome.ALREADY_APPLIED
    assert repo.status == JobStatus.APPLIED


def test_unknown_question_reason_reaches_the_result(answers_path):
    repo = FakeRepository()
    applier = FakeApplier(ApplyOutcome.NEEDS_MANUAL, reason="unknown question: 'Why us?'")
    result, _ = run(repo, answers_path, applier=applier)

    assert result.outcome == ApplyOutcome.NEEDS_MANUAL
    assert "Why us?" in result.reason
    assert repo.status == JobStatus.NEEDS_MANUAL
    # The reason is stored, so list_pending can show it later.
    assert repo.application.outcome == ApplicationOutcome.NEEDS_MANUAL
    assert "Why us?" in repo.application.reason

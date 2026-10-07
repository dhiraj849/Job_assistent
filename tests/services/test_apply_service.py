"""ApplyService safety rails, with a fake repository and fake browser applier."""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from app.models.apply_result import ApplierResult, ApplyOutcome
from app.models.job import Job
from app.models.job_status import JobStatus
from app.services.apply_service import CAP_TIMEZONE, ApplyService

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


class FakeRepository:
    def __init__(self, status: str = JobStatus.APPROVED, applied_today: int = 0):
        self.status = status
        self.applied_today = applied_today
        self.counted: list[JobStatus] = []
        self.locked = False

    async def lock_applies(self) -> None:
        self.locked = True

    async def get_job(self, job_id: int) -> Job | None:
        return JOB

    async def get_status(self, job_id: int) -> str | None:
        return self.status

    async def count_status_since(self, status: JobStatus, since: datetime) -> int:
        assert since == datetime(2026, 10, 7, tzinfo=CAP_TIMEZONE)
        self.counted.append(status)
        return self.applied_today

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
    assert repo.locked
    assert built[0].calls == 1


def test_cap_hit_does_not_apply(answers_path):
    repo = FakeRepository(applied_today=10)
    result, built = run(repo, answers_path, max_per_day=10)

    assert result.outcome == ApplyOutcome.SKIPPED_CAP
    assert result.retry_after_seconds == 2 * 3600 + 1  # until IST midnight
    assert built == []
    assert repo.status == JobStatus.APPROVED


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

    assert repo.counted == [JobStatus.APPLIED_DRY_RUN]


def test_already_applied_job_is_skipped(answers_path):
    repo = FakeRepository(status=JobStatus.APPLIED)
    result, built = run(repo, answers_path)

    assert result.outcome == ApplyOutcome.ALREADY_APPLIED
    assert built == []
    assert repo.counted == []  # skipped before even checking the cap


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

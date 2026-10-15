from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class ApplyOutcome(StrEnum):
    APPLIED = "applied"
    NEEDS_MANUAL = "needs_manual"
    FAILED = "failed"
    SKIPPED_CAP = "skipped_cap"
    ALREADY_APPLIED = "already_applied"
    # Company-site job: form found and checked, waiting for me to run
    # scripts/apply_company_site.py (fill, CAPTCHA/OTP, Submit by me).
    READY_FOR_YOU = "ready_for_you"


class ApplyResult(BaseModel):
    """What the apply_job activity did. Returned to the workflow (stored in history)."""

    outcome: ApplyOutcome
    dry_run: bool
    reason: str = ""
    # Only for SKIPPED_CAP: seconds until the daily cap resets. Computed in the
    # activity so the workflow can sleep on it and stay deterministic.
    retry_after_seconds: int | None = None


class CompanySite(BaseModel):
    """What the applier learned about a company career site."""

    # The page (or ATS iframe) that holds the form; the fill session opens it directly.
    url: str
    portal: str
    # Steps only a human can do, seen on the page: "captcha", "otp". A hint,
    # not a promise: an OTP may only appear after the email is typed.
    human_steps: list[str] = []


class ApplierResult(BaseModel):
    """What the browser applier saw. The reason tells a human what to do next
    (e.g. the text of a question it could not answer)."""

    outcome: Literal[
        ApplyOutcome.APPLIED,
        ApplyOutcome.NEEDS_MANUAL,
        ApplyOutcome.ALREADY_APPLIED,
        ApplyOutcome.READY_FOR_YOU,
    ]
    reason: str = ""
    # Set once "Apply on company site" was clicked and the site was read.
    company_site: CompanySite | None = None

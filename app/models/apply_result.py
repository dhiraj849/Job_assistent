from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class ApplyOutcome(StrEnum):
    APPLIED = "applied"
    NEEDS_MANUAL = "needs_manual"
    FAILED = "failed"
    SKIPPED_CAP = "skipped_cap"
    ALREADY_APPLIED = "already_applied"


class ApplyResult(BaseModel):
    """What the apply_job activity did. Returned to the workflow (stored in history)."""

    outcome: ApplyOutcome
    dry_run: bool
    reason: str = ""
    # Only for SKIPPED_CAP: seconds until the daily cap resets. Computed in the
    # activity so the workflow can sleep on it and stay deterministic.
    retry_after_seconds: int | None = None


class ApplierResult(BaseModel):
    """What the browser applier saw. The reason tells a human what to do next
    (e.g. the text of a question it could not answer)."""

    outcome: Literal[ApplyOutcome.APPLIED, ApplyOutcome.NEEDS_MANUAL, ApplyOutcome.ALREADY_APPLIED]
    reason: str = ""

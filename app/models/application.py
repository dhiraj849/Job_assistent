from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class ApplicationOutcome(StrEnum):
    """State of one row in the applications table (CHECK-constrained in the DB)."""

    # Approved by me, not applied yet (or waiting for the daily cap).
    PENDING = "pending"
    APPLIED = "applied"
    NEEDS_MANUAL = "needs_manual"
    FAILED = "failed"
    # Approved, but the daily cap stayed full for MAX_CAP_WAIT_DAYS: never
    # tried. Not "pending" any more (no workflow will apply it), so lists
    # and stats do not mistake it for a job still in the queue.
    EXPIRED = "expired"
    # Company-site form found and checked; I fill and submit it with
    # scripts/apply_company_site.py.
    READY_FOR_YOU = "ready_for_you"


class Application(BaseModel):
    """One applications row, as services see it."""

    outcome: ApplicationOutcome
    reason: str = ""
    dry_run: bool = False
    approved_at: datetime
    approval_note: str = ""
    applied_at: datetime | None = None
    artifacts_dir: str | None = None
    # Company-site jobs only.
    external_url: str | None = None
    portal: str | None = None
    human_steps: list[str] = []

    @property
    def applied_live(self) -> bool:
        # A dry-run "applied" must never block the real apply later.
        return self.outcome == ApplicationOutcome.APPLIED and not self.dry_run

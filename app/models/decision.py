from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class Decision(StrEnum):
    """What happened at the approval step (CHECK-constrained in job_decisions)."""

    APPROVED = "approved"
    REJECTED = "rejected"
    # Nobody answered within the approval timeout.
    EXPIRED = "expired"


class JobDecision(BaseModel):
    """One job_decisions row, as services see it."""

    decision: Decision
    note: str = ""
    decided_at: datetime
    workflow_run_id: str

from enum import StrEnum


class JobStatus(StrEnum):
    """Lifecycle of one job. Stored as plain text in jobs.status.

    StrEnum so values compare equal to the strings in the database.
    """

    DISCOVERED = "discovered"
    FILTERED_OUT = "filtered_out"
    SHORTLISTED = "shortlisted"
    MATCHED = "matched"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    APPLIED_DRY_RUN = "applied_dry_run"
    FAILED = "failed"

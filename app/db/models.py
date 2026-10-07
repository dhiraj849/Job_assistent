from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.application import ApplicationOutcome
from app.models.decision import Decision
from app.models.job_status import JobStatus


class JobRecord(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)

    source: Mapped[str] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(String(1000), unique=True)

    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300))
    experience: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    skills: Mapped[list[str]] = mapped_column(JSONB, default=list)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Plain string (not a DB enum) so adding a status needs no migration.
    status: Mapped[str] = mapped_column(
        String(30), index=True, server_default=JobStatus.DISCOVERED.value
    )
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JobMatchRecord(Base):
    __tablename__ = "job_matches"

    id: Mapped[int] = mapped_column(primary_key=True)

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)

    role_match: Mapped[int]
    skill_match: Mapped[int]
    experience_match: Mapped[int]
    overall_score: Mapped[int]
    match_level: Mapped[str] = mapped_column(String(20))

    matching_skills: Mapped[list[str]] = mapped_column(JSONB, default=list)
    missing_skills: Mapped[list[str]] = mapped_column(JSONB, default=list)
    strengths: Mapped[list[str]] = mapped_column(JSONB, default=list)
    concerns: Mapped[list[str]] = mapped_column(JSONB, default=list)
    recommendation: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


_OUTCOMES = ", ".join(f"'{outcome.value}'" for outcome in ApplicationOutcome)


class ApplicationRecord(Base):
    """One approved job and what happened when we applied (audit + idempotency).

    A row exists only after my approval, so approved_at is NOT NULL.
    """

    __tablename__ = "applications"
    # The rules live in the DB too, so a buggy script or a raw SQL fix
    # cannot write an impossible row.
    __table_args__ = (
        CheckConstraint(f"outcome IN ({_OUTCOMES})", name="ck_applications_outcome"),
        CheckConstraint(
            "(outcome = 'applied') = (applied_at IS NOT NULL)",
            name="ck_applications_applied_at",
        ),
        # A human must be able to see what to do next.
        CheckConstraint(
            "outcome NOT IN ('needs_manual', 'failed') OR reason <> ''",
            name="ck_applications_reason",
        ),
        CheckConstraint("applied_at >= approved_at", name="ck_applications_applied_after_approval"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # UNIQUE: one application per job, like the workflow id job-{id}.
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)

    outcome: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text, server_default="")
    dry_run: Mapped[bool] = mapped_column(Boolean, server_default="false")

    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approval_note: Mapped[str] = mapped_column(Text, server_default="")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifacts_dir: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


_DECISIONS = ", ".join(f"'{decision.value}'" for decision in Decision)


class JobDecisionRecord(Base):
    """Append-only log of my decisions at the approval step (audit).

    Separate from applications on purpose: an applications row means
    "approved", so a rejected row there would pass ApplyService's approval
    check. Many rows per job are fine (reject now, re-run and approve later).
    """

    __tablename__ = "job_decisions"
    __table_args__ = (
        CheckConstraint(f"decision IN ({_DECISIONS})", name="ck_job_decisions_decision"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    decision: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, server_default="")
    # From workflow.now(): when I decided (or when the timeout fired).
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # UNIQUE: one decision per workflow run, so a retried activity
    # cannot write it twice (idempotency key). Also links to the Temporal UI.
    workflow_run_id: Mapped[str] = mapped_column(String(64), unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

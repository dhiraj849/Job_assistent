"""add company site apply columns

Revision ID: ff13a6004feb
Revises: a7664589ce5e
Create Date: 2026-10-15 12:01:34.598432

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Copied literally on purpose (like a7664589ce5e): a migration must not
# change if ApplicationOutcome changes later.
OLD_OUTCOMES = "'pending', 'applied', 'needs_manual', 'failed', 'expired'"
NEW_OUTCOMES = "'pending', 'applied', 'needs_manual', 'failed', 'expired', 'ready_for_you'"
OLD_REASON = "outcome NOT IN ('needs_manual', 'failed') OR reason <> ''"
NEW_REASON = "outcome NOT IN ('needs_manual', 'failed', 'ready_for_you') OR reason <> ''"


# revision identifiers, used by Alembic.
revision: str = 'ff13a6004feb'
down_revision: Union[str, Sequence[str], None] = 'a7664589ce5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Company-site apply: the new outcome ready_for_you, where the form is
    (applications.external_url, portal), what a human must do there
    (human_steps), and on the JOB when anyone of ours (worker or inspector,
    approved or not) clicked Naukri's company button and where it led
    (jobs.company_site_opened_at, company_site_url). Naukri shows such a
    job as "Applied" from then on (known issue #18).
    No backfill here; jobs clicked by the inspector before this were
    backfilled once by hand (see docs/12, issue #18).
    """
    op.add_column("applications", sa.Column("external_url", sa.Text(), nullable=True))
    op.add_column("applications", sa.Column("portal", sa.String(length=30), nullable=True))
    op.add_column(
        "applications",
        sa.Column("human_steps", sa.String(length=100), server_default="", nullable=False),
    )
    op.add_column(
        "jobs", sa.Column("company_site_opened_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("jobs", sa.Column("company_site_url", sa.Text(), nullable=True))

    op.drop_constraint("ck_applications_outcome", "applications", type_="check")
    op.create_check_constraint(
        "ck_applications_outcome", "applications", f"outcome IN ({NEW_OUTCOMES})"
    )
    op.drop_constraint("ck_applications_reason", "applications", type_="check")
    op.create_check_constraint("ck_applications_reason", "applications", NEW_REASON)
    op.create_check_constraint(
        "ck_applications_ready_has_url",
        "applications",
        "outcome <> 'ready_for_you' OR external_url IS NOT NULL",
    )


def downgrade() -> None:
    """Downgrade schema.

    ready_for_you rows become needs_manual first (a human must finish them,
    which is what the old code said), keeping the URL in the reason.
    """
    op.execute(
        "UPDATE applications SET outcome = 'needs_manual', "
        "reason = reason || ' (apply at ' || external_url || ')' "
        "WHERE outcome = 'ready_for_you'"
    )
    op.drop_constraint("ck_applications_ready_has_url", "applications", type_="check")
    op.drop_constraint("ck_applications_reason", "applications", type_="check")
    op.create_check_constraint("ck_applications_reason", "applications", OLD_REASON)
    op.drop_constraint("ck_applications_outcome", "applications", type_="check")
    op.create_check_constraint(
        "ck_applications_outcome", "applications", f"outcome IN ({OLD_OUTCOMES})"
    )
    op.drop_column("jobs", "company_site_url")
    op.drop_column("jobs", "company_site_opened_at")
    op.drop_column("applications", "human_steps")
    op.drop_column("applications", "portal")
    op.drop_column("applications", "external_url")

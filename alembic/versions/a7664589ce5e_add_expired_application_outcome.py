"""add expired application outcome

Revision ID: a7664589ce5e
Revises: b50143f8cf9c
Create Date: 2026-10-08 16:18:53.855730

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Copied literally on purpose (like f734e9e72583): a migration must not
# change if ApplicationOutcome changes later.
OLD_OUTCOMES = "'pending', 'applied', 'needs_manual', 'failed'"
NEW_OUTCOMES = "'pending', 'applied', 'needs_manual', 'failed', 'expired'"

# revision identifiers, used by Alembic.
revision: str = 'a7664589ce5e'
down_revision: Union[str, Sequence[str], None] = 'b50143f8cf9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Only widens ck_applications_outcome. No backfill: there were 0
    pending rows on expired jobs when this shipped. ck_applications_reason
    stays as is (expired rows carry a reason, but the DB does not force it).
    """
    op.drop_constraint("ck_applications_outcome", "applications", type_="check")
    op.create_check_constraint(
        "ck_applications_outcome", "applications", f"outcome IN ({NEW_OUTCOMES})"
    )


def downgrade() -> None:
    """Downgrade schema.

    expired rows go back to pending first (what the old code left behind),
    otherwise the narrower constraint cannot be created.
    """
    op.execute("UPDATE applications SET outcome = 'pending' WHERE outcome = 'expired'")
    op.drop_constraint("ck_applications_outcome", "applications", type_="check")
    op.create_check_constraint(
        "ck_applications_outcome", "applications", f"outcome IN ({OLD_OUTCOMES})"
    )

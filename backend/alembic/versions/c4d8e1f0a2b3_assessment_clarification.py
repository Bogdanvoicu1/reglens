"""assessment clarification column

Revision ID: c4d8e1f0a2b3
Revises: beb07ed3064a
Create Date: 2026-06-13 10:00:00.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c4d8e1f0a2b3"
down_revision = "beb07ed3064a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assessments",
        sa.Column("clarification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assessments", "clarification")

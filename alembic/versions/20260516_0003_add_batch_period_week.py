"""Add period_week column to accounting_batch.

Revision ID: 20260516_0003
Revises: 20260516_0002
Create Date: 2026-05-16 14:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260516_0003"
down_revision = "20260516_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounting_batch", sa.Column("period_week", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounting_batch", "period_week")

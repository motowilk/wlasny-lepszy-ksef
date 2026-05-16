"""add last_tick_at to worker_heartbeat

Revision ID: 20260516_0004
Revises: 20260516_0003
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = "20260516_0004"
down_revision = "20260516_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "worker_heartbeat",
        sa.Column("last_tick_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("worker_heartbeat", "last_tick_at")

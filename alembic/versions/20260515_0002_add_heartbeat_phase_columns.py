"""Add phase and current_jobs_json columns to worker_heartbeat.

Revision ID: 20260515_0002
Revises: 20260515_0001
Create Date: 2026-05-15 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260515_0002"
down_revision = "20260515_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("worker_heartbeat")]

    if "phase" not in columns:
        op.add_column("worker_heartbeat", sa.Column("phase", sa.String(20), nullable=True))
    if "current_jobs_json" not in columns:
        op.add_column("worker_heartbeat", sa.Column("current_jobs_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("worker_heartbeat", "current_jobs_json")
    op.drop_column("worker_heartbeat", "phase")

"""Create worker_heartbeat table.

Revision ID: 20260514_0003
Revises: 20260514_0002
Create Date: 2026-05-14 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260514_0003"
down_revision = "20260514_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "worker_heartbeat" not in existing_tables:
        op.create_table(
            "worker_heartbeat",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("worker_id", sa.String(100), nullable=False),
            sa.Column("last_heartbeat_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("current_job_id", sa.Integer(), nullable=True),
            sa.Column("current_job_type", sa.String(100), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("worker_id", name="uq_worker_heartbeat_worker_id"),
            sa.ForeignKeyConstraint(
                ["current_job_id"],
                ["integration_job.id"],
                ondelete="SET NULL",
            ),
        )
        op.create_index(
            "idx_worker_heartbeat_worker_id",
            "worker_heartbeat",
            ["worker_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "worker_heartbeat" in inspector.get_table_names():
        op.drop_index("idx_worker_heartbeat_worker_id", table_name="worker_heartbeat")
        op.drop_table("worker_heartbeat")

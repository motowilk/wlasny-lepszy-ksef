"""Create notification_log table and add totp_secret to app_user.

Revision ID: 20260514_0002
Revises: 20260514_0001
Create Date: 2026-05-14 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260514_0002"
down_revision = "20260514_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # Create notification_log if it doesn't already exist.
    if "notification_log" not in existing_tables:
        op.create_table(
            "notification_log",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("notification_uuid", sa.String(36), nullable=False),
            sa.Column("invoice_id", sa.Integer(), nullable=True),
            sa.Column("batch_id", sa.Integer(), nullable=True),
            sa.Column("channel", sa.String(50), nullable=False),
            sa.Column("recipient", sa.String(255), nullable=False),
            sa.Column("subject", sa.String(500), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(50), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("notification_uuid"),
            sa.ForeignKeyConstraint(["invoice_id"], ["invoice.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["batch_id"], ["accounting_batch.id"], ondelete="SET NULL"),
        )

    # Add totp_secret to app_user if it doesn't already exist.
    existing_cols = {c["name"] for c in inspector.get_columns("app_user")}
    if "totp_secret" not in existing_cols:
        op.add_column(
            "app_user",
            sa.Column("totp_secret", sa.String(64), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_cols = {c["name"] for c in inspector.get_columns("app_user")}
    if "totp_secret" in existing_cols:
        op.drop_column("app_user", "totp_secret")

    existing_tables = inspector.get_table_names()
    if "notification_log" in existing_tables:
        op.drop_table("notification_log")

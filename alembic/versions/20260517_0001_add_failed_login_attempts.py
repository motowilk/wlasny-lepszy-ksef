"""Add failed login attempts to app_user.

Revision ID: 20260517_0001
Revises: 20260516_0004
Create Date: 2026-05-17 00:00:01
"""

from alembic import op
import sqlalchemy as sa

revision = "20260517_0001"
down_revision = "20260516_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("app_user")}

    if "failed_login_attempts" not in existing_cols:
        op.add_column(
            "app_user",
            sa.Column(
                "failed_login_attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("app_user")}

    if "failed_login_attempts" in existing_cols:
        op.drop_column("app_user", "failed_login_attempts")
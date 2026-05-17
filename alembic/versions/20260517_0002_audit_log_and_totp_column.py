"""Add admin_audit_log table and widen totp_secret column.

Revision ID: 20260517_0002
Revises: 20260517_0001
Create Date: 2026-05-17 00:00:02
"""

from alembic import op
import sqlalchemy as sa

revision = "20260517_0002"
down_revision = "20260517_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # ── admin_audit_log ────────────────────────────────────────────────────
    if "admin_audit_log" not in existing_tables:
        op.create_table(
            "admin_audit_log",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("actor_user_id", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(100), nullable=False),
            sa.Column("target_type", sa.String(50), nullable=True),
            sa.Column("target_id", sa.Integer(), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
        )
        op.create_index("ix_audit_actor", "admin_audit_log", ["actor_user_id"])
        op.create_index("ix_audit_action", "admin_audit_log", ["action"])

    # ── Widen totp_secret from String(64) to String(255) for encrypted values ─
    existing_cols = {c["name"]: c for c in inspector.get_columns("app_user")}
    if "totp_secret" in existing_cols:
        col_type = existing_cols["totp_secret"].get("type")
        # Only alter if currently shorter than 255
        if hasattr(col_type, "length") and (col_type.length or 0) < 255:
            op.alter_column(
                "app_user",
                "totp_secret",
                existing_type=sa.String(64),
                type_=sa.String(255),
                existing_nullable=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "admin_audit_log" in existing_tables:
        op.drop_table("admin_audit_log")

    existing_cols = {c["name"] for c in inspector.get_columns("app_user")}
    if "totp_secret" in existing_cols:
        op.alter_column(
            "app_user",
            "totp_secret",
            existing_type=sa.String(255),
            type_=sa.String(64),
            existing_nullable=True,
        )

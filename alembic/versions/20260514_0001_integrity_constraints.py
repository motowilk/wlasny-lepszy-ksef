"""Add invoice and batch integrity constraints.

Revision ID: 20260514_0001
Revises: 
Create Date: 2026-05-14 00:00:00
"""

from alembic import context, op
import sqlalchemy as sa


revision = "20260514_0001"
down_revision = None
branch_labels = None
depends_on = None


INVOICE_PARTY_FK = "fk_invoice_party_party_id_party"
INVOICE_BATCH_FK = "fk_invoice_accounting_batch_id_accounting_batch"
BATCH_INVOICE_UNIQUE = "uq_accounting_batch_invoice_invoice_id"


def _drop_fk_by_columns(table_name: str, constrained_columns: list[str], referred_table: str) -> None:
    if context.is_offline_mode():
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for fk in inspector.get_foreign_keys(table_name):
        if fk.get("referred_table") != referred_table:
            continue
        if fk.get("constrained_columns") != constrained_columns:
            continue
        name = fk.get("name")
        if name:
            op.drop_constraint(name, table_name, type_="foreignkey")
        break


def upgrade() -> None:
    _drop_fk_by_columns("invoice_party", ["party_id"], "party")
    op.create_foreign_key(
        INVOICE_PARTY_FK,
        "invoice_party",
        "party",
        ["party_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_foreign_key(
        INVOICE_BATCH_FK,
        "invoice",
        "accounting_batch",
        ["accounting_batch_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_unique_constraint(
        BATCH_INVOICE_UNIQUE,
        "accounting_batch_invoice",
        ["invoice_id"],
    )


def downgrade() -> None:
    op.drop_constraint(BATCH_INVOICE_UNIQUE, "accounting_batch_invoice", type_="unique")
    op.drop_constraint(INVOICE_BATCH_FK, "invoice", type_="foreignkey")
    op.drop_constraint(INVOICE_PARTY_FK, "invoice_party", type_="foreignkey")
    op.create_foreign_key(
        INVOICE_PARTY_FK,
        "invoice_party",
        "party",
        ["party_id"],
        ["id"],
    )

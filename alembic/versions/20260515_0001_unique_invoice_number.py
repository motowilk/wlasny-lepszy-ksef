"""Add unique constraint on invoice.invoice_number

Revision ID: 20260515_0001
Revises: 20260514_0003
Create Date: 2026-05-15
"""
from alembic import op

revision = "20260515_0001"
down_revision = "20260514_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_invoice_invoice_number", "invoice", ["invoice_number"])


def downgrade() -> None:
    op.drop_constraint("uq_invoice_invoice_number", "invoice", type_="unique")

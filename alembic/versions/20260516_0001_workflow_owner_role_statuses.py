"""Refactor workflow: rename accountant role to owner, update accounting_status values.

Revision ID: 20260516_0001
Revises: 20260515_0002
Create Date: 2026-05-16 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20260516_0001"
down_revision = "20260515_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Rename role: accountant → owner
    bind.execute(
        sa.text(
            "UPDATE app_role SET role_code = 'owner', role_name = 'Właściciel/Operator', "
            "description = 'Wystawianie faktur, kwalifikacja zakupów, zarządzanie batchami do biura księgowego' "
            "WHERE role_code = 'accountant'"
        )
    )

    # 2. Migrate accounting_status values
    bind.execute(
        sa.text("UPDATE invoice SET accounting_status = 'qualified' WHERE accounting_status = 'verified'")
    )
    bind.execute(
        sa.text("UPDATE invoice SET accounting_status = 'batched' WHERE accounting_status = 'posted'")
    )
    bind.execute(
        sa.text("UPDATE invoice SET accounting_status = 'sent_to_office' WHERE accounting_status = 'booked'")
    )
    bind.execute(
        sa.text("UPDATE invoice SET accounting_status = 'rejected' WHERE accounting_status = 'cancelled'")
    )

    # 3. Update erp_status: COMPLETED → SENT_TO_OFFICE
    bind.execute(
        sa.text("UPDATE invoice SET erp_status = 'SENT_TO_OFFICE' WHERE erp_status = 'COMPLETED'")
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Revert erp_status
    bind.execute(
        sa.text("UPDATE invoice SET erp_status = 'COMPLETED' WHERE erp_status = 'SENT_TO_OFFICE'")
    )

    # Revert accounting_status values
    bind.execute(
        sa.text("UPDATE invoice SET accounting_status = 'verified' WHERE accounting_status = 'qualified'")
    )
    bind.execute(
        sa.text("UPDATE invoice SET accounting_status = 'posted' WHERE accounting_status = 'batched'")
    )
    bind.execute(
        sa.text("UPDATE invoice SET accounting_status = 'booked' WHERE accounting_status = 'sent_to_office'")
    )
    bind.execute(
        sa.text("UPDATE invoice SET accounting_status = 'cancelled' WHERE accounting_status = 'rejected'")
    )

    # Revert role rename
    bind.execute(
        sa.text(
            "UPDATE app_role SET role_code = 'accountant', role_name = 'Księgowy', "
            "description = 'Operacje księgowe i statusy księgowe' "
            "WHERE role_code = 'owner'"
        )
    )

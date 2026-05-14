from app.db.models.accounting_batch import AccountingBatchInvoice
from app.db.models.invoice import Invoice
from app.db.models.invoice_party import InvoiceParty


def test_invoice_accounting_batch_id_has_foreign_key() -> None:
    foreign_keys = list(Invoice.__table__.c.accounting_batch_id.foreign_keys)

    assert len(foreign_keys) == 1
    assert foreign_keys[0].target_fullname == "accounting_batch.batch_code"
    assert foreign_keys[0].ondelete == "SET NULL"


def test_invoice_party_party_id_cascades_delete() -> None:
    foreign_keys = list(InvoiceParty.__table__.c.party_id.foreign_keys)

    assert len(foreign_keys) == 1
    assert foreign_keys[0].target_fullname == "party.id"
    assert foreign_keys[0].ondelete == "CASCADE"


def test_accounting_batch_invoice_enforces_one_batch_per_invoice() -> None:
    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in AccountingBatchInvoice.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert unique_constraints["uq_accounting_batch_invoice_invoice_id"] == ("invoice_id",)

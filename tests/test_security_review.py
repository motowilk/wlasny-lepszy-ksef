from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.security import HTTPBasicCredentials
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.api.dependencies.auth as auth_module
import app.core.security as security_module
from app.core.config import settings
from app.db.base import Base
from app.db.models import (
    AccountingBatchInvoice,
    AppUser,
    DictInvoiceDirection,
    DictInvoiceKind,
    DictKsefStatus,
    IntegrationJob,
    Invoice,
)
from app.services.accounting_service import AccountingService
from app.ui.routes import UIAuthRequired, _resolve_ui_user


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def unique(self):
        return self

    def scalar_one_or_none(self):
        return self._value


class _FakeDbSession:
    def __init__(self, user):
        self.user = user
        self.commit_calls = 0

    def execute(self, stmt):
        return _FakeScalarResult(self.user)

    def commit(self):
        self.commit_calls += 1


def test_ui_session_token_expires_and_is_invalidated_by_nonce_rotation(monkeypatch) -> None:
    issued_at = 1_700_000_000
    monkeypatch.setattr(security_module.time, "time", lambda: issued_at)

    user = AppUser(
        id=7,
        user_uuid="user-7",
        username="tester",
        email="tester@example.com",
        display_name="Tester",
        password_hash="hash",
        auth_provider="LOCAL",
        is_active=True,
        is_locked=False,
        metadata_json={"ui_session_nonce": "nonce-a"},
    )
    user.roles = []
    db = _FakeDbSession(user)

    token = security_module.create_ui_session_token(
        user.id,
        settings.secret_key,
        "nonce-a",
        max_age=60,
    )

    decoded = security_module.decode_ui_session_token(token, settings.secret_key)
    assert decoded is not None
    assert decoded["user_id"] == user.id
    assert decoded["session_nonce"] == "nonce-a"

    assert _resolve_ui_user(db, token) is user

    user.metadata_json = {"ui_session_nonce": "nonce-b"}
    with pytest.raises(UIAuthRequired):
        _resolve_ui_user(db, token)

    monkeypatch.setattr(security_module.time, "time", lambda: issued_at + 61)
    assert security_module.decode_ui_session_token(token, settings.secret_key) is None


def test_api_authentication_does_not_commit_on_success(monkeypatch) -> None:
    user = SimpleNamespace(
        id=1,
        username="reviewer",
        password_hash="hashed",
        is_active=True,
        is_locked=False,
        roles=[],
    )
    db = _FakeDbSession(user)

    monkeypatch.setattr(auth_module, "verify_password", lambda plain, hashed: True)

    result = auth_module.get_current_user(
        credentials=HTTPBasicCredentials(username=" Reviewer ", password="secret"),
        db=db,
    )

    assert result is user
    assert db.commit_calls == 0


def test_generate_monthly_purchase_batch_filters_by_issue_month() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                DictInvoiceDirection(code="PURCHASE", name="Purchase"),
                DictInvoiceDirection(code="SALE", name="Sale"),
                DictInvoiceKind(code="VAT", name="VAT"),
                DictKsefStatus(code="DRAFT", name="Draft"),
            ]
        )
        db.commit()

        may_purchase = Invoice(
            invoice_uuid="inv-may",
            direction_code="PURCHASE",
            invoice_kind_code="VAT",
            invoice_number="FV/05/2026/1",
            issue_date=date(2026, 5, 10),
            ksef_status_code="DRAFT",
            accounting_qualified=True,
        )
        june_purchase = Invoice(
            invoice_uuid="inv-june",
            direction_code="PURCHASE",
            invoice_kind_code="VAT",
            invoice_number="FV/06/2026/1",
            issue_date=date(2026, 6, 10),
            ksef_status_code="DRAFT",
            accounting_qualified=True,
        )
        may_sale = Invoice(
            invoice_uuid="inv-sale",
            direction_code="SALE",
            invoice_kind_code="VAT",
            invoice_number="FS/05/2026/1",
            issue_date=date(2026, 5, 12),
            ksef_status_code="DRAFT",
            accounting_qualified=True,
        )
        db.add_all([may_purchase, june_purchase, may_sale])
        db.commit()

        batch = AccountingService.generate_monthly_purchase_batch(
            db,
            period_year=2026,
            period_month=5,
        )

        db.refresh(may_purchase)
        db.refresh(june_purchase)
        db.refresh(may_sale)

        included_invoice_ids = db.execute(
            select(AccountingBatchInvoice.invoice_id).order_by(AccountingBatchInvoice.id)
        ).scalars().all()
        created_jobs = db.execute(select(IntegrationJob)).scalars().all()

        assert batch.item_count == 1
        assert included_invoice_ids == [may_purchase.id]
        assert may_purchase.accounting_batch_id == batch.batch_code
        assert june_purchase.accounting_batch_id is None
        assert may_sale.accounting_batch_id is None
        assert len(created_jobs) == 1
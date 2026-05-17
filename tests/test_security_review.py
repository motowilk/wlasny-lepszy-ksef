from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from fastapi.security import HTTPBasicCredentials
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.api.dependencies.auth as auth_module
import app.core.security as security_module
import app.ui.routes as ui_module
from app.core.config import settings
from app.db.dependencies import get_db
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
from app.services.ksef_import_service import KsefImportService
from app.ui.routes import UIAuthRequired, _resolve_ui_user, _set_user_password, get_current_ui_user
from main import app


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
        failed_login_attempts=0,
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


def test_api_failed_auth_locks_user_after_three_attempts(monkeypatch) -> None:
    user = SimpleNamespace(
        id=1,
        username="reviewer",
        password_hash="hashed",
        failed_login_attempts=0,
        is_active=True,
        is_locked=False,
        roles=[],
    )
    db = _FakeDbSession(user)

    monkeypatch.setattr(auth_module, "verify_password", lambda plain, hashed: False)

    for _ in range(3):
        with pytest.raises(HTTPException) as exc_info:
            auth_module.get_current_user(
                credentials=HTTPBasicCredentials(username="reviewer", password="wrong"),
                db=db,
            )
        assert exc_info.value.status_code == 401

    assert user.failed_login_attempts == 3
    assert user.is_locked is True
    assert db.commit_calls == 3


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


def _make_ui_user(*role_codes: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=11,
        user_uuid="user-11",
        username="owner",
        email="owner@example.com",
        display_name="Owner",
        password_hash="hash",
        auth_provider="LOCAL",
        failed_login_attempts=0,
        is_active=True,
        is_locked=False,
        metadata_json={"ui_session_nonce": "nonce-a"},
        roles=[
            SimpleNamespace(role=SimpleNamespace(role_code=role_code))
            for role_code in role_codes
        ],
    )


@pytest.mark.parametrize("role_code", ["admin", "agent", "owner"])
def test_ui_purchase_import_allows_expected_roles(monkeypatch, role_code: str) -> None:
    captured = {}

    def fake_fetch_and_import_purchases(*, db, date_from, date_to, actor_id):
        captured["actor_id"] = actor_id
        captured["date_from"] = date_from
        captured["date_to"] = date_to
        return []

    def override_db():
        yield object()

    monkeypatch.setattr(
        KsefImportService,
        "fetch_and_import_purchases",
        staticmethod(fake_fetch_and_import_purchases),
    )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_ui_user] = lambda: _make_ui_user(role_code)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/ui/purchase-invoices/fetch-ksef",
                data={"date_from": "2026-05-01", "date_to": "2026-05-31"},
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 303
    assert response.headers["location"].endswith("/ui/purchase-invoices?fetch_result=0")
    assert captured == {
        "actor_id": "11",
        "date_from": "2026-05-01T00:00:00",
        "date_to": "2026-05-31T23:59:59",
    }


def test_ui_purchase_import_rejects_viewer_role() -> None:
    def override_db():
        yield object()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_ui_user] = lambda: _make_ui_user("viewer")

    try:
        with TestClient(app) as client:
            response = client.post(
                "/ui/purchase-invoices/fetch-ksef",
                data={"date_from": "2026-05-01", "date_to": "2026-05-31"},
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 303
    assert response.headers["location"].startswith("/ui?error=")


def test_password_change_rotates_ui_session_nonce(monkeypatch) -> None:
    user = AppUser(
        id=7,
        user_uuid="user-7",
        username="tester",
        email="tester@example.com",
        display_name="Tester",
        password_hash="old-hash",
        auth_provider="LOCAL",
        failed_login_attempts=2,
        is_active=True,
        is_locked=False,
        metadata_json={"ui_session_nonce": "nonce-a"},
    )

    monkeypatch.setattr(ui_module, "get_password_hash", lambda password: f"hashed:{password}")

    _set_user_password(user, "new-password-123")

    assert user.password_hash == "hashed:new-password-123"
    assert user.failed_login_attempts == 0
    assert user.metadata_json is not None
    assert user.metadata_json["ui_session_nonce"] != "nonce-a"
    assert user.metadata_json["ui_session_nonce"]


def test_ui_login_missing_user_uses_dummy_hash(monkeypatch) -> None:
    seen = {}
    fake_db = _FakeDbSession(None)

    def fake_verify_password(plain: str, password_hash: str) -> bool:
        seen["plain"] = plain
        seen["password_hash"] = password_hash
        return False

    def override_db():
        yield fake_db

    monkeypatch.setattr(ui_module, "verify_password", fake_verify_password)

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/ui/login",
                data={"username": "ghost", "password": "bad-password"},
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert seen == {
        "plain": "bad-password",
        "password_hash": security_module.DUMMY_PASSWORD_HASH,
    }


def test_ui_login_locks_user_after_three_failed_attempts(monkeypatch) -> None:
    user = AppUser(
        id=7,
        user_uuid="user-7",
        username="tester",
        email="tester@example.com",
        display_name="Tester",
        password_hash="real-hash",
        auth_provider="LOCAL",
        failed_login_attempts=0,
        is_active=True,
        is_locked=False,
        metadata_json={"ui_session_nonce": "nonce-a"},
    )
    fake_db = _FakeDbSession(user)

    def override_db():
        yield fake_db

    monkeypatch.setattr(ui_module, "verify_password", lambda plain, password_hash: False)

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            for _ in range(3):
                response = client.post(
                    "/ui/login",
                    data={"username": "tester", "password": "bad-password"},
                    follow_redirects=False,
                )
                assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()

    assert user.failed_login_attempts == 3
    assert user.is_locked is True
    assert fake_db.commit_calls == 3


def test_ui_operation_error_masks_infrastructure_details() -> None:
    message = ui_module._ui_operation_error("purchase_import")

    assert "KSeF" in message
    assert "http" not in message.lower()
    assert "500" not in message


# ---------------------------------------------------------------------------
# Additional security tests
# ---------------------------------------------------------------------------

def test_csrf_token_generation_and_verification() -> None:
    from app.core.security import generate_csrf_token, verify_csrf_token

    nonce = "test-nonce-123"
    secret = "test-secret"
    token = generate_csrf_token(nonce, secret)

    assert verify_csrf_token(token, nonce, secret) is True
    assert verify_csrf_token("wrong-token", nonce, secret) is False
    assert verify_csrf_token(token, "wrong-nonce", secret) is False
    assert verify_csrf_token(None, nonce, secret) is False
    assert verify_csrf_token("", nonce, secret) is False


def test_totp_encryption_roundtrip() -> None:
    from app.core.security import (
        encrypt_totp_secret,
        decrypt_totp_secret,
        is_totp_encrypted,
    )

    plain = "JBSWY3DPEHPK3PXP"
    secret = "app-secret-key"
    encrypted = encrypt_totp_secret(plain, secret)

    assert encrypted != plain
    assert is_totp_encrypted(encrypted)
    assert not is_totp_encrypted(plain)
    assert decrypt_totp_secret(encrypted, secret) == plain
    assert decrypt_totp_secret(encrypted, "wrong-key") is None


def test_password_length_cap() -> None:
    from app.core.security import MAX_PASSWORD_LENGTH

    assert MAX_PASSWORD_LENGTH == 128


def test_session_max_age_is_2h() -> None:
    from app.core.security import UI_SESSION_MAX_AGE

    assert UI_SESSION_MAX_AGE == 7200


def test_lockout_sets_is_locked_not_is_active() -> None:
    from app.core.security import record_failed_login_attempt, MAX_FAILED_LOGIN_ATTEMPTS
    from types import SimpleNamespace

    user = SimpleNamespace(failed_login_attempts=0, is_active=True, is_locked=False)
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        record_failed_login_attempt(user)

    assert user.is_locked is True
    assert user.is_active is True  # is_active should remain unchanged
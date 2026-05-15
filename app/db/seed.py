from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AppRole,
    DictInvoiceDirection,
    DictInvoiceKind,
    DictKsefStatus,
    DictPartyRole,
    DictPayloadType,
)


def seed_reference_data(db: Session) -> None:
    _seed_invoice_directions(db)
    _seed_invoice_kinds(db)
    _seed_party_roles(db)
    _seed_ksef_statuses(db)
    _seed_payload_types(db)
    _seed_roles(db)
    db.commit()


def _exists(db: Session, model, code_field: str, code_value: str) -> bool:
    stmt = select(model).where(getattr(model, code_field) == code_value)
    return db.execute(stmt).scalar_one_or_none() is not None


def _seed_invoice_directions(db: Session) -> None:
    items = [
        ("SALE", "Sprzedażowa"),
        ("PURCHASE", "Zakupowa"),
    ]
    for code, name in items:
        if not _exists(db, DictInvoiceDirection, "code", code):
            db.add(DictInvoiceDirection(code=code, name=name))


def _seed_invoice_kinds(db: Session) -> None:
    items = [
        ("STANDARD", "Faktura standardowa"),
        ("CORRECTION", "Faktura korygująca"),
        ("ADVANCE", "Faktura zaliczkowa"),
    ]
    for code, name in items:
        if not _exists(db, DictInvoiceKind, "code", code):
            db.add(DictInvoiceKind(code=code, name=name))


def _seed_party_roles(db: Session) -> None:
    items = [
        ("SELLER", "Sprzedawca"),
        ("BUYER", "Nabywca"),
        ("ISSUER", "Wystawca"),
        ("RECIPIENT", "Odbiorca"),
    ]
    for code, name in items:
        if not _exists(db, DictPartyRole, "code", code):
            db.add(DictPartyRole(code=code, name=name))


def _seed_ksef_statuses(db: Session) -> None:
    items = [
        ("DRAFT", "Draft"),
        ("GENERATED", "Generated"),
        ("QUEUED", "Queued"),
        ("SENT", "Sent"),
        ("PROCESSING", "Processing"),
        ("ACCEPTED", "Accepted"),
        ("REJECTED", "Rejected"),
        ("DOWNLOADED", "Downloaded"),
        ("ERROR", "Error"),
    ]
    for code, name in items:
        if not _exists(db, DictKsefStatus, "code", code):
            db.add(DictKsefStatus(code=code, name=name))


def _seed_payload_types(db: Session) -> None:
    items = [
        ("KSEF_XML", "Payload XML KSeF"),
        ("KSEF_REQUEST", "Request do KSeF"),
        ("KSEF_RESPONSE", "Response z KSeF"),
        ("KSEF_XML_RECEIVED", "XML faktury pobranej z KSeF"),
        ("EMAIL_BODY", "Treść maila"),
    ]
    for code, name in items:
        if not _exists(db, DictPayloadType, "code", code):
            db.add(DictPayloadType(code=code, name=name))


def _seed_roles(db: Session) -> None:
    items = [
        ("admin", "Administrator", "Pełne uprawnienia administracyjne"),
        ("agent", "Agent AI", "Tworzenie draftów i operacje automatyczne bez akceptacji"),
        ("reviewer", "Reviewer", "Edycja i akceptacja dokumentów"),
        ("owner", "Właściciel/Operator", "Wystawianie faktur, kwalifikacja zakupów, zarządzanie batchami do biura księgowego"),
        ("viewer", "Viewer", "Dostęp tylko do odczytu"),
    ]
    for role_code, role_name, description in items:
        stmt = select(AppRole).where(AppRole.role_code == role_code)
        if db.execute(stmt).scalar_one_or_none() is None:
            db.add(AppRole(role_code=role_code, role_name=role_name, description=description))

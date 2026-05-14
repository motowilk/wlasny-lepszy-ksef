from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DictInvoiceDirection(Base):
    __tablename__ = "dict_invoice_direction"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class DictInvoiceKind(Base):
    __tablename__ = "dict_invoice_kind"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)


class DictPartyRole(Base):
    __tablename__ = "dict_party_role"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)


class DictKsefStatus(Base):
    __tablename__ = "dict_ksef_status"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)


class DictPayloadType(Base):
    __tablename__ = "dict_payload_type"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)

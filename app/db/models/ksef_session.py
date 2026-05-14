from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class KsefSession(Base):
    __tablename__ = "ksef_session"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_reference_number: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    session_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    session_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    )

    invoices = relationship(
        "KsefSessionInvoice",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class KsefSessionInvoice(Base):
    __tablename__ = "ksef_session_invoice"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("ksef_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoice.id", ondelete="CASCADE"),
        nullable=False,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    processing_description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    batch_item_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    session = relationship("KsefSession", back_populates="invoices")

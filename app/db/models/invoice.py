from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, JSON, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Invoice(Base):
    __tablename__ = "invoice"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    direction_code: Mapped[str] = mapped_column(
        ForeignKey("dict_invoice_direction.code"),
        nullable=False,
    )
    invoice_kind_code: Mapped[str] = mapped_column(
        ForeignKey("dict_invoice_kind.code"),
        nullable=False,
    )
    local_document_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_system_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    invoice_number: Mapped[str] = mapped_column(String(255), nullable=False)
    ksef_number: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    ksef_reference_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    sale_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    receive_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="PLN")
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_paid: Mapped[bool] = mapped_column(nullable=False, server_default="0")
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    net_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    vat_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    gross_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    rounding_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    is_correction: Mapped[bool] = mapped_column(nullable=False, server_default="0")
    corrected_invoice_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    corrected_ksef_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ksef_status_code: Mapped[str] = mapped_column(
        ForeignKey("dict_ksef_status.code"),
        nullable=False,
        server_default="DRAFT",
    )
    accounting_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    purchase_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    erp_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    review_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    review_locked_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    review_locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accounting_marked_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    accounting_marked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accounting_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    accounting_qualified: Mapped[bool | None] = mapped_column(nullable=True)
    accounting_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounting_batch.batch_code", ondelete="SET NULL"),
        nullable=True,
    )
    notification_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notification_channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_notification_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ksef_session_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ksef_submission_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ksef_acceptance_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ksef_download_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(50), nullable=True, server_default="FA(3)")
    source_system: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    xml_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    business_tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fa_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    workflow_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    )

    parties = relationship("InvoiceParty", back_populates="invoice", cascade="all, delete-orphan")
    lines = relationship("InvoiceLine", back_populates="invoice", cascade="all, delete-orphan")
    vat_summaries = relationship("InvoiceVatSummary", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("InvoicePayment", back_populates="invoice", cascade="all, delete-orphan")
    attachments = relationship("InvoiceAttachment", back_populates="invoice", cascade="all, delete-orphan")
    payloads = relationship("InvoicePayload", back_populates="invoice", cascade="all, delete-orphan")
    events = relationship("InvoiceEvent", back_populates="invoice", cascade="all, delete-orphan")
    jobs = relationship("IntegrationJob", back_populates="invoice")

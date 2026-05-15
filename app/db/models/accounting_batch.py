from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AccountingBatch(Base):
    __tablename__ = "accounting_batch"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    batch_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    batch_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    period_year: Mapped[int] = mapped_column(nullable=False)
    period_month: Mapped[int] = mapped_column(nullable=False)
    criteria_json: Mapped[dict | None] = mapped_column("criteria_json", JSON, nullable=True)
    item_count: Mapped[int] = mapped_column(nullable=False, server_default="0")
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
        "AccountingBatchInvoice",
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class AccountingBatchInvoice(Base):
    __tablename__ = "accounting_batch_invoice"
    __table_args__ = (
        UniqueConstraint("invoice_id", name="uq_accounting_batch_invoice_invoice_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_batch.id", ondelete="CASCADE"),
        nullable=False,
    )
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoice.id", ondelete="CASCADE"),
        nullable=False,
    )
    inclusion_status: Mapped[str] = mapped_column(String(50), nullable=False)
    inclusion_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    batch = relationship("AccountingBatch", back_populates="invoices")
    invoice = relationship("Invoice")

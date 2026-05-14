from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InvoiceVatSummary(Base):
    __tablename__ = "invoice_vat_summary"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoice.id", ondelete="CASCADE"),
        nullable=False,
    )
    vat_code: Mapped[str] = mapped_column(String(32), nullable=False)
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    summary_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    invoice = relationship("Invoice", back_populates="vat_summaries")

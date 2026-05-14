from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, JSON, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InvoicePayment(Base):
    __tablename__ = "invoice_payment"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoice.id", ondelete="CASCADE"),
        nullable=False,
    )
    payment_no: Mapped[int] = mapped_column(nullable=False, server_default="1")
    payment_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_term_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, server_default="PLN")
    bank_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    split_payment: Mapped[bool] = mapped_column(nullable=False, server_default="0")
    payment_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    invoice = relationship("Invoice", back_populates="payments")

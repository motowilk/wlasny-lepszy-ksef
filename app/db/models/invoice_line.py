from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InvoiceLine(Base):
    __tablename__ = "invoice_line"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoice.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_name: Mapped[str] = mapped_column(String(1000), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pkwiu_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cn_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, server_default="1.000000")
    unit_price_net: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, server_default="0.000000")
    unit_price_gross: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    vat_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reverse_charge: Mapped[bool] = mapped_column(nullable=False, server_default="0")
    tax_procedure_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_exemption_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0.00")
    line_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tax_flags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    invoice = relationship("Invoice", back_populates="lines")

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InvoiceParty(Base):
    __tablename__ = "invoice_party"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoice.id", ondelete="CASCADE"),
        nullable=False,
    )
    party_id: Mapped[int] = mapped_column(
        ForeignKey("party.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_code: Mapped[str] = mapped_column(
        ForeignKey("dict_party_role.code"),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(nullable=False, server_default="1")
    role_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    invoice = relationship("Invoice", back_populates="parties")
    party = relationship("Party", back_populates="invoice_links")

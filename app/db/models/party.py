from datetime import datetime

from sqlalchemy import DateTime, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Party(Base):
    __tablename__ = "party"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    party_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    party_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    name_full: Mapped[str] = mapped_column(String(500), nullable=False)
    name_short: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vat_eu_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    regon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    krs: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    building_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    apartment_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    province: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="1")
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        server_onupdate=func.current_timestamp(),
    )

    invoice_links = relationship("InvoiceParty", back_populates="party")

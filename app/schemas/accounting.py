from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AccountingStatusUpdateRequest(BaseModel):
    accounting_status: str = Field(
        ...,
        description="new / verified / posted / booked / cancelled",
    )
    accounting_notes: str | None = None
    accounting_qualified: bool | None = None


class PurchaseQualificationRequest(BaseModel):
    accounting_qualified: bool
    accounting_notes: str | None = None


class AccountingBatchGenerateRequest(BaseModel):
    period_year: int
    period_month: int
    criteria_json: dict[str, Any] | None = None


class AccountingBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_uuid: str
    batch_code: str
    batch_type: str
    status: str
    period_year: int
    period_month: int
    criteria_json: dict[str, Any] | None = None
    item_count: int
    sent_at: datetime | None = None
    created_at: datetime


class AccountingBatchInvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    invoice_id: int
    inclusion_status: str
    inclusion_reason: str | None = None
    created_at: datetime

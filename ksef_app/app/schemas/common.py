from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str
    ksef_mode: str


class MessageResponse(BaseModel):
    message: str


class IdResponse(BaseModel):
    id: int


class AuditInfo(ORMModel):
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PaginationQuery(BaseModel):
    limit: int = 50
    offset: int = 0


class DecimalAmount(BaseModel):
    value: Decimal


JsonDict = dict[str, Any]


class DateRange(BaseModel):
    date_from: date | None = None
    date_to: date | None = None

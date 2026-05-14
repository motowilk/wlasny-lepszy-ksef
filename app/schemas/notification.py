from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr


class NotificationCreate(BaseModel):
    invoice_id: int | None = None
    batch_id: int | None = None
    channel: str = "EMAIL"
    recipient: EmailStr
    subject: str | None = None
    payload: dict[str, Any] | None = None


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notification_uuid: str
    invoice_id: int | None = None
    batch_id: int | None = None
    channel: str
    recipient: str
    subject: str | None = None
    payload: dict[str, Any] | None = None
    status: str
    error_message: str | None = None
    sent_at: datetime | None = None
    created_at: datetime

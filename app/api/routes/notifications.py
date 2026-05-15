from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_roles
from app.db.dependencies import get_db
from app.db.models import AppUser, NotificationLog
from app.schemas.notification import NotificationRead
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/api", tags=["notifications"])


@router.post("/invoices/{invoice_id}/notify", response_model=NotificationRead)
def create_notification(
    invoice_id: int,
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "reviewer", "owner")),
) -> NotificationRead:
    try:
        notification = NotificationService.create_invoice_notification(db, invoice_id)
        return NotificationRead.model_validate(notification, from_attributes=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Nie udało się utworzyć powiadomienia.",
        ) from exc


@router.post("/notifications/{notification_id}/send", response_model=NotificationRead)
def send_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "reviewer", "owner")),
) -> NotificationRead:
    try:
        notification = NotificationService.send_notification(db, notification_id)
        return NotificationRead.model_validate(notification, from_attributes=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Nie udało się wysłać powiadomienia.",
        ) from exc


@router.get("/notifications", response_model=list[NotificationRead])
def list_notifications(
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "owner", "viewer")),
) -> list[NotificationRead]:
    items = (
        db.execute(select(NotificationLog).order_by(NotificationLog.id.desc()))
        .scalars()
        .all()
    )
    return [NotificationRead.model_validate(item, from_attributes=True) for item in items]

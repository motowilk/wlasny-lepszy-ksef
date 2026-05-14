from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_roles
from app.db.dependencies import get_db
from app.db.models import AppUser, IntegrationJob, Invoice
from app.schemas.invoice import InvoiceRead

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/health")
def agent_health(
    _: AppUser = Depends(require_roles("admin", "agent")),
):
    return {"status": "ok", "agent_mode": "enabled"}


@router.get("/work-queue")
def get_work_queue(
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "agent")),
):
    jobs = (
        db.execute(
            select(IntegrationJob)
            .where(IntegrationJob.status.in_(["NEW", "PROCESSING"]))
            .order_by(IntegrationJob.priority.asc(), IntegrationJob.id.asc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": j.id,
            "job_uuid": j.job_uuid,
            "job_type": j.job_type,
            "status": j.status,
            "invoice_id": j.invoice_id,
            "priority": j.priority,
            "attempts": j.attempts,
            "scheduled_at": j.scheduled_at,
        }
        for j in jobs
    ]


@router.get("/drafts", response_model=list[InvoiceRead])
def get_agent_drafts(
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "agent")),
) -> list[InvoiceRead]:
    items = (
        db.execute(
            select(Invoice)
            .where(Invoice.erp_status == "DRAFT_CREATED")
            .order_by(Invoice.id.desc())
        )
        .scalars()
        .all()
    )
    return [InvoiceRead.model_validate(item, from_attributes=True) for item in items]

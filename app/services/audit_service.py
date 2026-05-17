"""Simple audit logging for admin/security-sensitive operations."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.models.admin_audit_log import AdminAuditLog


def log_audit(
    db: Session,
    *,
    actor_user_id: int,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: str | None = None,
    request: Request | None = None,
) -> None:
    """Record an audit event."""
    ip_address = None
    if request:
        ip_address = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if not ip_address and request.client:
            ip_address = request.client.host

    entry = AdminAuditLog(
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=ip_address,
    )
    db.add(entry)

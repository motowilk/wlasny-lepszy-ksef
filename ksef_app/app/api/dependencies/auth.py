from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.security import normalize_username, verify_password
from app.db.dependencies import get_db
from app.db.models import AppUser, AppUserRole

security = HTTPBasic(realm=settings.basic_auth_realm)

# Pre-computed hash used only for constant-time dummy checks when a user is not
# found, to prevent timing-based username enumeration.
_DUMMY_HASH = "$2b$12$KIX/TAtOSw8A4uFGrwFnGuvVVz3SsLOJo0bMLXkn9E2z8CRF.pBGG"


def get_current_user(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> AppUser:
    username = normalize_username(credentials.username)

    stmt = (
        select(AppUser)
        .where(AppUser.username == username)
        .options(joinedload(AppUser.roles).joinedload(AppUserRole.role))
    )
    user = db.execute(stmt).unique().scalar_one_or_none()

    if not user:
        # Always run the hash check to keep response time constant and prevent
        # timing-based username enumeration.
        verify_password(credentials.password, _DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nieprawidłowy login lub hasło.",
            headers={"WWW-Authenticate": "Basic"},
        )

    if not user.is_active or user.is_locked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Konto jest nieaktywne lub zablokowane.",
        )

    if not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nieprawidłowy login lub hasło.",
            headers={"WWW-Authenticate": "Basic"},
        )

    user.last_login_at = datetime.now(tz=timezone.utc)
    db.commit()

    return user


def require_roles(*role_codes: str) -> Callable:
    def role_dependency(user: AppUser = Depends(get_current_user)) -> AppUser:
        current_roles = {item.role.role_code for item in user.roles}
        if not any(role in current_roles for role in role_codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Brak wymaganej roli. Wymagane: {', '.join(role_codes)}",
            )
        return user

    return role_dependency

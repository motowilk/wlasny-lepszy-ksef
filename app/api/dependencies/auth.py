from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    MAX_PASSWORD_LENGTH,
    normalize_username,
    record_failed_login_attempt,
    reset_failed_login_attempts,
    verify_password,
)
from app.db.dependencies import get_db
from app.db.models import AppUser, AppUserRole

security = HTTPBasic(realm=settings.basic_auth_realm)


def get_current_user(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> AppUser:
    username = normalize_username(credentials.username)
    password = credentials.password[:MAX_PASSWORD_LENGTH]

    stmt = (
        select(AppUser)
        .where(AppUser.username == username)
        .options(joinedload(AppUser.roles).joinedload(AppUserRole.role))
    )
    user = db.execute(stmt).unique().scalar_one_or_none()
    password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    password_valid = verify_password(password, password_hash)

    if not user or not password_valid:
        if user and user.is_active and not user.is_locked:
            record_failed_login_attempt(user)
            db.commit()
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

    if user.failed_login_attempts:
        reset_failed_login_attempts(user)
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

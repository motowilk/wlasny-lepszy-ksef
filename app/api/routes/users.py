import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies.auth import require_roles
from app.core.security import get_password_hash, normalize_username
from app.db.dependencies import get_db
from app.db.models import AppRole, AppUser, AppUserRole
from app.schemas.user import AssignRolesRequest, RoleRead, UserCreate, UserRead, UserWithRoles

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/users", response_model=list[UserWithRoles])
def list_users(
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin")),
) -> list[UserWithRoles]:
    stmt = select(AppUser).options(joinedload(AppUser.roles).joinedload(AppUserRole.role))
    users = db.execute(stmt).unique().scalars().all()

    result = []
    for user in users:
        roles = [RoleRead.model_validate(item.role, from_attributes=True) for item in user.roles]
        result.append(
            UserWithRoles(
                id=user.id,
                user_uuid=user.user_uuid,
                username=user.username,
                email=user.email,
                display_name=user.display_name,
                auth_provider=user.auth_provider,
                is_active=user.is_active,
                is_locked=user.is_locked,
                last_login_at=user.last_login_at,
                created_at=user.created_at,
                roles=roles,
            )
        )
    return result


@router.post("/users", response_model=UserRead)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin")),
) -> UserRead:
    username = normalize_username(payload.username)

    existing = db.execute(
        select(AppUser).where(AppUser.username == username)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Użytkownik o tym loginie już istnieje.")

    user = AppUser(
        user_uuid=str(uuid.uuid4()),
        username=username,
        email=payload.email,
        display_name=payload.display_name,
        password_hash=get_password_hash(payload.password),
        auth_provider="LOCAL",
        is_active=True,
        is_locked=False,
    )
    db.add(user)
    db.flush()

    if payload.role_codes:
        roles = (
            db.execute(select(AppRole).where(AppRole.role_code.in_(payload.role_codes)))
            .scalars()
            .all()
        )
        found_role_codes = {role.role_code for role in roles}
        missing_role_codes = sorted(set(payload.role_codes) - found_role_codes)
        if missing_role_codes:
            raise HTTPException(
                status_code=400,
                detail=f"Nieznane role: {', '.join(missing_role_codes)}",
            )
        for role in roles:
            db.add(AppUserRole(user_id=user.id, role_id=role.id))

    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user, from_attributes=True)


@router.get("/roles", response_model=list[RoleRead])
def list_roles(
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin", "viewer", "reviewer", "owner")),
) -> list[RoleRead]:
    roles = db.execute(select(AppRole).order_by(AppRole.role_code)).scalars().all()
    return [RoleRead.model_validate(role, from_attributes=True) for role in roles]


@router.post("/users/{user_id}/roles", response_model=UserWithRoles)
def assign_roles(
    user_id: int,
    payload: AssignRolesRequest,
    db: Session = Depends(get_db),
    _: AppUser = Depends(require_roles("admin")),
) -> UserWithRoles:
    user = db.execute(
        select(AppUser)
        .where(AppUser.id == user_id)
        .options(joinedload(AppUser.roles).joinedload(AppUserRole.role))
    ).unique().scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Użytkownik nie istnieje.")

    db.execute(delete(AppUserRole).where(AppUserRole.user_id == user.id))

    roles = (
        db.execute(select(AppRole).where(AppRole.role_code.in_(payload.role_codes)))
        .scalars()
        .all()
    )
    found_role_codes = {role.role_code for role in roles}
    missing_role_codes = sorted(set(payload.role_codes) - found_role_codes)
    if missing_role_codes:
        raise HTTPException(
            status_code=400,
            detail=f"Nieznane role: {', '.join(missing_role_codes)}",
        )
    for role in roles:
        db.add(AppUserRole(user_id=user.id, role_id=role.id))

    db.commit()

    user = db.execute(
        select(AppUser)
        .where(AppUser.id == user_id)
        .options(joinedload(AppUser.roles).joinedload(AppUserRole.role))
    ).unique().scalar_one()

    return UserWithRoles(
        id=user.id,
        user_uuid=user.user_uuid,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        auth_provider=user.auth_provider,
        is_active=user.is_active,
        is_locked=user.is_locked,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        roles=[
            RoleRead.model_validate(item.role, from_attributes=True)
            for item in user.roles
        ],
    )

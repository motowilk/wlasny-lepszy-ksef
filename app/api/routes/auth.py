from fastapi import APIRouter, Depends

from app.api.dependencies.auth import get_current_user
from app.db.models import AppUser
from app.schemas.user import RoleRead, UserWithRoles

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/me", response_model=UserWithRoles)
def get_me(current_user: AppUser = Depends(get_current_user)) -> UserWithRoles:
    roles = [
        RoleRead.model_validate(item.role, from_attributes=True)
        for item in current_user.roles
    ]
    return UserWithRoles(
        id=current_user.id,
        user_uuid=current_user.user_uuid,
        username=current_user.username,
        email=current_user.email,
        display_name=current_user.display_name,
        auth_provider=current_user.auth_provider,
        is_active=current_user.is_active,
        is_locked=current_user.is_locked,
        last_login_at=current_user.last_login_at,
        created_at=current_user.created_at,
        roles=roles,
    )

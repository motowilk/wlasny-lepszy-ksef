from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role_code: str
    role_name: str
    description: str | None = None


class UserCreate(BaseModel):
    username: str
    email: EmailStr | None = None
    display_name: str
    password: str = Field(min_length=10)
    role_codes: list[str] = []


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_uuid: str
    username: str
    email: str | None = None
    display_name: str
    auth_provider: str
    is_active: bool
    is_locked: bool
    last_login_at: datetime | None = None
    created_at: datetime


class UserWithRoles(UserRead):
    roles: list[RoleRead] = []


class AssignRolesRequest(BaseModel):
    role_codes: list[str]

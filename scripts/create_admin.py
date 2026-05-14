"""
Tworzy konto administratora.

Użycie:
    cd ksef_app
    python scripts/create_admin.py
"""
import sys
from pathlib import Path

# Add parent directory to path so we can import app module
sys.path.insert(0, str(Path(__file__).parent.parent))

import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import get_password_hash
from app.db.models import AppRole, AppUser, AppUserRole
from app.db.session import SessionLocal


def main() -> None:
    settings = get_settings()
    password = settings.admin_default_password.strip()
    if not password:
        raise ValueError("ADMIN_DEFAULT_PASSWORD must be set before creating the admin user.")

    db = SessionLocal()
    try:
        existing = db.execute(
            select(AppUser).where(AppUser.username == "admin")
        ).scalars().first()

        if existing:
            print("Użytkownik 'admin' już istnieje.")
            return

        admin_user = AppUser(
            user_uuid=str(uuid.uuid4()),
            username="admin",
            email="admin@ksef.local",
            display_name="Administrator",
            password_hash=get_password_hash(password),
            auth_provider="LOCAL",
            is_active=True,
            is_locked=False,
        )
        db.add(admin_user)
        db.flush()

        admin_role = db.execute(
            select(AppRole).where(AppRole.role_code == "admin")
        ).scalars().first()

        if admin_role:
            db.add(AppUserRole(user_id=admin_user.id, role_id=admin_role.id))

        db.commit()
        print("Użytkownik 'admin' utworzony pomyślnie.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

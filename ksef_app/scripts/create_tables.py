"""
Tworzy wszystkie tabele w bazie danych na podstawie modeli SQLAlchemy.
Uruchom raz przed pierwszym startem aplikacji.

Użycie:
    cd ksef_app
    python scripts/create_tables.py
"""
import app.db.models  # noqa: F401 — rejestruje wszystkie modele w Base.metadata

from app.db.base import Base
from app.db.session import engine


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("Tabele utworzone pomyślnie.")


if __name__ == "__main__":
    main()

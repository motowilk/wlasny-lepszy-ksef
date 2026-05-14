"""
Wypełnia tabele słownikowe i role domyślnymi danymi.

Użycie:
    cd ksef_app
    python scripts/seed_reference_data.py
"""
from app.db.seed import seed_reference_data
from app.db.session import SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
        seed_reference_data(db)
        print("Dane referencyjne załadowane pomyślnie.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

"""
Wypełnia tabele słownikowe i role domyślnymi danymi.

Użycie:
    cd ksef_app
    python scripts/seed_reference_data.py
"""
import sys
from pathlib import Path

# Add parent directory to path so we can import app module
sys.path.insert(0, str(Path(__file__).parent.parent))

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

"""
Import a PURCHASE invoice from a local XML file — simulates what job_worker does
when processing FETCH_KSEF_PURCHASES from KSeF API.

Usage:
    python scripts/import_purchase_xml.py 123456789-zakupowa-test.xml

Optional --ksef-number flag to assign a KSeF reference number:
    python scripts/import_purchase_xml.py 123456789-zakupowa-test.xml --ksef-number 6721877104-20260505-AAABBB-01
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal
from app.services.ksef_import_service import KsefImportService


def main() -> None:
    parser = argparse.ArgumentParser(description="Import FA(3) XML as PURCHASE invoice.")
    parser.add_argument("xml_file", help="Path to the FA(3) XML file")
    parser.add_argument("--ksef-number", default=None, help="KSeF reference number to assign")
    parser.add_argument("--actor-id", default="script", help="Actor ID for the event log")
    args = parser.parse_args()

    xml_path = Path(args.xml_file)
    if not xml_path.exists():
        print(f"ERROR: File not found: {xml_path}")
        sys.exit(1)

    xml_content = xml_path.read_text(encoding="utf-8")
    print(f"Read {len(xml_content)} bytes from {xml_path.name}")

    db = SessionLocal()
    try:
        invoice = KsefImportService.import_invoice_xml(
            db=db,
            xml_content=xml_content,
            ksef_number=args.ksef_number,
            direction_code="PURCHASE",
            actor_id=args.actor_id,
        )

        if invoice is None:
            print("SKIPPED: Invoice already exists (duplicate ksef_number or invoice_number).")
        else:
            print(f"SUCCESS: Imported invoice id={invoice.id}")
            print(f"  invoice_number = {invoice.invoice_number}")
            print(f"  ksef_number    = {invoice.ksef_number}")
            print(f"  ksef_status    = {invoice.ksef_status_code}")
            print(f"  erp_status     = {invoice.erp_status}")
            print(f"  direction      = {invoice.direction_code}")
            print(f"  gross_total    = {invoice.gross_total}")
    except Exception as exc:
        print(f"ERROR: {exc}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

import logging
from decimal import Decimal
from pathlib import Path

from app.db.models import Invoice
from app.schemas.invoice import InvoiceValidateResponse

logger = logging.getLogger(__name__)

# ── KSeF XSD schema cache (loaded once at first use) ──────────────────────────
_ksef_schema = None
_ksef_schema_attempted = False


def _load_ksef_schema():
    """Load and cache the FA(3) XSD schema. Returns None if unavailable."""
    global _ksef_schema, _ksef_schema_attempted
    if _ksef_schema_attempted:
        return _ksef_schema
    _ksef_schema_attempted = True
    try:
        from lxml import etree  # noqa: PLC0415
    except ImportError:
        logger.warning("lxml is not installed — XSD validation unavailable")
        _ksef_schema = None
        return None
    try:
        _safe_parser = etree.XMLParser(resolve_entities=False, no_network=True, dtd_validation=False, load_dtd=False)
        schemas_dir = Path(__file__).parent.parent / "adapters" / "ksef" / "schemas"
        xsd_path = schemas_dir / "schemat_FA3_v1-0E.xsd"
        if not xsd_path.exists():
            logger.warning("KSeF XSD schema file not found: %s (resolved from %s)", xsd_path, Path(__file__).parent)
            return None
        xsd_doc = etree.parse(str(xsd_path), parser=_safe_parser)
        _ksef_schema = etree.XMLSchema(xsd_doc)
        logger.info("KSeF XSD schema loaded from %s", xsd_path)
    except Exception as exc:
        logger.warning("Failed to load KSeF XSD schema: %s", exc)
        _ksef_schema = None
    return _ksef_schema


class ValidationService:
    @staticmethod
    def validate_invoice(invoice: Invoice) -> InvoiceValidateResponse:
        errors: list[str] = []
        warnings: list[str] = []

        if not invoice.invoice_number:
            errors.append("Brak numeru faktury.")

        if not invoice.issue_date:
            errors.append("Brak daty wystawienia.")

        if not invoice.direction_code:
            errors.append("Brak direction_code.")

        if not invoice.invoice_kind_code:
            errors.append("Brak invoice_kind_code.")

        if not invoice.parties:
            errors.append("Faktura nie ma kontrahentów.")

        if not invoice.lines:
            errors.append("Faktura nie ma pozycji.")

        if invoice.payment_account and invoice.payment_account.strip():
            acct = invoice.payment_account.strip()
            if len(acct) < 10 or len(acct) > 34:
                errors.append(
                    f"Nr rachunku bankowego (IBAN) musi mieć od 10 do 34 znaków (podano {len(acct)})."
                )

        if invoice.direction_code == "SALE":
            buyer_exists = any(p.role_code == "BUYER" for p in invoice.parties)
            seller_link = next((p for p in invoice.parties if p.role_code == "SELLER"), None)
            seller_exists = seller_link is not None
            if not buyer_exists:
                errors.append("Faktura sprzedażowa musi mieć nabywcę.")
            if not seller_exists:
                errors.append("Faktura sprzedażowa musi mieć powiązanego sprzedawcę.")
            elif not (seller_link.party and (seller_link.party.tax_id or "").strip()):
                errors.append("Sprzedawca musi mieć wypełniony NIP.")

        calculated_net = Decimal("0.00")
        calculated_vat = Decimal("0.00")
        calculated_gross = Decimal("0.00")

        for line in invoice.lines:
            if line.quantity <= 0:
                errors.append(f"Pozycja {line.line_no}: ilość musi być większa od 0.")
            if line.unit_price_net < 0:
                errors.append(f"Pozycja {line.line_no}: cena netto nie może być ujemna.")
            if line.net_amount < 0 or line.vat_amount < 0 or line.gross_amount < 0:
                errors.append(
                    f"Pozycja {line.line_no}: wartości netto/VAT/brutto nie mogą być ujemne."
                )

            if line.reverse_charge and line.vat_code in {"23", "8", "5"}:
                warnings.append(
                    f"Pozycja {line.line_no}: reverse_charge i standardowy vat_code mogą być niespójne."
                )

            calculated_net += Decimal(line.net_amount)
            calculated_vat += Decimal(line.vat_amount)
            calculated_gross += Decimal(line.gross_amount)

        if invoice.net_total != calculated_net:
            warnings.append(
                f"Net total ({invoice.net_total}) różni się od sumy pozycji ({calculated_net})."
            )

        if invoice.vat_total != calculated_vat:
            warnings.append(
                f"VAT total ({invoice.vat_total}) różni się od sumy pozycji ({calculated_vat})."
            )

        if invoice.gross_total != calculated_gross:
            warnings.append(
                f"Gross total ({invoice.gross_total}) różni się od sumy pozycji ({calculated_gross})."
            )

        valid = len(errors) == 0
        return InvoiceValidateResponse(valid=valid, errors=errors, warnings=warnings)

    @staticmethod
    def validate_ksef_xml(xml_content: str) -> list[str]:
        """Validate XML string against the KSeF FA(3) v1-0E XSD schema.

        Returns a list of error strings (empty list = valid).
        If the schema cannot be loaded, returns a single informational message.
        """
        try:
            from lxml import etree  # noqa: PLC0415
        except ImportError:
            return ["lxml nie jest zainstalowane — walidacja XSD pominięta."]

        schema = _load_ksef_schema()
        if schema is None:
            return ["Schemat XSD FA(3) niedostępny — walidacja XSD pominięta."]

        try:
            doc = etree.fromstring(xml_content.encode("utf-8"))
        except etree.XMLSyntaxError as exc:
            return [f"Błąd składni XML: {exc}"]

        if not schema.validate(doc):
            return [str(err) for err in schema.error_log]
        return []

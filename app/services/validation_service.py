from decimal import Decimal

from app.db.models import Invoice
from app.schemas.invoice import InvoiceValidateResponse


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

        if invoice.direction_code == "SALE":
            buyer_exists = any(p.role_code == "BUYER" for p in invoice.parties)
            seller_exists = any(p.role_code == "SELLER" for p in invoice.parties)
            if not buyer_exists:
                errors.append("Faktura sprzedażowa musi mieć nabywcę.")
            if not seller_exists:
                warnings.append("Faktura sprzedażowa nie ma powiązanego sprzedawcy.")

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

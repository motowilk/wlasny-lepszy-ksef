"""Test importing a PURCHASE invoice from FA(3) XML via ksef_xml_parser + KsefImportService."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.services.ksef_xml_parser import parse_fa3_xml

XML_PATH = Path(__file__).resolve().parents[1] / "123456789-zakupowa-test.xml"


@pytest.fixture
def xml_content() -> str:
    return XML_PATH.read_text(encoding="utf-8")


class TestParseFA3XmlPurchase:
    """Verify the parser correctly extracts all data from the test XML."""

    def test_direction_code(self, xml_content: str) -> None:
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        assert result.direction_code == "PURCHASE"

    def test_invoice_number(self, xml_content: str) -> None:
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        assert result.invoice_number == "FS/134/05/2026"

    def test_issue_date(self, xml_content: str) -> None:
        from datetime import date as d
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        assert result.issue_date == d(2026, 5, 5)

    def test_sale_date(self, xml_content: str) -> None:
        from datetime import date as d
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        assert result.sale_date == d(2026, 4, 20)

    def test_currency(self, xml_content: str) -> None:
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        assert result.currency_code == "PLN"

    def test_two_lines_present(self, xml_content: str) -> None:
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        assert len(result.lines) == 2
        assert all(ln.vat_code == "23" for ln in result.lines)

    def test_seller_party(self, xml_content: str) -> None:
        """Podmiot1 = SELLER."""
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        sellers = [p for p in result.parties if p.role_code == "SELLER"]
        assert len(sellers) == 1
        seller = sellers[0].party
        assert seller.tax_id == "6721877104"
        assert "OPTIMA" in seller.name_full
        assert "Szczecin" in (seller.street or "")

    def test_buyer_party(self, xml_content: str) -> None:
        """Podmiot2 = BUYER."""
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        buyers = [p for p in result.parties if p.role_code == "BUYER"]
        assert len(buyers) == 1
        buyer = buyers[0].party
        assert buyer.tax_id == "8522713795"
        assert "LIMENE" in buyer.name_full

    def test_line_1_details(self, xml_content: str) -> None:
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        line = result.lines[0]
        assert line.line_no == 1
        assert line.product_name == "Usługi księgowe"
        assert line.unit_code == "usł"
        assert line.quantity == Decimal("1.0000")
        assert line.unit_price_net == Decimal("460.00")
        assert line.vat_code == "23"

    def test_line_2_details(self, xml_content: str) -> None:
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        line = result.lines[1]
        assert line.line_no == 2
        assert line.product_name == "Obsługa kadrowo-płacowa umowa zlecenia bez ZUS"
        assert line.unit_code == "os"
        assert line.quantity == Decimal("1.0000")
        assert line.unit_price_net == Decimal("55.00")

    def test_payment_due_date(self, xml_content: str) -> None:
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        from datetime import date as d
        assert result.due_date == d(2026, 5, 10)

    def test_payment_method(self, xml_content: str) -> None:
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        # FormaPlatnosci=6 → przelew
        assert result.payment_method == "6"

    def test_bank_account(self, xml_content: str) -> None:
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        assert result.payment_account == "51109026620000000147781196"
        assert result.fa_metadata["payment_bank_name"] == "Santander Bank Polska S.A."

    def test_invoice_kind(self, xml_content: str) -> None:
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        assert result.invoice_kind_code == "STANDARD"

    def test_lines_sum_to_expected_totals(self, xml_content: str) -> None:
        """Lines net sum should match P_13_1 (515.00)."""
        result = parse_fa3_xml(xml_content, direction_code="PURCHASE")
        lines_net = sum(ln.quantity * ln.unit_price_net for ln in result.lines)
        assert lines_net == Decimal("515.0000")

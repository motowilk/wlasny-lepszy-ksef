from decimal import Decimal

import pytest

from app.schemas.invoice import InvoiceLinePayload
from app.services.invoice_service import InvoiceService


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            InvoiceLinePayload(
                line_no=1,
                product_name="Widget",
                quantity=Decimal("0"),
                unit_price_net=Decimal("10.00"),
            ),
            "quantity must be greater than 0",
        ),
        (
            InvoiceLinePayload(
                line_no=1,
                product_name="Widget",
                quantity=Decimal("1"),
                unit_price_net=Decimal("-1.00"),
            ),
            "unit_price_net must be non-negative",
        ),
        (
            InvoiceLinePayload(
                line_no=1,
                product_name="Widget",
                quantity=Decimal("1"),
                unit_price_net=Decimal("10.00"),
                discount_percent=Decimal("150.00"),
            ),
            "discount_percent must be between 0 and 100",
        ),
        (
            InvoiceLinePayload(
                line_no=1,
                product_name="Widget",
                quantity=Decimal("1"),
                unit_price_net=Decimal("10.00"),
                discount_amount=Decimal("15.00"),
            ),
            "discount_amount cannot exceed the line net amount",
        ),
    ],
)
def test_calculate_line_amounts_rejects_invalid_inputs(payload: InvoiceLinePayload, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        InvoiceService._calculate_line_amounts(payload)


def test_calculate_line_amounts_returns_expected_amounts() -> None:
    payload = InvoiceLinePayload(
        line_no=1,
        product_name="Widget",
        quantity=Decimal("2.000000"),
        unit_price_net=Decimal("10.000000"),
        discount_percent=Decimal("10.00"),
        vat_rate=Decimal("23.00"),
        vat_code="23",
    )

    net_amount, vat_amount, gross_amount = InvoiceService._calculate_line_amounts(payload)

    assert net_amount == Decimal("18.00")
    assert vat_amount == Decimal("4.14")
    assert gross_amount == Decimal("22.14")

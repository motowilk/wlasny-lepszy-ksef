from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PartyPayload(BaseModel):
    party_uuid: str | None = None
    party_type: str | None = None
    name_full: str
    name_short: str | None = None
    tax_id: str | None = None
    vat_eu_id: str | None = None
    regon: str | None = None
    krs: str | None = None
    country_code: str | None = None
    street: str | None = None
    building_no: str | None = None
    apartment_no: str | None = None
    city: str | None = None
    postal_code: str | None = None
    province: str | None = None
    email: str | None = None
    phone: str | None = None
    bank_account: str | None = None
    extra_data: dict[str, Any] | None = None


class InvoicePartyPayload(BaseModel):
    role_code: str
    sequence_no: int = 1
    role_details: dict[str, Any] | None = None
    party: PartyPayload


class InvoiceLinePayload(BaseModel):
    line_no: int
    product_code: str | None = None
    product_name: str
    description: str | None = None
    item_type: str | None = None
    pkwiu_code: str | None = None
    cn_code: str | None = None
    unit_code: str | None = None
    quantity: Decimal = Decimal("1.000000")
    unit_price_net: Decimal = Decimal("0.000000")
    unit_price_gross: Decimal | None = None
    discount_percent: Decimal | None = None
    discount_amount: Decimal | None = None
    vat_rate: Decimal | None = None
    vat_code: str | None = None
    reverse_charge: bool = False
    tax_procedure_code: str | None = None
    tax_exemption_reason: str | None = None
    line_metadata: dict[str, Any] | None = None
    tax_flags: dict[str, Any] | None = None
    extra_data: dict[str, Any] | None = None


class InvoiceCreateRequest(BaseModel):
    tenant_id: str | None = None
    direction_code: str = "SALE"
    invoice_kind_code: str = "STANDARD"
    local_document_id: str | None = None
    external_system_id: str | None = None
    invoice_number: str
    issue_date: date
    sale_date: date | None = None
    receive_date: date | None = None
    due_date: date | None = None
    currency_code: str = "PLN"
    exchange_rate: Decimal | None = None
    payment_method: str | None = None
    payment_reference: str | None = None
    payment_account: str | None = None
    purchase_category: str | None = None
    source_system: str | None = None
    source_channel: str | None = None
    business_tags: dict[str, Any] | None = None
    fa_metadata: dict[str, Any] | None = None
    workflow_data: dict[str, Any] | None = None
    extra_data: dict[str, Any] | None = None
    parties: list[InvoicePartyPayload]
    lines: list[InvoiceLinePayload]


class InvoiceUpdateRequest(BaseModel):
    invoice_number: str | None = None
    issue_date: date | None = None
    sale_date: date | None = None
    receive_date: date | None = None
    due_date: date | None = None
    currency_code: str | None = None
    exchange_rate: Decimal | None = None
    payment_method: str | None = None
    payment_reference: str | None = None
    payment_account: str | None = None
    purchase_category: str | None = None
    business_tags: dict[str, Any] | None = None
    fa_metadata: dict[str, Any] | None = None
    workflow_data: dict[str, Any] | None = None
    extra_data: dict[str, Any] | None = None
    parties: list[InvoicePartyPayload] | None = None
    lines: list[InvoiceLinePayload] | None = None


class InvoiceApproveRequest(BaseModel):
    approved_by_user_id: int


class InvoiceValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []


class InvoiceLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    product_code: str | None = None
    product_name: str
    description: str | None = None
    item_type: str | None = None
    unit_code: str | None = None
    quantity: Decimal
    unit_price_net: Decimal
    unit_price_gross: Decimal | None = None
    discount_percent: Decimal | None = None
    discount_amount: Decimal | None = None
    net_amount: Decimal
    vat_rate: Decimal | None = None
    vat_code: str | None = None
    reverse_charge: bool
    tax_procedure_code: str | None = None
    tax_exemption_reason: str | None = None
    vat_amount: Decimal
    gross_amount: Decimal
    line_metadata: dict[str, Any] | None = None
    tax_flags: dict[str, Any] | None = None
    extra_data: dict[str, Any] | None = None


class PartyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    party_uuid: str
    party_type: str | None = None
    name_full: str
    name_short: str | None = None
    tax_id: str | None = None
    vat_eu_id: str | None = None
    regon: str | None = None
    krs: str | None = None
    country_code: str | None = None
    street: str | None = None
    building_no: str | None = None
    apartment_no: str | None = None
    city: str | None = None
    postal_code: str | None = None
    province: str | None = None
    email: str | None = None
    phone: str | None = None
    bank_account: str | None = None
    extra_data: dict[str, Any] | None = None


class InvoicePartyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role_code: str
    sequence_no: int
    role_details: dict[str, Any] | None = None
    party: PartyRead


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_uuid: str
    tenant_id: str | None = None
    direction_code: str
    invoice_kind_code: str
    local_document_id: str | None = None
    external_system_id: str | None = None
    invoice_number: str
    ksef_number: str | None = None
    ksef_reference_number: str | None = None
    issue_date: date
    sale_date: date | None = None
    receive_date: date | None = None
    due_date: date | None = None
    currency_code: str
    exchange_rate: Decimal | None = None
    payment_method: str | None = None
    payment_reference: str | None = None
    payment_account: str | None = None
    is_paid: bool
    paid_amount: Decimal
    net_total: Decimal
    vat_total: Decimal
    gross_total: Decimal
    rounding_amount: Decimal
    is_correction: bool
    corrected_invoice_number: str | None = None
    corrected_ksef_number: str | None = None
    correction_reason: str | None = None
    ksef_status_code: str
    accounting_status: str | None = None
    purchase_category: str | None = None
    erp_status: str | None = None
    review_status: str | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    accounting_marked_by: int | None = None
    accounting_marked_at: datetime | None = None
    accounting_notes: str | None = None
    accounting_qualified: bool | None = None
    accounting_batch_id: str | None = None
    notification_status: str | None = None
    notification_channel: str | None = None
    last_notification_at: datetime | None = None
    ksef_session_reference: str | None = None
    ksef_submission_timestamp: datetime | None = None
    ksef_acceptance_timestamp: datetime | None = None
    ksef_download_timestamp: datetime | None = None
    schema_version: str | None = None
    source_system: str | None = None
    source_channel: str | None = None
    xml_sha256: str | None = None
    business_tags: dict[str, Any] | None = None
    fa_metadata: dict[str, Any] | None = None
    workflow_data: dict[str, Any] | None = None
    extra_data: dict[str, Any] | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    parties: list[InvoicePartyRead] = []
    lines: list[InvoiceLineRead] = []


class InvoiceListQuery(BaseModel):
    direction_code: str | None = None
    ksef_status_code: str | None = None
    accounting_status: str | None = None
    erp_status: str | None = None
    review_status: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

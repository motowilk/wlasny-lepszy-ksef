import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape as xml_escape

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    IntegrationJob,
    Invoice,
    InvoiceEvent,
    InvoiceLine,
    InvoiceParty,
    InvoicePayload,
    InvoiceVatSummary,
    Party,
)
from app.schemas.invoice import (
    InvoiceApproveRequest,
    InvoiceCreateRequest,
    InvoiceLinePayload,
    InvoiceListQuery,
    InvoiceUpdateRequest,
)
from app.services.validation_service import ValidationService

TWOPLACES = Decimal("0.01")
SIXPLACES = Decimal("0.000001")


class InvoiceService:
    @staticmethod
    def create_invoice(
        db: Session,
        payload: InvoiceCreateRequest,
        actor_id: str | None = None,
    ) -> Invoice:
        invoice = Invoice(
            invoice_uuid=str(uuid.uuid4()),
            tenant_id=payload.tenant_id,
            direction_code=payload.direction_code,
            invoice_kind_code=payload.invoice_kind_code,
            local_document_id=payload.local_document_id,
            external_system_id=payload.external_system_id,
            invoice_number=payload.invoice_number,
            issue_date=payload.issue_date,
            sale_date=payload.sale_date,
            receive_date=payload.receive_date,
            due_date=payload.due_date,
            currency_code=payload.currency_code,
            exchange_rate=payload.exchange_rate,
            payment_method=payload.payment_method,
            payment_reference=payload.payment_reference,
            payment_account=payload.payment_account,
            purchase_category=payload.purchase_category,
            source_system=payload.source_system,
            source_channel=payload.source_channel,
            business_tags=payload.business_tags,
            fa_metadata=payload.fa_metadata,
            workflow_data=payload.workflow_data,
            extra_data=payload.extra_data,
            ksef_status_code="DRAFT",
            accounting_status="new",
            erp_status="DRAFT_CREATED",
            review_status="PENDING",
            notification_status="PENDING",
            notification_channel="EMAIL",
        )
        db.add(invoice)
        db.flush()

        InvoiceService._replace_parties(db, invoice, payload.parties)
        InvoiceService._replace_lines(db, invoice, payload.lines)
        InvoiceService._recalculate_invoice(invoice)
        InvoiceService._rebuild_vat_summary(db, invoice)

        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type="INVOICE_CREATED",
                event_status="SUCCESS",
                actor_type="USER" if actor_id else "SYSTEM",
                actor_id=actor_id,
                message="Utworzono draft faktury.",
                details={"direction_code": invoice.direction_code},
            )
        )

        db.commit()
        db.refresh(invoice)
        return InvoiceService.get_invoice(db, invoice.id)

    @staticmethod
    def list_invoices(db: Session, query: InvoiceListQuery) -> list[Invoice]:
        stmt = (
            select(Invoice)
            .options(
                joinedload(Invoice.parties).joinedload(InvoiceParty.party),
                joinedload(Invoice.lines),
            )
            .order_by(Invoice.id.desc())
            .limit(query.limit)
            .offset(query.offset)
        )

        if query.direction_code:
            stmt = stmt.where(Invoice.direction_code == query.direction_code)
        if query.ksef_status_code:
            stmt = stmt.where(Invoice.ksef_status_code == query.ksef_status_code)
        if query.accounting_status:
            stmt = stmt.where(Invoice.accounting_status == query.accounting_status)
        if query.erp_status:
            stmt = stmt.where(Invoice.erp_status == query.erp_status)
        if query.review_status:
            stmt = stmt.where(Invoice.review_status == query.review_status)

        return list(db.execute(stmt).unique().scalars().all())

    @staticmethod
    def get_invoice(db: Session, invoice_id: int) -> Invoice:
        stmt = (
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .options(
                joinedload(Invoice.parties).joinedload(InvoiceParty.party),
                joinedload(Invoice.lines),
                joinedload(Invoice.events),
                joinedload(Invoice.payloads),
                joinedload(Invoice.vat_summaries),
            )
        )
        invoice = db.execute(stmt).unique().scalar_one_or_none()
        if not invoice:
            raise ValueError(f"Invoice id={invoice_id} not found.")
        return invoice

    @staticmethod
    def update_invoice(
        db: Session,
        invoice_id: int,
        payload: InvoiceUpdateRequest,
        actor_id: str | None = None,
    ) -> Invoice:
        invoice = InvoiceService.get_invoice(db, invoice_id)

        if invoice.approved_at is not None:
            raise ValueError("Nie można edytować faktury po akceptacji.")

        for field in [
            "invoice_number",
            "issue_date",
            "sale_date",
            "receive_date",
            "due_date",
            "currency_code",
            "exchange_rate",
            "payment_method",
            "payment_reference",
            "payment_account",
            "purchase_category",
            "business_tags",
            "fa_metadata",
            "workflow_data",
            "extra_data",
        ]:
            value = getattr(payload, field)
            if value is not None:
                setattr(invoice, field, value)

        if payload.parties is not None:
            InvoiceService._replace_parties(db, invoice, payload.parties)

        if payload.lines is not None:
            InvoiceService._replace_lines(db, invoice, payload.lines)

        InvoiceService._recalculate_invoice(invoice)
        InvoiceService._rebuild_vat_summary(db, invoice)

        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type="INVOICE_UPDATED",
                event_status="SUCCESS",
                actor_type="USER" if actor_id else "SYSTEM",
                actor_id=actor_id,
                message="Zaktualizowano draft faktury.",
            )
        )

        db.commit()
        db.refresh(invoice)
        return InvoiceService.get_invoice(db, invoice.id)

    @staticmethod
    def validate_invoice(db: Session, invoice_id: int):
        invoice = InvoiceService.get_invoice(db, invoice_id)
        return ValidationService.validate_invoice(invoice)

    @staticmethod
    def approve_invoice(
        db: Session,
        invoice_id: int,
        payload: InvoiceApproveRequest,
        actor_id: str | None = None,
    ) -> Invoice:
        invoice = InvoiceService.get_invoice(db, invoice_id)

        if invoice.approved_at is not None:
            raise ValueError("Faktura jest już zaakceptowana.")

        validation_result = ValidationService.validate_invoice(invoice)
        if not validation_result.valid:
            raise ValueError(
                "Faktura nie przeszła walidacji: " + "; ".join(validation_result.errors)
            )

        xml_content = InvoiceService._generate_mock_xml(invoice)
        xml_hash = hashlib.sha256(xml_content.encode("utf-8")).hexdigest()

        invoice.approved_by = payload.approved_by_user_id
        invoice.approved_at = datetime.now(tz=timezone.utc)
        invoice.erp_status = "APPROVED"
        invoice.review_status = "APPROVED"
        invoice.ksef_status_code = "QUEUED"
        invoice.xml_sha256 = xml_hash
        invoice.notification_status = "PENDING"
        invoice.notification_channel = "EMAIL"

        db.add(
            InvoicePayload(
                invoice_id=invoice.id,
                payload_type_code="KSEF_XML",
                content_format="XML",
                content=xml_content,
                content_sha256=xml_hash,
                api_endpoint="/mock/ksef/send",
                transport_metadata={"mode": "mock"},
            )
        )

        job = IntegrationJob(
            job_uuid=str(uuid.uuid4()),
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            related_entity_type="INVOICE",
            related_entity_id=str(invoice.id),
            job_type="SEND_TO_KSEF",
            status="NEW",
            priority=100,
            attempts=0,
            max_attempts=5,
            request_payload={"invoice_id": invoice.id},
        )
        db.add(job)

        db.add(
            InvoiceEvent(
                invoice_id=invoice.id,
                event_type="INVOICE_APPROVED",
                event_status="SUCCESS",
                actor_type="USER",
                actor_id=str(actor_id or payload.approved_by_user_id),
                message="Faktura zaakceptowana i dodana do kolejki KSeF.",
                details={"job_type": "SEND_TO_KSEF"},
            )
        )

        db.commit()
        db.refresh(invoice)
        return InvoiceService.get_invoice(db, invoice.id)

    @staticmethod
    def _replace_parties(db: Session, invoice: Invoice, parties_payload) -> None:
        db.execute(delete(InvoiceParty).where(InvoiceParty.invoice_id == invoice.id))
        db.flush()

        for party_link in parties_payload:
            party = InvoiceService._get_or_create_party(db, party_link.party)
            db.add(
                InvoiceParty(
                    invoice_id=invoice.id,
                    party_id=party.id,
                    role_code=party_link.role_code,
                    sequence_no=party_link.sequence_no,
                    role_details=party_link.role_details,
                )
            )
        db.flush()

    @staticmethod
    def _get_or_create_party(db: Session, party_payload) -> Party:
        if party_payload.party_uuid:
            stmt = select(Party).where(Party.party_uuid == party_payload.party_uuid)
            existing = db.execute(stmt).scalar_one_or_none()
            if existing:
                InvoiceService._update_party(existing, party_payload)
                db.flush()
                return existing

        if party_payload.tax_id and party_payload.name_full:
            stmt = select(Party).where(
                Party.tax_id == party_payload.tax_id,
                Party.name_full == party_payload.name_full,
            )
            existing = db.execute(stmt).scalar_one_or_none()
            if existing:
                InvoiceService._update_party(existing, party_payload)
                db.flush()
                return existing

        party = Party(
            party_uuid=str(uuid.uuid4()),
            party_type=party_payload.party_type,
            name_full=party_payload.name_full,
            name_short=party_payload.name_short,
            tax_id=party_payload.tax_id,
            vat_eu_id=party_payload.vat_eu_id,
            regon=party_payload.regon,
            krs=party_payload.krs,
            country_code=party_payload.country_code,
            street=party_payload.street,
            building_no=party_payload.building_no,
            apartment_no=party_payload.apartment_no,
            city=party_payload.city,
            postal_code=party_payload.postal_code,
            province=party_payload.province,
            email=party_payload.email,
            phone=party_payload.phone,
            bank_account=party_payload.bank_account,
            extra_data=party_payload.extra_data,
        )
        db.add(party)
        db.flush()
        return party

    @staticmethod
    def _update_party(party: Party, party_payload) -> None:
        for field in [
            "party_type",
            "name_full",
            "name_short",
            "tax_id",
            "vat_eu_id",
            "regon",
            "krs",
            "country_code",
            "street",
            "building_no",
            "apartment_no",
            "city",
            "postal_code",
            "province",
            "email",
            "phone",
            "bank_account",
            "extra_data",
        ]:
            value = getattr(party_payload, field)
            if value is not None:
                setattr(party, field, value)

    @staticmethod
    def _replace_lines(
        db: Session,
        invoice: Invoice,
        lines_payload: list[InvoiceLinePayload],
    ) -> None:
        db.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id))
        db.flush()

        for line_payload in lines_payload:
            net_amount, vat_amount, gross_amount = InvoiceService._calculate_line_amounts(line_payload)
            db.add(
                InvoiceLine(
                    invoice_id=invoice.id,
                    line_no=line_payload.line_no,
                    product_code=line_payload.product_code,
                    product_name=line_payload.product_name,
                    description=line_payload.description,
                    item_type=line_payload.item_type,
                    pkwiu_code=line_payload.pkwiu_code,
                    cn_code=line_payload.cn_code,
                    unit_code=line_payload.unit_code,
                    quantity=line_payload.quantity.quantize(SIXPLACES),
                    unit_price_net=line_payload.unit_price_net.quantize(SIXPLACES),
                    unit_price_gross=(
                        line_payload.unit_price_gross.quantize(SIXPLACES)
                        if line_payload.unit_price_gross is not None
                        else None
                    ),
                    discount_percent=line_payload.discount_percent,
                    discount_amount=line_payload.discount_amount,
                    net_amount=net_amount,
                    vat_rate=line_payload.vat_rate,
                    vat_code=line_payload.vat_code,
                    reverse_charge=line_payload.reverse_charge,
                    tax_procedure_code=line_payload.tax_procedure_code,
                    tax_exemption_reason=line_payload.tax_exemption_reason,
                    vat_amount=vat_amount,
                    gross_amount=gross_amount,
                    line_metadata=line_payload.line_metadata,
                    tax_flags=line_payload.tax_flags,
                    extra_data=line_payload.extra_data,
                )
            )
        db.flush()

    @staticmethod
    def _calculate_line_amounts(line_payload: InvoiceLinePayload):
        quantity = Decimal(line_payload.quantity)
        unit_price_net = Decimal(line_payload.unit_price_net)
        discount_amount = Decimal(line_payload.discount_amount or Decimal("0.00"))
        discount_percent = Decimal(line_payload.discount_percent or Decimal("0.00"))
        vat_rate = Decimal(line_payload.vat_rate or Decimal("0.00"))

        if quantity <= 0:
            raise ValueError("quantity must be greater than 0")
        if unit_price_net < 0:
            raise ValueError("unit_price_net must be non-negative")
        if line_payload.unit_price_gross is not None and Decimal(line_payload.unit_price_gross) < 0:
            raise ValueError("unit_price_gross must be non-negative")
        if discount_amount < 0:
            raise ValueError("discount_amount must be non-negative")
        if discount_percent < 0 or discount_percent > 100:
            raise ValueError("discount_percent must be between 0 and 100")
        if vat_rate < 0:
            raise ValueError("vat_rate must be non-negative")

        base_net = (quantity * unit_price_net).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

        if discount_percent > 0:
            base_net = (
                base_net * (Decimal("1.00") - discount_percent / Decimal("100.00"))
            ).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

        if discount_amount > base_net:
            raise ValueError("discount_amount cannot exceed the line net amount")

        net_amount = (base_net - discount_amount).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

        if line_payload.reverse_charge or (
            line_payload.vat_code and line_payload.vat_code.upper() in {"NP", "ZW"}
        ):
            vat_amount = Decimal("0.00")
        else:
            vat_amount = (net_amount * vat_rate / Decimal("100.00")).quantize(
                TWOPLACES, rounding=ROUND_HALF_UP
            )

        gross_amount = (net_amount + vat_amount).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        return net_amount, vat_amount, gross_amount

    @staticmethod
    def _recalculate_invoice(invoice: Invoice) -> None:
        net_total = sum((Decimal(line.net_amount) for line in invoice.lines), Decimal("0.00"))
        vat_total = sum((Decimal(line.vat_amount) for line in invoice.lines), Decimal("0.00"))
        gross_total = sum((Decimal(line.gross_amount) for line in invoice.lines), Decimal("0.00"))

        invoice.net_total = net_total.quantize(TWOPLACES)
        invoice.vat_total = vat_total.quantize(TWOPLACES)
        invoice.gross_total = gross_total.quantize(TWOPLACES)
        invoice.rounding_amount = Decimal("0.00")

    @staticmethod
    def _rebuild_vat_summary(db: Session, invoice: Invoice) -> None:
        db.execute(delete(InvoiceVatSummary).where(InvoiceVatSummary.invoice_id == invoice.id))
        db.flush()

        grouped: dict[tuple[str | None, Decimal | None], dict[str, Decimal]] = {}

        for line in invoice.lines:
            key = (
                line.vat_code,
                Decimal(line.vat_rate) if line.vat_rate is not None else None,
            )
            if key not in grouped:
                grouped[key] = {
                    "net_amount": Decimal("0.00"),
                    "vat_amount": Decimal("0.00"),
                    "gross_amount": Decimal("0.00"),
                }
            grouped[key]["net_amount"] += Decimal(line.net_amount)
            grouped[key]["vat_amount"] += Decimal(line.vat_amount)
            grouped[key]["gross_amount"] += Decimal(line.gross_amount)

        for (vat_code, vat_rate), amounts in grouped.items():
            db.add(
                InvoiceVatSummary(
                    invoice_id=invoice.id,
                    vat_code=vat_code or "UNSPECIFIED",
                    vat_rate=vat_rate,
                    net_amount=amounts["net_amount"].quantize(TWOPLACES),
                    vat_amount=amounts["vat_amount"].quantize(TWOPLACES),
                    gross_amount=amounts["gross_amount"].quantize(TWOPLACES),
                )
            )
        db.flush()

    @staticmethod
    def _generate_mock_xml(invoice: Invoice) -> str:
        seller = next((p for p in invoice.parties if p.role_code == "SELLER"), None)
        buyer = next((p for p in invoice.parties if p.role_code == "BUYER"), None)

        lines_xml = []
        for line in sorted(invoice.lines, key=lambda x: x.line_no):
            lines_xml.append(
                f"    <Line>\n"
                f"      <LineNo>{line.line_no}</LineNo>\n"
                f"      <ProductName>{xml_escape(line.product_name or '')}</ProductName>\n"
                f"      <Quantity>{line.quantity}</Quantity>\n"
                f"      <UnitPriceNet>{line.unit_price_net}</UnitPriceNet>\n"
                f"      <VatCode>{xml_escape(line.vat_code or '')}</VatCode>\n"
                f"      <VatRate>{line.vat_rate if line.vat_rate is not None else ''}</VatRate>\n"
                f"      <NetAmount>{line.net_amount}</NetAmount>\n"
                f"      <VatAmount>{line.vat_amount}</VatAmount>\n"
                f"      <GrossAmount>{line.gross_amount}</GrossAmount>\n"
                f"    </Line>"
            )

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Invoice>\n"
            "  <Header>\n"
            f"    <InvoiceNumber>{xml_escape(invoice.invoice_number)}</InvoiceNumber>\n"
            f"    <IssueDate>{invoice.issue_date}</IssueDate>\n"
            f"    <Currency>{xml_escape(invoice.currency_code)}</Currency>\n"
            f"    <SchemaVersion>{xml_escape(invoice.schema_version or 'FA(3)')}</SchemaVersion>\n"
            "  </Header>\n"
            "  <Seller>\n"
            f"    <Name>{xml_escape(seller.party.name_full if seller and seller.party else '')}</Name>\n"
            f"    <TaxId>{xml_escape(seller.party.tax_id if seller and seller.party.tax_id else '')}</TaxId>\n"
            "  </Seller>\n"
            "  <Buyer>\n"
            f"    <Name>{xml_escape(buyer.party.name_full if buyer and buyer.party else '')}</Name>\n"
            f"    <TaxId>{xml_escape(buyer.party.tax_id if buyer and buyer.party.tax_id else '')}</TaxId>\n"
            "  </Buyer>\n"
            "  <Totals>\n"
            f"    <NetTotal>{invoice.net_total}</NetTotal>\n"
            f"    <VatTotal>{invoice.vat_total}</VatTotal>\n"
            f"    <GrossTotal>{invoice.gross_total}</GrossTotal>\n"
            "  </Totals>\n"
            "  <Lines>\n"
            + "\n".join(lines_xml) + "\n"
            "  </Lines>\n"
            "</Invoice>\n"
        )

    @staticmethod
    def create_event(
        db: Session,
        invoice_id: int,
        event_type: str,
        event_status: str,
        actor_type: str | None = None,
        actor_id: str | None = None,
        message: str | None = None,
        details: dict | None = None,
    ) -> None:
        db.add(
            InvoiceEvent(
                invoice_id=invoice_id,
                event_type=event_type,
                event_status=event_status,
                actor_type=actor_type,
                actor_id=actor_id,
                message=message,
                details=details,
            )
        )
        db.flush()

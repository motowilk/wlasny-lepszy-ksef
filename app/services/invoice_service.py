import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from lxml import etree as lxml_etree
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
from app.adapters.notification.discord import DiscordNotificationAdapter
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

        if invoice.direction_code == "SALE":
            buyer_name = ""
            for ip in invoice.parties:
                if ip.role_code == "BUYER":
                    buyer_name = ip.party.name_full if ip.party else ""
                    break
            DiscordNotificationAdapter().send(
                f"Utworzono fakturę sprzedażową {invoice.invoice_number}, dla {buyer_name}"
            )

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

        xml_content = InvoiceService._generate_fa3_xml(invoice)

        xsd_errors = ValidationService.validate_ksef_xml(xml_content)
        if xsd_errors:
            raise ValueError(
                "XML nie przeszedł walidacji XSD: " + "; ".join(xsd_errors[:5])
            )

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
                api_endpoint="/api/online/Send/Invoices",
                transport_metadata={"schema": "FA(3)", "version": "1-0E"},
            )
        )

        job = IntegrationJob(
            job_uuid=str(uuid.uuid4()),
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            related_entity_type="INVOICE",
            related_entity_id=str(invoice.id),
            job_type="SEND_TO_KSEF",
            status="PROCESSING",
            priority=100,
            attempts=1,
            max_attempts=5,
            started_at=datetime.now(tz=timezone.utc),
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
                message="Faktura zaakceptowana — wysyłka do KSeF.",
                details={"job_type": "SEND_TO_KSEF"},
            )
        )

        db.flush()

        from app.services.ksef_service import KsefService
        try:
            KsefService.process_send_to_ksef_job(db, job)
        except Exception as exc:
            db.rollback()

            # Re-fetch after rollback — the flushed approval data is gone
            invoice = InvoiceService.get_invoice(db, invoice_id)
            invoice.approved_by = payload.approved_by_user_id
            invoice.approved_at = datetime.now(tz=timezone.utc)
            invoice.erp_status = "APPROVED"
            invoice.review_status = "APPROVED"
            invoice.ksef_status_code = "QUEUED"
            invoice.xml_sha256 = xml_hash
            invoice.notification_status = "PENDING"
            invoice.notification_channel = "EMAIL"

            # Persist the XML payload again (lost in rollback)
            db.add(
                InvoicePayload(
                    invoice_id=invoice.id,
                    payload_type_code="KSEF_XML",
                    content_format="XML",
                    content=xml_content,
                    content_sha256=xml_hash,
                    api_endpoint="/api/online/Send/Invoices",
                    transport_metadata={"schema": "FA(3)", "version": "1-0E"},
                )
            )

            failed_job = IntegrationJob(
                job_uuid=str(uuid.uuid4()),
                tenant_id=invoice.tenant_id,
                invoice_id=invoice.id,
                related_entity_type="INVOICE",
                related_entity_id=str(invoice.id),
                job_type="SEND_TO_KSEF",
                status="FAILED",
                priority=100,
                attempts=1,
                max_attempts=5,
                started_at=datetime.now(tz=timezone.utc),
                finished_at=datetime.now(tz=timezone.utc),
                last_error_message=str(exc),
                request_payload={"invoice_id": invoice.id},
            )
            db.add(failed_job)

            db.add(
                InvoiceEvent(
                    invoice_id=invoice.id,
                    event_type="KSEF_SEND_FAILED",
                    event_status="FAILURE",
                    actor_type="SYSTEM",
                    actor_id="approve_invoice",
                    message=f"Wysyłka do KSeF nie powiodła się: {exc}",
                    details={"error": str(exc)},
                )
            )

            db.commit()
            raise RuntimeError(f"Wysyłka do KSeF nie powiodła się: {exc}") from exc

        job.status = "DONE"
        job.finished_at = datetime.now(tz=timezone.utc)

        db.commit()
        db.refresh(invoice)
        return InvoiceService.get_invoice(db, invoice.id)

    @staticmethod
    def retry_ksef_send(
        db: Session,
        invoice_id: int,
        actor_id: str | None = None,
    ) -> Invoice:
        invoice = InvoiceService.get_invoice(db, invoice_id)

        if not invoice.approved_at:
            raise ValueError("Faktura nie jest zaakceptowana.")

        if invoice.ksef_status_code != "QUEUED":
            raise ValueError(
                f"Ponowna wysyłka możliwa tylko dla statusu 'W kolejce' "
                f"(obecny: {invoice.ksef_status_code})."
            )

        xml_payload = db.scalars(
            select(InvoicePayload)
            .where(
                InvoicePayload.invoice_id == invoice.id,
                InvoicePayload.payload_type_code == "KSEF_XML",
            )
            .order_by(InvoicePayload.id.desc())
            .limit(1)
        ).first()
        if not xml_payload:
            raise ValueError("Brak payloadu XML dla faktury.")

        job = IntegrationJob(
            job_uuid=str(uuid.uuid4()),
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            related_entity_type="INVOICE",
            related_entity_id=str(invoice.id),
            job_type="SEND_TO_KSEF",
            status="PROCESSING",
            priority=100,
            attempts=1,
            max_attempts=5,
            started_at=datetime.now(tz=timezone.utc),
            request_payload={"invoice_id": invoice.id},
        )
        db.add(job)
        db.flush()

        from app.services.ksef_service import KsefService
        try:
            KsefService.process_send_to_ksef_job(db, job)
        except Exception as exc:
            db.rollback()

            invoice = InvoiceService.get_invoice(db, invoice_id)
            invoice.ksef_status_code = "QUEUED"
            invoice.erp_status = "APPROVED"

            failed_job = IntegrationJob(
                job_uuid=str(uuid.uuid4()),
                tenant_id=invoice.tenant_id,
                invoice_id=invoice.id,
                related_entity_type="INVOICE",
                related_entity_id=str(invoice.id),
                job_type="SEND_TO_KSEF",
                status="FAILED",
                priority=100,
                attempts=1,
                max_attempts=5,
                started_at=datetime.now(tz=timezone.utc),
                finished_at=datetime.now(tz=timezone.utc),
                last_error_message=str(exc),
                request_payload={"invoice_id": invoice.id},
            )
            db.add(failed_job)

            db.add(
                InvoiceEvent(
                    invoice_id=invoice.id,
                    event_type="KSEF_SEND_FAILED",
                    event_status="FAILURE",
                    actor_type="USER",
                    actor_id=actor_id or "unknown",
                    message=f"Ponowna wysyłka do KSeF nie powiodła się: {exc}",
                    details={"error": str(exc)},
                )
            )

            db.commit()
            raise RuntimeError(f"Wysyłka do KSeF nie powiodła się: {exc}") from exc

        job.status = "DONE"
        job.finished_at = datetime.now(tz=timezone.utc)

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
    def _generate_fa3_xml(invoice: Invoice) -> str:
        """Generate a KSeF-compliant FA(3) v1-0E XML document for the invoice."""
        FA3_NS = "http://crd.gov.pl/wzor/2025/06/25/13775/"
        NSMAP = {None: FA3_NS}

        def _sub(parent, tag, text=None, attrib=None):
            el = lxml_etree.SubElement(parent, f"{{{FA3_NS}}}{tag}", attrib or {})
            if text is not None:
                el.text = str(text)
            return el

        def _fmt(val) -> str:
            """Format as TKwotowy (up to 2 decimal places)."""
            return str(Decimal(str(val)).quantize(TWOPLACES))

        def _fmt6(val) -> str:
            """Format as TIlosci / TKwotowy2 (up to 6 significant decimal places)."""
            s = str(Decimal(str(val)).quantize(Decimal("0.000001"))).rstrip("0").rstrip(".")
            return s if s else "0"

        def _build_addr_l1(party) -> str:
            parts = []
            if party.street:
                street_part = party.street
                if party.building_no:
                    street_part += f" {party.building_no}"
                    if party.apartment_no:
                        street_part += f"/{party.apartment_no}"
                parts.append(street_part)
            if party.postal_code and party.city:
                parts.append(f"{party.postal_code} {party.city}")
            elif party.city:
                parts.append(party.city)
            if parts:
                return ", ".join(parts)
            return (party.extra_data or {}).get("address_l1", "")

        # P_12 per-line VAT code → TStawkaPodatku
        P12_MAP: dict[str, str] = {
            "23": "23", "22": "22", "8": "8", "7": "7",
            "5": "5", "4": "4", "3": "3",
            "0": "0", "0 KR": "0", "0 WDT": "0", "0 EX": "0",
            "zw": "zw", "oo": "oo",
            "np": "np", "np I": "np", "np II": "np",
            "oss": "oss",
        }

        # vat_code → P_13 bucket key
        VAT_CODE_TO_P13: dict[str, str] = {
            "23": "1", "22": "1",
            "8": "2", "7": "2",
            "5": "3",
            "0": "6_1", "0 KR": "6_1",
            "0 WDT": "6_2",
            "0 EX": "6_3",
            "zw": "7",
            "np": "8", "np I": "8",
            "np II": "9",
            "oo": "10",
        }
        # P_13 buckets with paired P_14 (these have non-zero VAT rates)
        HAS_P14 = {"1", "2", "3"}

        # Aggregate P_13 / P_14 totals
        p13_nets: dict[str, Decimal] = {}
        p13_vats: dict[str, Decimal] = {}
        has_zw = False
        has_oo = False
        for line in invoice.lines:
            code = (line.vat_code or "").strip()
            key = VAT_CODE_TO_P13.get(code, "10")
            p13_nets[key] = p13_nets.get(key, Decimal("0")) + Decimal(str(line.net_amount))
            if key in HAS_P14:
                p13_vats[key] = p13_vats.get(key, Decimal("0")) + Decimal(str(line.vat_amount))
            if code == "zw":
                has_zw = True
            if code == "oo":
                has_oo = True

        fa_meta: dict = invoice.fa_metadata or {}

        # ── Root ──────────────────────────────────────────────────────────────
        root = lxml_etree.Element(f"{{{FA3_NS}}}Faktura", nsmap=NSMAP)

        # ── Naglowek ──────────────────────────────────────────────────────────
        nagl = _sub(root, "Naglowek")
        kf = _sub(nagl, "KodFormularza", "FA",
                  attrib={"kodSystemowy": "FA (3)", "wersjaSchemy": "1-0E"})  # noqa: F841
        _sub(nagl, "WariantFormularza", "3")
        _sub(nagl, "DataWytworzeniaFa",
             datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000Z"))
        _sub(nagl, "SystemInfo", "KSeF-App v1.0")

        # ── Podmiot1 (seller) ─────────────────────────────────────────────────
        seller_link = next((p for p in invoice.parties if p.role_code == "SELLER"), None)
        seller = seller_link.party if seller_link else None

        p1 = _sub(root, "Podmiot1")
        # PrefiksPodatnika fixed="PL" for Polish sellers
        if not seller or not seller.country_code or seller.country_code == "PL":
            _sub(p1, "PrefiksPodatnika", "PL")
        di1 = _sub(p1, "DaneIdentyfikacyjne")
        seller_nip = (seller.tax_id or "").strip() if seller else ""
        if not seller_nip:
            raise ValueError("Sprzedawca (Podmiot1) musi mieć wypełniony NIP.")
        _sub(di1, "NIP", seller_nip)
        _sub(di1, "Nazwa", (seller.name_full or "") if seller else "")
        addr_l1 = _build_addr_l1(seller) if seller else ""
        adres1 = _sub(p1, "Adres")
        _sub(adres1, "KodKraju",
             (seller.country_code or "PL") if seller else "PL")
        _sub(adres1, "AdresL1", addr_l1 or (seller.name_full if seller else ""))

        # ── Podmiot2 (buyer) ──────────────────────────────────────────────────
        buyer_link = next((p for p in invoice.parties if p.role_code == "BUYER"), None)
        buyer = buyer_link.party if buyer_link else None

        p2 = _sub(root, "Podmiot2")
        di2 = _sub(p2, "DaneIdentyfikacyjne")
        if buyer:
            bp = buyer
            if bp.vat_eu_id:
                vat_eu_raw = bp.vat_eu_id.strip()
                # Strip country code prefix (2 letters) from vat_eu_id for NrVatUE
                if len(vat_eu_raw) > 2 and vat_eu_raw[:2].isalpha():
                    kod_ue = vat_eu_raw[:2].upper()
                    nr_vat_ue = vat_eu_raw[2:]
                else:
                    kod_ue = bp.country_code or ""
                    nr_vat_ue = vat_eu_raw
                _sub(di2, "KodUE", kod_ue)
                _sub(di2, "NrVatUE", nr_vat_ue)
                _sub(di2, "Nazwa", bp.name_full or "")
            elif bp.tax_id and (not bp.country_code or bp.country_code == "PL"):
                _sub(di2, "NIP", bp.tax_id)
                _sub(di2, "Nazwa", bp.name_full or "")
            elif bp.tax_id:
                _sub(di2, "KodKraju", bp.country_code or "")
                _sub(di2, "NrID", bp.tax_id)
                _sub(di2, "Nazwa", bp.name_full or "")
            else:
                _sub(di2, "BrakID", "1")
                if bp.name_full:
                    _sub(di2, "Nazwa", bp.name_full)
        else:
            _sub(di2, "BrakID", "1")

        # Optional buyer address
        buyer_addr = _build_addr_l1(buyer) if buyer else ""
        if buyer_addr and buyer:
            adres2 = _sub(p2, "Adres")
            _sub(adres2, "KodKraju", buyer.country_code or "PL")
            _sub(adres2, "AdresL1", buyer_addr)

        _sub(p2, "JST", "2")  # not a public finance sector entity
        _sub(p2, "GV", "2")   # not a private individual

        # ── Fa ────────────────────────────────────────────────────────────────
        fa = _sub(root, "Fa")
        _sub(fa, "KodWaluty", invoice.currency_code or "PLN")
        _sub(fa, "P_1", str(invoice.issue_date))
        if fa_meta.get("issue_place"):
            _sub(fa, "P_1M", fa_meta["issue_place"])
        _sub(fa, "P_2", invoice.invoice_number or "")
        if invoice.sale_date:
            _sub(fa, "P_6", str(invoice.sale_date))

        # P_13 totals (standard VAT rates — have paired P_14)
        for key in ("1", "2", "3"):
            if key in p13_nets:
                _sub(fa, f"P_13_{key}", _fmt(p13_nets[key]))
                _sub(fa, f"P_14_{key}", _fmt(p13_vats.get(key, Decimal("0"))))

        # P_13 totals (zero / exempt / special — no paired P_14)
        for key in ("6_1", "6_2", "6_3", "7", "8", "9", "10", "11"):
            tag = f"P_13_{key}"
            if key in p13_nets:
                _sub(fa, tag, _fmt(p13_nets[key]))

        _sub(fa, "P_15", _fmt(invoice.gross_total))

        # Exchange rate annotation (only when currency ≠ PLN and rate provided)
        if invoice.currency_code and invoice.currency_code != "PLN" and invoice.exchange_rate:
            _sub(fa, "KursWalutyZ", _fmt6(invoice.exchange_rate))

        # ── Adnotacje ─────────────────────────────────────────────────────────
        adn = _sub(fa, "Adnotacje")
        _sub(adn, "P_16", "2")   # no self-billing
        _sub(adn, "P_17", "2")   # no cash-accounting method
        _sub(adn, "P_18", "2")   # no split payment
        _sub(adn, "P_18A", "2")  # no mandatory split payment
        # Zwolnienie: P_19=1 + P_19A (legal basis) if zw lines, else P_19N=1
        zwol = _sub(adn, "Zwolnienie")
        if has_zw:
            _sub(zwol, "P_19", "1")
            _sub(zwol, "P_19A", fa_meta.get("tax_exemption_basis", "art. 43 ust. 1"))
        else:
            _sub(zwol, "P_19N", "1")
        # NoweSrodkiTransportu: P_22N=1 (not new transport means)
        nst = _sub(adn, "NoweSrodkiTransportu")
        _sub(nst, "P_22N", "1")
        _sub(adn, "P_23", "2")  # not a tourist service
        # PMarzy
        pmarzy = _sub(adn, "PMarzy")
        _sub(pmarzy, "P_PMarzyN", "1")

        _sub(fa, "RodzajFaktury", "VAT")

        # ── FaWiersz (invoice lines) ──────────────────────────────────────────
        for line in sorted(invoice.lines, key=lambda x: x.line_no):
            fw = _sub(fa, "FaWiersz")
            _sub(fw, "NrWierszaFa", str(line.line_no))
            if line.product_name:
                _sub(fw, "P_7", line.product_name)
            if line.unit_code:
                _sub(fw, "P_8A", line.unit_code)
            _sub(fw, "P_8B", _fmt6(line.quantity))
            _sub(fw, "P_9A", _fmt6(line.unit_price_net))
            _sub(fw, "P_11", _fmt(line.net_amount))
            vat_code_raw = (line.vat_code or "").strip()
            p12_val = P12_MAP.get(vat_code_raw)
            if p12_val:
                _sub(fw, "P_12", p12_val)
            # Per-line exchange rate (foreign currency invoices)
            line_meta = line.line_metadata or {}
            if line_meta.get("exchange_rate"):
                _sub(fw, "KursWaluty", _fmt6(line_meta["exchange_rate"]))
            elif invoice.currency_code and invoice.currency_code != "PLN" and invoice.exchange_rate:
                _sub(fw, "KursWaluty", _fmt6(invoice.exchange_rate))

        # ── Platnosc ──────────────────────────────────────────────────────────
        has_payment_info = (
            invoice.due_date or invoice.payment_method or invoice.payment_account
        )
        if has_payment_info:
            platnosc = _sub(fa, "Platnosc")
            if invoice.due_date:
                tp = _sub(platnosc, "TerminPlatnosci")
                _sub(tp, "Termin", str(invoice.due_date))
            if invoice.payment_method:
                _sub(platnosc, "FormaPlatnosci", str(invoice.payment_method))
            if invoice.payment_account:
                rb = _sub(platnosc, "RachunekBankowy")
                _sub(rb, "NrRB", invoice.payment_account)
                if fa_meta.get("payment_swift"):
                    _sub(rb, "SWIFT", fa_meta["payment_swift"])
                if fa_meta.get("payment_bank_name"):
                    _sub(rb, "NazwaBanku", fa_meta["payment_bank_name"])

        # ── WarunkiTransakcji ─────────────────────────────────────────────────
        contract_date = fa_meta.get("contract_date")
        contract_number = fa_meta.get("contract_number")
        if contract_date or contract_number:
            wt = _sub(fa, "WarunkiTransakcji")
            umowy = _sub(wt, "Umowy")
            if contract_date:
                _sub(umowy, "DataUmowy", contract_date)
            if contract_number:
                _sub(umowy, "NrUmowy", contract_number)

        # ── Stopka ────────────────────────────────────────────────────────────
        footer_note = fa_meta.get("footer_note")
        if footer_note:
            stopka = _sub(root, "Stopka")
            info = _sub(stopka, "Informacje")
            _sub(info, "StopkaFaktury", footer_note)

        xml_bytes = lxml_etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=True
        )
        return xml_bytes.decode("utf-8")

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

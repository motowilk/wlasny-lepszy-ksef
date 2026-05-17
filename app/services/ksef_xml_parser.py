"""Parse FA(3) v1-0E XML (KSeF invoice format) into InvoiceCreateRequest."""

from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import etree

from app.schemas.invoice import (
    InvoiceCreateRequest,
    InvoiceLinePayload,
    InvoicePartyPayload,
    PartyPayload,
)

FA3_NS = "http://crd.gov.pl/wzor/2025/06/25/13775/"

_SAFE_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    dtd_validation=False,
    load_dtd=False,
)


def _ns(tag: str) -> str:
    return f"{{{FA3_NS}}}{tag}"


def _text(parent, tag: str) -> str | None:
    """Get text content of a direct child element, or None."""
    el = parent.find(_ns(tag))
    if el is not None and el.text:
        return el.text.strip()
    return None


def _decimal(parent, tag: str) -> Decimal | None:
    t = _text(parent, tag)
    if t is None:
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def _date(parent, tag: str) -> date | None:
    t = _text(parent, tag)
    if t is None:
        return None
    try:
        return date.fromisoformat(t[:10])
    except (ValueError, TypeError):
        return None


# Map P_12 values to (vat_rate Decimal, vat_code str)
_P12_TO_VAT: dict[str, tuple[Decimal | None, str]] = {
    "23": (Decimal("23"), "23"),
    "22": (Decimal("22"), "22"),
    "8": (Decimal("8"), "8"),
    "7": (Decimal("7"), "7"),
    "5": (Decimal("5"), "5"),
    "4": (Decimal("4"), "4"),
    "3": (Decimal("3"), "3"),
    "0": (Decimal("0"), "0"),
    "zw": (None, "zw"),
    "oo": (None, "oo"),
    "np": (None, "np"),
    "oss": (None, "oss"),
}


def _parse_party_podmiot1(podmiot1) -> PartyPayload:
    """Parse Podmiot1 (seller) into PartyPayload."""
    di = podmiot1.find(_ns("DaneIdentyfikacyjne"))
    adres = podmiot1.find(_ns("Adres"))

    nip = _text(di, "NIP") if di is not None else None
    nazwa = _text(di, "Nazwa") if di is not None else None

    country_code = _text(adres, "KodKraju") if adres is not None else None
    addr_l1 = _text(adres, "AdresL1") if adres is not None else None
    addr_l2 = _text(adres, "AdresL2") if adres is not None else None
    full_addr = " ".join(filter(None, [addr_l1, addr_l2]))

    return PartyPayload(
        name_full=nazwa or "",
        tax_id=nip,
        country_code=country_code or "PL",
        street=full_addr or None,
    )


def _parse_party_podmiot2(podmiot2) -> PartyPayload:
    """Parse Podmiot2 (buyer) into PartyPayload."""
    di = podmiot2.find(_ns("DaneIdentyfikacyjne"))
    adres = podmiot2.find(_ns("Adres"))

    nip = _text(di, "NIP") if di is not None else None
    kod_ue = _text(di, "KodUE") if di is not None else None
    nr_vat_ue = _text(di, "NrVatUE") if di is not None else None
    kod_kraju_id = _text(di, "KodKraju") if di is not None else None
    nr_id = _text(di, "NrID") if di is not None else None
    nazwa = _text(di, "Nazwa") if di is not None else None

    country_code = None
    tax_id = nip
    vat_eu_id = None

    if kod_ue and nr_vat_ue:
        country_code = kod_ue
        vat_eu_id = f"{kod_ue}{nr_vat_ue}"
    elif nip:
        country_code = "PL"
        tax_id = nip
    elif kod_kraju_id and nr_id:
        country_code = kod_kraju_id
        tax_id = nr_id

    # Address from Adres element
    addr_country = _text(adres, "KodKraju") if adres is not None else None
    addr_l1 = _text(adres, "AdresL1") if adres is not None else None
    addr_l2 = _text(adres, "AdresL2") if adres is not None else None
    full_addr = " ".join(filter(None, [addr_l1, addr_l2]))

    if not country_code and addr_country:
        country_code = addr_country

    return PartyPayload(
        name_full=nazwa or "",
        tax_id=tax_id,
        vat_eu_id=vat_eu_id,
        country_code=country_code,
        street=full_addr or None,
    )


def _parse_lines(fa_el) -> list[InvoiceLinePayload]:
    """Parse all FaWiersz elements into line payloads."""
    lines: list[InvoiceLinePayload] = []
    for wiersz in fa_el.findall(_ns("FaWiersz")):
        line_no_str = _text(wiersz, "NrWierszaFa")
        line_no = int(line_no_str) if line_no_str else len(lines) + 1

        product_name = _text(wiersz, "P_7") or ""
        unit_code = _text(wiersz, "P_8A")
        quantity = _decimal(wiersz, "P_8B") or Decimal("1")
        unit_price_net = _decimal(wiersz, "P_9A") or Decimal("0")
        # P_9B is unit price gross (optional)
        net_amount = _decimal(wiersz, "P_11") or (quantity * unit_price_net)
        vat_code_raw = _text(wiersz, "P_12") or "23"
        kurs_waluty = _text(wiersz, "KursWaluty")

        vat_rate, vat_code = _P12_TO_VAT.get(vat_code_raw, (Decimal("23"), "23"))

        line_metadata: dict | None = None
        if kurs_waluty:
            line_metadata = {"exchange_rate": kurs_waluty}

        lines.append(
            InvoiceLinePayload(
                line_no=line_no,
                product_name=product_name,
                unit_code=unit_code,
                quantity=quantity,
                unit_price_net=unit_price_net,
                vat_rate=vat_rate,
                vat_code=vat_code,
                line_metadata=line_metadata,
            )
        )
    return lines


def parse_fa3_xml(xml_content: str, direction_code: str = "PURCHASE") -> InvoiceCreateRequest:
    """
    Parse a KSeF FA(3) v1-0E XML document into an InvoiceCreateRequest.

    Args:
        xml_content: Full XML string of the FA(3) invoice.
        direction_code: "PURCHASE" or "SALE" depending on context.

    Returns:
        InvoiceCreateRequest ready to be passed to InvoiceService.create_invoice().
    """
    root = etree.fromstring(
        xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content,
        parser=_SAFE_PARSER,
    )

    # ── Podmiot1 (seller) ─────────────────────────────────────────────────
    podmiot1 = root.find(_ns("Podmiot1"))
    if podmiot1 is None:
        raise ValueError("Brak elementu Podmiot1 w XML.")
    seller_payload = _parse_party_podmiot1(podmiot1)

    # ── Podmiot2 (buyer) ──────────────────────────────────────────────────
    podmiot2 = root.find(_ns("Podmiot2"))
    if podmiot2 is None:
        raise ValueError("Brak elementu Podmiot2 w XML.")
    buyer_payload = _parse_party_podmiot2(podmiot2)

    # ── Fa (invoice body) ─────────────────────────────────────────────────
    fa_el = root.find(_ns("Fa"))
    if fa_el is None:
        raise ValueError("Brak elementu Fa w XML.")

    currency_code = _text(fa_el, "KodWaluty") or "PLN"
    issue_date = _date(fa_el, "P_1")
    if not issue_date:
        raise ValueError("Brak daty wystawienia (P_1) w XML.")
    issue_place = _text(fa_el, "P_1M")
    invoice_number = _text(fa_el, "P_2") or ""
    sale_date = _date(fa_el, "P_6")

    # ── Payment ───────────────────────────────────────────────────────────
    platnosc = fa_el.find(_ns("Platnosc"))
    due_date: date | None = None
    payment_method: str | None = None
    payment_account: str | None = None
    payment_swift: str | None = None
    payment_bank_name: str | None = None

    if platnosc is not None:
        termin_el = platnosc.find(_ns("TerminPlatnosci"))
        if termin_el is not None:
            due_date = _date(termin_el, "Termin")
        payment_method = _text(platnosc, "FormaPlatnosci")
        rachunek = platnosc.find(_ns("RachunekBankowy"))
        if rachunek is not None:
            payment_account = _text(rachunek, "NrRB")
            payment_swift = _text(rachunek, "SWIFT")
            payment_bank_name = _text(rachunek, "NazwaBanku")

    # ── Lines ─────────────────────────────────────────────────────────────
    lines = _parse_lines(fa_el)
    if not lines:
        raise ValueError("Brak pozycji (FaWiersz) w XML.")

    # ── WarunkiTransakcji ─────────────────────────────────────────────────
    fa_metadata: dict = {}
    if issue_place:
        fa_metadata["issue_place"] = issue_place
    if payment_swift:
        fa_metadata["payment_swift"] = payment_swift
    if payment_bank_name:
        fa_metadata["payment_bank_name"] = payment_bank_name

    warunki = fa_el.find(_ns("WarunkiTransakcji"))
    if warunki is not None:
        umowy = warunki.find(_ns("Umowy"))
        if umowy is not None:
            data_umowy = _text(umowy, "DataUmowy")
            nr_umowy = _text(umowy, "NrUmowy")
            if data_umowy:
                fa_metadata["contract_date"] = data_umowy
            if nr_umowy:
                fa_metadata["contract_number"] = nr_umowy

    # ── Stopka ────────────────────────────────────────────────────────────
    stopka = root.find(_ns("Stopka"))
    if stopka is not None:
        info = stopka.find(_ns("Informacje"))
        if info is not None:
            footer = _text(info, "StopkaFaktury")
            if footer:
                fa_metadata["footer_note"] = footer

    # ── Exchange rate (header-level from first line if uniform) ───────────
    exchange_rate: Decimal | None = None
    if currency_code != "PLN" and lines:
        first_exr = (lines[0].line_metadata or {}).get("exchange_rate")
        if first_exr:
            all_same = all(
                (ln.line_metadata or {}).get("exchange_rate") == first_exr
                for ln in lines
            )
            if all_same:
                try:
                    exchange_rate = Decimal(first_exr)
                except InvalidOperation:
                    pass

    # ── Assemble parties ──────────────────────────────────────────────────
    seller_party = InvoicePartyPayload(
        role_code="SELLER", sequence_no=1, party=seller_payload
    )
    buyer_party = InvoicePartyPayload(
        role_code="BUYER", sequence_no=1, party=buyer_payload
    )

    # ── Invoice kind ──────────────────────────────────────────────────────
    rodzaj = _text(fa_el, "RodzajFaktury") or "VAT"
    kind_map = {
        "VAT": "STANDARD",
        "KOR": "CORRECTION",
        "ZAL": "ADVANCE",
        "KOR_ZAL": "CORRECTION",
        "UPR": "STANDARD",
    }
    invoice_kind_code = kind_map.get(rodzaj, "STANDARD")

    return InvoiceCreateRequest(
        direction_code=direction_code,
        invoice_kind_code=invoice_kind_code,
        invoice_number=invoice_number,
        issue_date=issue_date,
        sale_date=sale_date,
        due_date=due_date,
        currency_code=currency_code,
        exchange_rate=exchange_rate,
        payment_method=payment_method,
        payment_account=payment_account,
        fa_metadata=fa_metadata or None,
        parties=[seller_party, buyer_party],
        lines=lines,
    )

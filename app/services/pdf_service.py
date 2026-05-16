import base64
import io
import os
import platform
from pathlib import Path

import qrcode

# Ensure Homebrew libraries are discoverable on macOS before weasyprint import
if platform.system() == "Darwin":
    _brew_lib = "/opt/homebrew/lib"
    if os.path.isdir(_brew_lib):
        _current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        if _brew_lib not in _current:
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"{_brew_lib}:{_current}" if _current else _brew_lib

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _build_qr_url(seller_nip: str, issue_date_str: str, xml_sha256_hex: str) -> str:
    """Build KSeF QR verification URL.

    Format: https://qr.ksef.mf.gov.pl/invoice/{NIP}/{DD-MM-RRRR}/{SHA256_Base64URL}
    """
    sha256_bytes = bytes.fromhex(xml_sha256_hex)
    sha256_b64url = base64.urlsafe_b64encode(sha256_bytes).rstrip(b"=").decode("ascii")
    return f"https://qr.ksef.mf.gov.pl/invoice/{seller_nip}/{issue_date_str}/{sha256_b64url}"


def _generate_qr_base64(data: str) -> str:
    """Generate QR code image as base64-encoded PNG for embedding in HTML."""
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def generate_invoice_pdf(invoice) -> bytes:
    """Generate PDF visualization of an invoice matching KSeF format.

    Args:
        invoice: SQLAlchemy Invoice object with loaded relationships
                 (parties, lines, vat_summaries).

    Returns:
        PDF file content as bytes.
    """
    seller = None
    buyer = None
    for ip in invoice.parties:
        if ip.role_code == "SELLER":
            seller = ip.party
        elif ip.role_code == "BUYER":
            buyer = ip.party

    # Build address strings (FA(3) TAdres: AdresL1, AdresL2)
    def _address_line1(party):
        if not party:
            return ""
        parts = []
        if party.street:
            parts.append(party.street)
        if party.building_no:
            parts.append(party.building_no)
        if party.apartment_no:
            parts.append(f"/{party.apartment_no}")
        return " ".join(parts)

    def _address_line2(party):
        if not party:
            return ""
        parts = []
        if party.postal_code:
            parts.append(party.postal_code)
        if party.city:
            parts.append(party.city)
        return " ".join(parts)

    # QR code generation
    qr_url = None
    qr_base64 = None
    if seller and seller.tax_id and invoice.xml_sha256 and invoice.issue_date:
        issue_date_formatted = invoice.issue_date.strftime("%d-%m-%Y")
        qr_url = _build_qr_url(seller.tax_id, issue_date_formatted, invoice.xml_sha256)
        qr_base64 = _generate_qr_base64(qr_url)

    # Determine invoice type label per FA(3) RodzajFaktury
    kind_labels = {
        "VAT": "Faktura podstawowa",
        "KOR": "Faktura korygująca",
        "ZAL": "Faktura zaliczkowa",
        "ROZ": "Faktura rozliczeniowa",
        "UPR": "Faktura uproszczona",
    }
    invoice_kind_label = kind_labels.get(invoice.invoice_kind_code, "Faktura VAT")

    # Sort lines by line_no
    lines_sorted = sorted(invoice.lines, key=lambda l: l.line_no) if invoice.lines else []

    # Render HTML template
    from jinja2 import Environment, FileSystemLoader
    from weasyprint import HTML

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("invoice_pdf.html")

    html_content = template.render(
        invoice=invoice,
        seller=seller,
        buyer=buyer,
        seller_address_l1=_address_line1(seller),
        seller_address_l2=_address_line2(seller),
        buyer_address_l1=_address_line1(buyer),
        buyer_address_l2=_address_line2(buyer),
        invoice_kind_label=invoice_kind_label,
        lines=lines_sorted,
        vat_summaries=invoice.vat_summaries,
        qr_base64=qr_base64,
        qr_url=qr_url,
        ksef_number=invoice.ksef_number,
    )

    pdf_bytes = HTML(string=html_content, base_url=str(TEMPLATES_DIR)).write_pdf()
    return pdf_bytes

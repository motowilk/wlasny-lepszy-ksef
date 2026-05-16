"""
Generate a KSeF token on the test environment.

This script:
  1. Creates a test person via POST /testdata/person
  2. Grants permissions via POST /testdata/permissions
  3. Authenticates via XAdES with a self-signed certificate
  4. Generates a KSeF token via POST /tokens

Usage:
    pip install signxml
    python scripts/generate_ksef_token.py
"""

import base64
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ObjectIdentifier

BASE_URL = "https://api-test.ksef.mf.gov.pl/v2"
NIP = os.environ.get("KSEF_NIP", "1234567890")  # Get from .ENV or Fictional test NIP (not real)
PESEL = "85010112345"  # Fictional test PESEL (not real)
HTTP_TIMEOUT = 30


def generate_self_signed_cert(nip: str):
    """
    Generate a self-signed certificate mimicking a qualified seal (pieczęć firmowa).
    The NIP is placed in the organizationIdentifier field (OID 2.5.4.97)
    as required by KSeF for certificateSubject identification.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # OID 2.5.4.97 = organizationIdentifier (used for NIP in qualified certs)
    oid_org_identifier = ObjectIdentifier("2.5.4.97")

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "PL"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test Firma Sp. z o.o."),
        x509.NameAttribute(oid_org_identifier, f"VATPL-{nip}"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Test KSeF Certificate"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(tz=timezone.utc))
        .not_valid_after(datetime.now(tz=timezone.utc) + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )

    return key, cert


def step1_create_test_person(client: httpx.Client, nip: str, pesel: str):
    """Create test person on the KSeF test environment."""
    print(f"\n[1/6] Creating test person (NIP={nip}, PESEL={pesel})...")
    resp = client.post(
        f"{BASE_URL}/testdata/person",
        json={
            "nip": nip,
            "pesel": pesel,
            "isBailiff": False,
            "description": "Test person for KSeF token generation",
        },
    )
    if resp.status_code == 200:
        print("      ✓ Test person created (or already exists).")
    elif resp.status_code == 400:
        body = resp.json() if resp.content else {}
        print(f"      ⚠ 400 response (person may already exist): {body}")
    else:
        resp.raise_for_status()


def step2_grant_permissions(client: httpx.Client, nip: str):
    """Grant full permissions to the test person (optional — person gets owner rights on creation)."""
    print(f"\n[2/6] Granting additional permissions (context NIP={nip})...")
    resp = client.post(
        f"{BASE_URL}/testdata/permissions",
        json={
            "contextIdentifier": {"type": "Nip", "value": nip},
            "authorizedIdentifier": {"type": "Nip", "value": nip},
            "permissions": [
                {"description": "Read invoices", "permissionType": "InvoiceRead"},
                {"description": "Write invoices", "permissionType": "InvoiceWrite"},
                {"description": "Manage credentials", "permissionType": "CredentialsManage"},
                {"description": "Read credentials", "permissionType": "CredentialsRead"},
                {"description": "Introspection", "permissionType": "Introspection"},
            ],
        },
    )
    if resp.status_code == 200:
        print("      ✓ Permissions granted.")
    elif resp.status_code in (400, 500):
        print(f"      ⚠ {resp.status_code} — skipping (person already has owner permissions from creation).")
    else:
        resp.raise_for_status()


def step3_get_challenge(client: httpx.Client) -> tuple[str, int]:
    """Get auth challenge."""
    print("\n[3/6] Getting auth challenge...")
    resp = client.post(f"{BASE_URL}/auth/challenge")
    resp.raise_for_status()
    data = resp.json()
    challenge = data["challenge"]
    timestamp_ms = data["timestampMs"]
    print(f"      ✓ Challenge: {challenge[:30]}...")
    print(f"      ✓ Timestamp: {timestamp_ms}")
    return challenge, timestamp_ms


def _exc_c14n(element):
    """Exclusive Canonical XML 1.0 (without comments)."""
    from lxml import etree
    from io import BytesIO
    output = BytesIO()
    etree.ElementTree(element).write_c14n(output, exclusive=True, with_comments=False)
    return output.getvalue()


def _build_xades_signature(root, key, cert):
    """
    Manually build a XAdES-BES enveloped signature.
    This avoids signxml's buggy digest computation for XAdES references.
    """
    import hashlib
    import uuid
    from lxml import etree
    from cryptography.hazmat.primitives.asymmetric import padding

    DS = "http://www.w3.org/2000/09/xmldsig#"
    XADES = "http://uri.etsi.org/01903/v1.3.2#"
    ds = lambda tag: f"{{{DS}}}{tag}"
    xades = lambda tag: f"{{{XADES}}}{tag}"

    # IDs
    sig_id = f"Signature-{uuid.uuid4().hex[:8]}"
    sp_id = f"SignedProperties-{uuid.uuid4().hex[:8]}"
    ki_id = f"KeyInfo-{uuid.uuid4().hex[:8]}"

    # Certificate info
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    cert_b64 = base64.b64encode(cert_der).decode()
    cert_digest = base64.b64encode(hashlib.sha256(cert_der).digest()).decode()
    issuer_name = cert.issuer.rfc4514_string()
    serial_number = str(cert.serial_number)

    signing_time = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- Build the Signature element ---
    nsmap_sig = {"ds": DS, "xades": XADES}
    sig_el = etree.SubElement(root, ds("Signature"), nsmap=nsmap_sig)
    sig_el.set("Id", sig_id)

    # SignedInfo
    signed_info = etree.SubElement(sig_el, ds("SignedInfo"))
    c14n_method = etree.SubElement(signed_info, ds("CanonicalizationMethod"))
    c14n_method.set("Algorithm", "http://www.w3.org/2001/10/xml-exc-c14n#")
    sig_method = etree.SubElement(signed_info, ds("SignatureMethod"))
    sig_method.set("Algorithm", "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256")

    # Reference #1: the document (URI="")
    ref1 = etree.SubElement(signed_info, ds("Reference"))
    ref1.set("URI", "")
    transforms1 = etree.SubElement(ref1, ds("Transforms"))
    t1 = etree.SubElement(transforms1, ds("Transform"))
    t1.set("Algorithm", "http://www.w3.org/2000/09/xmldsig#enveloped-signature")
    t2 = etree.SubElement(transforms1, ds("Transform"))
    t2.set("Algorithm", "http://www.w3.org/2001/10/xml-exc-c14n#")
    dm1 = etree.SubElement(ref1, ds("DigestMethod"))
    dm1.set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
    dv1 = etree.SubElement(ref1, ds("DigestValue"))
    # Will be filled below

    # Reference #2: SignedProperties
    ref2 = etree.SubElement(signed_info, ds("Reference"))
    ref2.set("URI", f"#{sp_id}")
    ref2.set("Type", "http://uri.etsi.org/01903#SignedProperties")
    transforms2 = etree.SubElement(ref2, ds("Transforms"))
    t3 = etree.SubElement(transforms2, ds("Transform"))
    t3.set("Algorithm", "http://www.w3.org/2001/10/xml-exc-c14n#")
    dm2 = etree.SubElement(ref2, ds("DigestMethod"))
    dm2.set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
    dv2 = etree.SubElement(ref2, ds("DigestValue"))
    # Will be filled below

    # SignatureValue (placeholder)
    sig_value_el = etree.SubElement(sig_el, ds("SignatureValue"))

    # KeyInfo
    key_info = etree.SubElement(sig_el, ds("KeyInfo"))
    key_info.set("Id", ki_id)
    x509_data = etree.SubElement(key_info, ds("X509Data"))
    x509_cert = etree.SubElement(x509_data, ds("X509Certificate"))
    x509_cert.text = cert_b64

    # Object > QualifyingProperties > SignedProperties
    obj = etree.SubElement(sig_el, ds("Object"))
    qp = etree.SubElement(obj, xades("QualifyingProperties"))
    qp.set("Target", f"#{sig_id}")
    sp = etree.SubElement(qp, xades("SignedProperties"))
    sp.set("Id", sp_id)
    ssp = etree.SubElement(sp, xades("SignedSignatureProperties"))
    st = etree.SubElement(ssp, xades("SigningTime"))
    st.text = signing_time
    sc = etree.SubElement(ssp, xades("SigningCertificate"))
    sc_cert = etree.SubElement(sc, xades("Cert"))
    cd = etree.SubElement(sc_cert, xades("CertDigest"))
    cd_dm = etree.SubElement(cd, ds("DigestMethod"))
    cd_dm.set("Algorithm", "http://www.w3.org/2001/04/xmlenc#sha256")
    cd_dv = etree.SubElement(cd, ds("DigestValue"))
    cd_dv.text = cert_digest
    issuer_serial = etree.SubElement(sc_cert, xades("IssuerSerial"))
    issuer_name_el = etree.SubElement(issuer_serial, ds("X509IssuerName"))
    issuer_name_el.text = issuer_name
    issuer_serial_el = etree.SubElement(issuer_serial, ds("X509SerialNumber"))
    issuer_serial_el.text = serial_number

    # --- Compute digests ---

    # Digest for Reference #1 (document with enveloped-signature transform = document without Signature)
    # Clone root, remove the Signature element, canonicalize
    root_copy = etree.fromstring(etree.tostring(root))
    for sig in root_copy.findall(f"{{{DS}}}Signature"):
        root_copy.remove(sig)
    doc_c14n = _exc_c14n(root_copy)
    doc_digest = base64.b64encode(hashlib.sha256(doc_c14n).digest()).decode()
    dv1.text = doc_digest

    # Digest for Reference #2 (SignedProperties)
    sp_c14n = _exc_c14n(sp)
    sp_digest = base64.b64encode(hashlib.sha256(sp_c14n).digest()).decode()
    dv2.text = sp_digest

    # --- Compute SignatureValue ---
    si_c14n = _exc_c14n(signed_info)
    signature_bytes = key.sign(si_c14n, padding.PKCS1v15(), hashes.SHA256())
    sig_value_el.text = base64.b64encode(signature_bytes).decode()

    return root


def step4_xades_auth(client: httpx.Client, challenge: str, nip: str, key, cert) -> tuple[str, str]:
    """
    Create AuthTokenRequest XML, sign with XAdES-BES manually, and submit.
    Returns (referenceNumber, authenticationToken).
    """
    print("\n[4/6] Authenticating with XAdES signature...")

    from lxml import etree

    # Build the AuthTokenRequest XML
    nsmap = {None: "http://ksef.mf.gov.pl/auth/token/2.0"}
    root = etree.Element("AuthTokenRequest", nsmap=nsmap)
    challenge_el = etree.SubElement(root, "Challenge")
    challenge_el.text = challenge
    ctx_id = etree.SubElement(root, "ContextIdentifier")
    nip_el = etree.SubElement(ctx_id, "Nip")
    nip_el.text = nip
    subject_type = etree.SubElement(root, "SubjectIdentifierType")
    subject_type.text = "certificateSubject"

    unsigned_xml = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    print(f"      ✓ AuthTokenRequest XML created ({len(unsigned_xml)} bytes)")

    # Sign the document with manual XAdES-BES
    signed_root = _build_xades_signature(root, key, cert)
    signed_xml = etree.tostring(signed_root, xml_declaration=True, encoding="utf-8")
    print(f"      ✓ XML signed with XAdES-BES ({len(signed_xml)} bytes)")

    # Submit signed XML
    resp = client.post(
        f"{BASE_URL}/auth/xades-signature",
        content=signed_xml,
        headers={"Content-Type": "application/xml"},
        params={"verifyCertificateChain": "false"},
    )
    if resp.status_code not in (200, 202):
        print(f"      ✗ Auth submission failed: {resp.status_code}")
        print(f"        Response: {resp.text[:500]}")
        sys.exit(1)

    data = resp.json()
    ref_number = data["referenceNumber"]
    auth_token = data["authenticationToken"]["token"]
    print(f"      ✓ Auth submitted. Reference: {ref_number}")
    return ref_number, auth_token


def step5_poll_auth_status(client: httpx.Client, ref_number: str, auth_token: str) -> None:
    """Poll auth status until code=200."""
    print("\n[5/6] Polling authentication status...")
    for attempt in range(30):
        resp = client.get(
            f"{BASE_URL}/auth/{ref_number}",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        code = data.get("status", {}).get("code", 0)
        desc = data.get("status", {}).get("description", "")
        print(f"      ... attempt {attempt + 1}: code={code} ({desc})")

        if code == 200:
            print("      ✓ Authentication successful!")
            return
        if code >= 400:
            print(f"      ✗ Authentication failed: {desc}")
            sys.exit(1)

        time.sleep(2)

    print("      ✗ Authentication timed out.")
    sys.exit(1)


def step6_redeem_and_generate_token(client: httpx.Client, auth_token: str, nip: str) -> str:
    """Redeem access token and then generate a KSeF token."""
    print("\n[6/6] Redeeming access token and generating KSeF token...")

    # Redeem access token
    resp = client.post(
        f"{BASE_URL}/auth/token/redeem",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    resp.raise_for_status()
    data = resp.json()
    access_token = data["accessToken"]["token"]
    print(f"      ✓ Access token obtained (valid until {data['accessToken']['validUntil']})")

    # Generate KSeF token
    resp = client.post(
        f"{BASE_URL}/tokens",
        json={
            "permissions": [
                "InvoiceRead",
                "InvoiceWrite",
                "CredentialsRead",
                "CredentialsManage",
                "Introspection",
            ],
            "description": "Auto-generated token for ksef-app",
        },
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if resp.status_code not in (200, 201, 202):
        print(f"      ✗ Token generation failed: {resp.status_code}")
        print(f"        Response: {resp.text[:500]}")
        sys.exit(1)

    data = resp.json()
    ksef_token = data["token"]
    ref = data["referenceNumber"]
    print(f"      ✓ KSeF token generated!")
    print(f"        Reference: {ref}")
    print(f"        Token:     {ksef_token}")
    return ksef_token


def main():
    print("=" * 60)
    print("  KSeF Token Generator (test environment)")
    print(f"  NIP: {NIP}")
    print(f"  API: {BASE_URL}")
    print("=" * 60)

    key, cert = generate_self_signed_cert(NIP)
    print("\n✓ Self-signed certificate generated")

    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        step1_create_test_person(client, NIP, PESEL)
        step2_grant_permissions(client, NIP)
        challenge, timestamp_ms = step3_get_challenge(client)
        ref_number, auth_token = step4_xades_auth(client, challenge, NIP, key, cert)
        step5_poll_auth_status(client, ref_number, auth_token)
        ksef_token = step6_redeem_and_generate_token(client, auth_token, NIP)

    print("\n" + "=" * 60)
    print("  DONE! Add these to your .env file:")
    print("=" * 60)
    print(f"\nKSEF_NIP={NIP}")
    print(f"KSEF_TOKEN={ksef_token}")
    print()


if __name__ == "__main__":
    main()

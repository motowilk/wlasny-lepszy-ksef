import base64
import hashlib
import os
import time
from datetime import datetime, timezone

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.x509 import load_der_x509_certificate

from app.adapters.ksef.base import BaseKsefClient
from app.core.config import get_settings


class RealKsefClient(BaseKsefClient):
    """
    KSeF API v2 client implementing the interactive session flow.

    Authentication flow per RFC:
      1. POST /auth/challenge            → challenge + timestampMs
      2. Encrypt ksef_token|timestampMs  → RSA-OAEP SHA-256 with MF public key
      3. POST /auth/ksef-token           → referenceNumber + authenticationToken
      4. Poll GET /auth/{ref}            → wait for status.code == 200
      5. POST /auth/token/redeem         → accessToken (Bearer JWT)

    Invoice submission flow:
      6. Generate random AES-256 key + IV
      7. Encrypt AES key with MF RSA public key
      8. POST /sessions/online           → session referenceNumber
      9. AES-256-CBC encrypt invoice XML; compute SHA-256 hashes
     10. POST /sessions/online/{ref}/invoices  → invoice referenceNumber
     11. POST /sessions/online/{ref}/close
     12. Poll GET /sessions/{ref}/invoices/{invoiceRef} → ksefNumber
    """

    _AUTH_POLL_RETRIES = 30
    _AUTH_POLL_INTERVAL = 2  # seconds
    _HTTP_TIMEOUT = 30  # seconds — applied to every outgoing HTTP call

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.ksef_api_url.rstrip("/")
        self._access_token: str | None = None
        self._token_valid_until: datetime | None = None
        # Cache the MF public key to avoid fetching on every call
        self._cached_public_key_der: bytes | None = None
        self._cached_public_key_id: str | None = None

    # ------------------------------------------------------------------ #
    # Public interface (BaseKsefClient)                                    #
    # ------------------------------------------------------------------ #

    def send_invoice(self, invoice_id: int, xml_content: str) -> dict:
        """
        Authenticate, open an interactive session, encrypt and send the
        invoice XML, then close the session.

        Returns {"invoice_ref": str, "session_ref": str}.
        The caller must separately poll get_invoice_status() for ksefNumber.
        """
        self._ensure_authenticated()

        sym_key = os.urandom(32)  # AES-256 key
        iv = os.urandom(16)       # AES-256-CBC IV

        enc_sym_key, public_key_id = self._encrypt_with_mf_key(sym_key)
        session_ref = self._open_session(enc_sym_key, iv, public_key_id)

        xml_bytes = xml_content.encode("utf-8")
        invoice_hash = base64.b64encode(hashlib.sha256(xml_bytes).digest()).decode()

        encrypted = self._aes_encrypt(xml_bytes, sym_key, iv)
        encrypted_hash = base64.b64encode(hashlib.sha256(encrypted).digest()).decode()
        encrypted_content = base64.b64encode(encrypted).decode()

        invoice_ref = self._send_invoice_to_session(
            session_ref=session_ref,
            invoice_hash=invoice_hash,
            invoice_size=len(xml_bytes),
            encrypted_hash=encrypted_hash,
            encrypted_size=len(encrypted),
            encrypted_content=encrypted_content,
        )

        self._close_session(session_ref)

        return {"invoice_ref": invoice_ref, "session_ref": session_ref}

    def get_invoice_status(self, session_ref: str, invoice_ref: str) -> dict:
        """
        Poll KSeF for individual invoice acceptance status.

        Relevant response keys:
          - ksefNumber  (str | None)  — present only after acceptance
          - status.code (int)         — 100 = processing, 200 = accepted, 4xx = error
          - status.description (str)
        """
        self._ensure_authenticated()
        url = f"{self.base_url}/sessions/{session_ref}/invoices/{invoice_ref}"
        return self._get(url)

    def fetch_invoices(
        self,
        date_from: str,
        date_to: str,
        subject_type: str = "subject2",
    ) -> list[dict]:
        """
        Fetch invoices from KSeF using the query endpoint.

        Uses POST /api/online/Query/Invoice/Sync to retrieve invoice metadata,
        then fetches each invoice's XML via GET /api/online/Invoice/Get/{ksefNumber}.

        Args:
            date_from: ISO datetime string for range start.
            date_to: ISO datetime string for range end.
            subject_type: "subject1" (I am seller) or "subject2" (I am buyer/purchase).

        Returns:
            List of dicts: {"ksef_number": str, "xml_content": str}
        """
        self._ensure_authenticated()

        # Query for invoice references in the date range
        query_body = {
            "queryCriteria": {
                "subjectType": subject_type,
                "type": "incremental",
                "acquisitionTimestampThresholdFrom": date_from,
                "acquisitionTimestampThresholdTo": date_to,
            },
        }

        results: list[dict] = []
        page_offset = 0
        page_size = 100

        while True:
            query_body["queryCriteria"]["offset"] = page_offset
            query_body["queryCriteria"]["limit"] = page_size

            resp = self._post(
                f"{self.base_url}/online/Query/Invoice/Sync",
                query_body,
            )

            invoices_list = resp.get("invoiceHeaderList", [])
            if not invoices_list:
                break

            for inv_header in invoices_list:
                ksef_number = inv_header.get("ksefReferenceNumber")
                if not ksef_number:
                    continue

                # Fetch the actual XML content
                xml_resp = self._get_raw(
                    f"{self.base_url}/online/Invoice/Get/{ksef_number}"
                )
                results.append({
                    "ksef_number": ksef_number,
                    "xml_content": xml_resp,
                })

            if len(invoices_list) < page_size:
                break
            page_offset += page_size

        return results

    # ------------------------------------------------------------------ #
    # Authentication                                                        #
    # ------------------------------------------------------------------ #

    def _ensure_authenticated(self) -> None:
        now = datetime.now(tz=timezone.utc)
        if (
            self._access_token
            and self._token_valid_until
            and now < self._token_valid_until
        ):
            return
        self._authenticate()

    def _authenticate(self) -> None:
        # Step 1 — challenge
        challenge_resp = self._post_anon(f"{self.base_url}/auth/challenge", {})
        challenge = challenge_resp["challenge"]
        timestamp_ms = challenge_resp["timestampMs"]

        # Step 2 — encrypt ksef_token|timestampMs with MF RSA public key
        plaintext = f"{self.settings.ksef_token}|{timestamp_ms}".encode("utf-8")
        enc_token, pub_key_id = self._encrypt_with_mf_key(plaintext)

        # Step 3 — submit KSeF token authentication
        auth_resp = self._post_anon(
            f"{self.base_url}/auth/ksef-token",
            {
                "challenge": challenge,
                "contextIdentifier": {
                    "type": "Nip",
                    "value": self.settings.ksef_nip,
                },
                "encryptedToken": enc_token,
                "publicKeyId": pub_key_id,
            },
        )
        auth_ref = auth_resp["referenceNumber"]
        auth_token = auth_resp["authenticationToken"]["token"]

        # Step 4 — poll until authentication succeeds
        for _ in range(self._AUTH_POLL_RETRIES):
            status_resp = self._get_with_token(
                f"{self.base_url}/auth/{auth_ref}", auth_token
            )
            code = status_resp.get("status", {}).get("code", 0)
            if code == 200:
                break
            if code >= 400:
                desc = status_resp.get("status", {}).get("description", "unknown")
                raise RuntimeError(f"KSeF authentication failed: {desc}")
            time.sleep(self._AUTH_POLL_INTERVAL)
        else:
            raise TimeoutError("KSeF authentication timed out after polling.")

        # Step 5 — redeem final tokens
        redeem_resp = self._post_with_token(
            f"{self.base_url}/auth/token/redeem", {}, auth_token
        )
        self._access_token = redeem_resp["accessToken"]["token"]
        valid_until_str = redeem_resp["accessToken"]["validUntil"]
        # Normalise to an aware datetime regardless of whether the API returns
        # a timezone offset or a bare ISO string.  Without this, comparing a
        # naive datetime with timezone.utc-aware `now` raises TypeError.
        raw_dt = datetime.fromisoformat(valid_until_str.replace("Z", "+00:00"))
        self._token_valid_until = (
            raw_dt if raw_dt.tzinfo is not None else raw_dt.replace(tzinfo=timezone.utc)
        )

    # ------------------------------------------------------------------ #
    # Session management                                                    #
    # ------------------------------------------------------------------ #

    def _open_session(self, enc_sym_key: str, iv: bytes, public_key_id: str) -> str:
        resp = self._post(
            f"{self.base_url}/sessions/online",
            {
                "formCode": {
                    "systemCode": "FA (3)",
                    "schemaVersion": "1-0E",
                    "value": "FA",
                },
                "encryption": {
                    "encryptedSymmetricKey": enc_sym_key,
                    "initializationVector": base64.b64encode(iv).decode(),
                    "publicKeyId": public_key_id,
                },
            },
        )
        return resp["referenceNumber"]

    def _send_invoice_to_session(
        self,
        session_ref: str,
        invoice_hash: str,
        invoice_size: int,
        encrypted_hash: str,
        encrypted_size: int,
        encrypted_content: str,
    ) -> str:
        resp = self._post(
            f"{self.base_url}/sessions/online/{session_ref}/invoices",
            {
                "invoiceHash": invoice_hash,
                "invoiceSize": invoice_size,
                "encryptedInvoiceHash": encrypted_hash,
                "encryptedInvoiceSize": encrypted_size,
                "encryptedInvoiceContent": encrypted_content,
            },
        )
        return resp["referenceNumber"]

    def _close_session(self, session_ref: str) -> None:
        with httpx.Client(timeout=self._HTTP_TIMEOUT) as client:
            client.post(
                f"{self.base_url}/sessions/online/{session_ref}/close",
                headers=self._auth_headers(),
            ).raise_for_status()

    # ------------------------------------------------------------------ #
    # Crypto helpers                                                        #
    # ------------------------------------------------------------------ #

    def _get_mf_public_key(self) -> tuple[bytes, str]:
        """Fetch and cache the MF certificate used for KsefTokenEncryption."""
        if self._cached_public_key_der and self._cached_public_key_id:
            return self._cached_public_key_der, self._cached_public_key_id

        certs = self._get_anon(f"{self.base_url}/security/public-key-certificates")
        for cert in certs:
            if "KsefTokenEncryption" in cert.get("usage", []):
                der_bytes = base64.b64decode(cert["certificate"])
                self._cached_public_key_der = der_bytes
                self._cached_public_key_id = cert["publicKeyId"]
                return der_bytes, cert["publicKeyId"]

        raise RuntimeError(
            "MF public key with KsefTokenEncryption usage not found in /security/public-key-certificates"
        )

    def _encrypt_with_mf_key(self, data: bytes) -> tuple[str, str]:
        """
        Encrypt arbitrary bytes with the MF RSA public key using OAEP + SHA-256.
        Returns (base64_ciphertext, publicKeyId).
        """
        der_bytes, pub_key_id = self._get_mf_public_key()
        cert = load_der_x509_certificate(der_bytes)
        public_key = cert.public_key()
        ciphertext = public_key.encrypt(
            data,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return base64.b64encode(ciphertext).decode(), pub_key_id

    @staticmethod
    def _aes_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
        """AES-256-CBC encryption with PKCS7 padding."""
        padder = sym_padding.PKCS7(128).padder()
        padded = padder.update(data) + padder.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        return encryptor.update(padded) + encryptor.finalize()

    # ------------------------------------------------------------------ #
    # HTTP helpers                                                          #
    # ------------------------------------------------------------------ #

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def _post(self, url: str, body: dict) -> dict:
        with httpx.Client(timeout=self._HTTP_TIMEOUT) as client:
            resp = client.post(url, json=body, headers=self._auth_headers())
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    def _get(self, url: str) -> dict:
        with httpx.Client(timeout=self._HTTP_TIMEOUT) as client:
            resp = client.get(url, headers=self._auth_headers())
            resp.raise_for_status()
            return resp.json()

    def _get_raw(self, url: str) -> str:
        """GET returning raw text (for XML downloads)."""
        with httpx.Client(timeout=self._HTTP_TIMEOUT) as client:
            resp = client.get(url, headers=self._auth_headers())
            resp.raise_for_status()
            return resp.text

    def _post_anon(self, url: str, body: dict) -> dict:
        with httpx.Client(timeout=self._HTTP_TIMEOUT) as client:
            resp = client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()

    def _get_anon(self, url: str) -> list | dict:
        with httpx.Client(timeout=self._HTTP_TIMEOUT) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()

    def _post_with_token(self, url: str, body: dict, token: str) -> dict:
        with httpx.Client(timeout=self._HTTP_TIMEOUT) as client:
            resp = client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()

    def _get_with_token(self, url: str, token: str) -> dict:
        with httpx.Client(timeout=self._HTTP_TIMEOUT) as client:
            resp = client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()

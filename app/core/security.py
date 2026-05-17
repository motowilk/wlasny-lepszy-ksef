import base64
import hashlib
import hmac as _hmac
import json
import time

from passlib.context import CryptContext

# bcrypt_sha256 is the primary scheme (avoids bcrypt's 72-byte input limit by pre-hashing).
# bcrypt is kept as deprecated so that existing hashes created with plain bcrypt can still
# be verified; passlib will flag them for rehashing on next login.
pwd_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated=["bcrypt"])
UI_SESSION_MAX_AGE = 2 * 60 * 60
MAX_FAILED_LOGIN_ATTEMPTS = 3
MAX_PASSWORD_LENGTH = 128
DUMMY_PASSWORD_HASH = "$2b$12$KIX/TAtOSw8A4uFGrwFnGuvVVz3SsLOJo0bMLXkn9E2z8CRF.pBGG"


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def normalize_username(username: str | None) -> str | None:
    if username is None:
        return None
    return username.strip().lower()


def get_failed_login_attempts(user) -> int:
    return int(getattr(user, "failed_login_attempts", 0) or 0)


def record_failed_login_attempt(user) -> int:
    attempts = get_failed_login_attempts(user) + 1
    user.failed_login_attempts = attempts
    if attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
        user.is_locked = True
    return attempts


def reset_failed_login_attempts(user) -> None:
    if get_failed_login_attempts(user):
        user.failed_login_attempts = 0


def create_ui_session_token(
    user_id: int,
    secret: str,
    session_nonce: str,
    max_age: int = UI_SESSION_MAX_AGE,
) -> str:
    issued_at = int(time.time())
    payload = json.dumps(
        {
            "user_id": user_id,
            "issued_at": issued_at,
            "expires_at": issued_at + max_age,
            "session_nonce": session_nonce,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    sig = _hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode()


def decode_ui_session_token(token: str, secret: str) -> dict[str, int | str] | None:
    """Verify the signed payload and return the decoded session data."""
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        payload, sig = raw.rsplit(".", 1)
        expected = _hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(sig, expected):
            return None

        data = json.loads(payload)
        user_id = int(data["user_id"])
        issued_at = int(data["issued_at"])
        expires_at = int(data["expires_at"])
        session_nonce = str(data["session_nonce"])

        now = int(time.time())
        if expires_at < now or issued_at > expires_at or not session_nonce:
            return None

        return {
            "user_id": user_id,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "session_nonce": session_nonce,
        }
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# TOTP pending token — short-lived, used between password step and TOTP step
# ---------------------------------------------------------------------------

_TOTP_PENDING_MAX_AGE = 300  # 5 minutes


def create_totp_pending_token(user_id: int, secret: str) -> str:
    """Return a URL-safe, time-stamped, HMAC-signed token for the TOTP step."""
    payload = f"{user_id}:{int(time.time())}"
    sig = _hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode()


def decode_totp_pending_token(token: str, secret: str) -> int | None:
    """Return user_id if the token is valid and within the 5-minute window."""
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        payload, sig = raw.split(".", 1)
        expected = _hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(sig, expected):
            return None
        user_id_str, ts_str = payload.split(":", 1)
        if int(time.time()) - int(ts_str) > _TOTP_PENDING_MAX_AGE:
            return None
        return int(user_id_str)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CSRF token — HMAC-based, derived from session nonce
# ---------------------------------------------------------------------------


def generate_csrf_token(session_nonce: str, secret: str) -> str:
    """Generate an HMAC-SHA256 CSRF token derived from the session nonce."""
    return _hmac.new(
        secret.encode(), f"csrf:{session_nonce}".encode(), hashlib.sha256
    ).hexdigest()


def verify_csrf_token(token: str | None, session_nonce: str, secret: str) -> bool:
    """Verify CSRF token matches expected value for the session nonce."""
    if not token or not session_nonce:
        return False
    expected = generate_csrf_token(session_nonce, secret)
    return _hmac.compare_digest(token, expected)


# ---------------------------------------------------------------------------
# TOTP secret encryption at rest (AES-256-GCM)
# ---------------------------------------------------------------------------

import os


def _derive_totp_key(secret: str) -> bytes:
    """Derive a 32-byte AES key from the app secret using HKDF-like HMAC."""
    return _hmac.new(secret.encode(), b"totp-encryption-key-v1", hashlib.sha256).digest()


def encrypt_totp_secret(plaintext: str, secret: str) -> str:
    """Encrypt a TOTP secret with AES-256-GCM. Returns base64(nonce + ciphertext + tag)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _derive_totp_key(secret)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt_totp_secret(ciphertext_b64: str, secret: str) -> str | None:
    """Decrypt a TOTP secret. Returns None on failure (wrong key, tampered data)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        raw = base64.urlsafe_b64decode(ciphertext_b64)
        if len(raw) < 13:  # 12 nonce + at least 1 byte
            return None
        nonce = raw[:12]
        ct = raw[12:]
        key = _derive_totp_key(secret)
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ct, None)
        return plaintext.decode()
    except Exception:
        return None


def is_totp_encrypted(value: str) -> bool:
    """Heuristic: encrypted values are base64 and longer than plain base32 secrets."""
    # Plain pyotp secrets are 32 chars of base32 (A-Z2-7). Encrypted are url-safe base64.
    if not value:
        return False
    # Encrypted output: 12 bytes nonce + >=16 bytes (secret) + 16 bytes tag = >=44 bytes → >=60 base64 chars
    return len(value) > 50 and any(c in value for c in "-_")

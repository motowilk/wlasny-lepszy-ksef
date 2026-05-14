import base64
import hashlib
import hmac as _hmac
import time

from passlib.context import CryptContext

# bcrypt_sha256 is the primary scheme (avoids bcrypt's 72-byte input limit by pre-hashing).
# bcrypt is kept as deprecated so that existing hashes created with plain bcrypt can still
# be verified; passlib will flag them for rehashing on next login.
pwd_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated=["bcrypt"])


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def normalize_username(username: str | None) -> str | None:
    if username is None:
        return None
    return username.strip().lower()


def create_ui_session_token(user_id: int, secret: str) -> str:
    payload = str(user_id)
    sig = _hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{sig}".encode()).decode()


def decode_ui_session_token(token: str, secret: str) -> int | None:
    """Verify the HMAC signature and return the user_id, or None if invalid."""
    try:
        # Re-add stripped base64 padding if necessary.
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        payload, sig = raw.split(".", 1)
        expected = _hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if _hmac.compare_digest(sig, expected):
            return int(payload)
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

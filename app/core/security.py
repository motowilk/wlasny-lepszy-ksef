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
UI_SESSION_MAX_AGE = 12 * 60 * 60


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def normalize_username(username: str | None) -> str | None:
    if username is None:
        return None
    return username.strip().lower()


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

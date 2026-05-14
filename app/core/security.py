from passlib.context import CryptContext

# Use bcrypt_sha256 to avoid bcrypt's 72-byte input limit by pre-hashing long passwords.
pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def normalize_username(username: str | None) -> str | None:
    if username is None:
        return None
    return username.strip().lower()

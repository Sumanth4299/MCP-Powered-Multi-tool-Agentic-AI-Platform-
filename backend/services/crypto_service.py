from cryptography.fernet import Fernet
from backend.config import get_settings

settings = get_settings()


def _get_fernet() -> Fernet:
    key = settings.ENCRYPTION_KEY.encode()
    return Fernet(key)


def encrypt_token(plain_token: str) -> bytes:
    """Encrypt OAuth refresh token before persisting to disk/database."""
    f = _get_fernet()
    return f.encrypt(plain_token.encode())


def decrypt_token(cipher_bytes: bytes) -> str:
    """Decrypt token on-the-fly for outbound API authentication."""
    f = _get_fernet()
    return f.decrypt(cipher_bytes).decode()
from cryptography.fernet import Fernet

from app.config import settings


def _get_fernet() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string and return the base64-encoded ciphertext."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext and return the plaintext string."""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()

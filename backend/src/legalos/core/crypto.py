"""Small, standard cryptographic helpers. No custom algorithms."""

import hashlib
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet

from legalos.config import get_settings

_hasher = PasswordHasher()  # Argon2id with the library's recommended parameters.

# A fixed hash used to spend the same time verifying when an email does not exist,
# so response timing does not reveal which emails have accounts.
_DUMMY_HASH = _hasher.hash("legalos-timing-equalizer")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
    except (VerificationError, InvalidHashError):
        return False


def new_token() -> str:
    """A random, URL-safe token (256 bits) for session cookies."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    """Sessions are stored by hash, so a database leak does not leak live sessions."""
    return hashlib.sha256(token.encode()).digest()


def keyed_hash(value: str) -> str:
    """Stable, non-reversible identifier for values we must not store (e.g. emails in
    throttling records)."""
    key = get_settings().encryption_key.get_secret_value().encode()
    return hashlib.blake2b(value.encode(), key=key[:64], digest_size=32).hexdigest()


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().encryption_key.get_secret_value()
    if not key:
        raise RuntimeError("LEGALOS_ENCRYPTION_KEY is not set")
    return Fernet(key.encode())


def encrypt(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    return _fernet().decrypt(ciphertext).decode()

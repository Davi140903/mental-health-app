from __future__ import annotations

import base64
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken

from .config import DATA_ENCRYPTION_KEY, SECRET_KEY


ENCRYPTED_PREFIX = "enc:v1:"


def build_fernet_key() -> bytes:
    configured_key = DATA_ENCRYPTION_KEY.strip()
    if configured_key:
        return configured_key.encode("utf-8")
    return base64.urlsafe_b64encode(sha256(SECRET_KEY.encode("utf-8")).digest())


fernet = Fernet(build_fernet_key())


def encrypt_text(value: str | None) -> str | None:
    if value is None or value.startswith(ENCRYPTED_PREFIX):
        return value
    token = fernet.encrypt(value.encode("utf-8")).decode("utf-8")
    return ENCRYPTED_PREFIX + token


def decrypt_text(value: str | None) -> str | None:
    if value is None or not value.startswith(ENCRYPTED_PREFIX):
        return value
    try:
        return fernet.decrypt(value[len(ENCRYPTED_PREFIX) :].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return value


def is_encrypted_text(value: str | None) -> bool:
    return bool(value and value.startswith(ENCRYPTED_PREFIX))

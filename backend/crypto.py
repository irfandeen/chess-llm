"""Fernet encryption for API keys at rest.

AES-128-CBC + HMAC-SHA256 (Fernet) with a key held only in the server
environment, so a database leak alone never exposes user API keys.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY is not set")
    return Fernet(key.encode())


def encrypt_key(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_key(ciphertext: bytes) -> str:
    return _fernet().decrypt(bytes(ciphertext)).decode()

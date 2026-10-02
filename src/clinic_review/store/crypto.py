"""Field encryption for the raw store.

Response bodies and URLs are sealed with AES-256-GCM before they touch disk. The row's
CHR id and screen name are bound in as associated data, so a body can't be moved to
another patient's row without failing to decrypt.

On the clinic Mac the key lives in the macOS Keychain of the separate data account.
"""
from __future__ import annotations

import base64
import os
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12
KEY_BYTES = 32


class KeyProvider(Protocol):
    def get_key(self) -> bytes: ...


class StaticKeyProvider:
    """For tests and CI only."""

    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise ValueError("store key must be 32 bytes")
        self._key = key

    def get_key(self) -> bytes:
        return self._key


class EnvKeyProvider:
    """Base64 key from an environment variable. Weaker than the Keychain; tests and CI."""

    def __init__(self, var: str = "CLINIC_REVIEW_STORE_KEY") -> None:
        self.var = var

    def get_key(self) -> bytes:
        raw = os.environ.get(self.var)
        if not raw:
            raise RuntimeError(f"{self.var} isn't set")
        key = base64.b64decode(raw)
        if len(key) != KEY_BYTES:
            raise ValueError(f"{self.var} must decode to 32 bytes")
        return key


class KeychainKeyProvider:
    """Key in the macOS Keychain, created on first use."""

    def __init__(self, service: str = "clinic_review", account: str = "raw-store") -> None:
        self.service = service
        self.account = account

    def get_key(self) -> bytes:
        import keyring  # optional dependency: pip install .[mac]

        stored = keyring.get_password(self.service, self.account)
        if stored is None:
            stored = base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()
            keyring.set_password(self.service, self.account, stored)
        return base64.b64decode(stored)


class Sealer:
    def __init__(self, key: bytes) -> None:
        self._aead = AESGCM(key)

    def seal(self, plaintext: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, plaintext, aad)

    def open(self, sealed: bytes, aad: bytes) -> bytes:
        return self._aead.decrypt(sealed[:NONCE_BYTES], sealed[NONCE_BYTES:], aad)

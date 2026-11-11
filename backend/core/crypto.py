"""Envelope encryption of Azure secrets under a per-connection data key (AD-06, T-4.1.4).

``KeyService`` is the KMS interface. B1 has only ``FakeKeyService`` (AES-GCM with an in-memory
master key); the real KMS key in ca-central-1 is blocked until an AWS account exists. The
encryption context binds each ciphertext to its tenant and connection.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.secretvalue import SecretValue


class KeyService(Protocol):
    key_arn: str

    def generate_data_key(self, context: dict[str, str]) -> tuple[bytes, bytes]:
        """Return (plaintext data key, wrapped data key)."""
        ...

    def decrypt_data_key(self, wrapped: bytes, context: dict[str, str]) -> bytes: ...


class FakeKeyService:
    key_arn = "arn:aws:kms:ca-central-1:000000000000:key/fake-local"

    def __init__(self, master_key: bytes | None = None) -> None:
        self._master = AESGCM(master_key or AESGCM.generate_key(256))

    @staticmethod
    def _aad(context: dict[str, str]) -> bytes:
        return json.dumps(context, sort_keys=True).encode()

    def generate_data_key(self, context: dict[str, str]) -> tuple[bytes, bytes]:
        dk = AESGCM.generate_key(256)
        nonce = os.urandom(12)
        return dk, nonce + self._master.encrypt(nonce, dk, self._aad(context))

    def decrypt_data_key(self, wrapped: bytes, context: dict[str, str]) -> bytes:
        return self._master.decrypt(wrapped[:12], wrapped[12:], self._aad(context))


@dataclass(frozen=True)
class Envelope:
    ciphertext: bytes
    wrapped_data_key: bytes
    kms_key_arn: str


def _context(tenant_id: uuid.UUID, connection_id: uuid.UUID) -> dict[str, str]:
    return {"tenant_id": str(tenant_id), "connection_id": str(connection_id)}


def encrypt_secret(ks: KeyService, tenant_id: uuid.UUID, connection_id: uuid.UUID, secret: SecretValue) -> Envelope:
    ctx = _context(tenant_id, connection_id)
    dk, wrapped = ks.generate_data_key(ctx)
    nonce = os.urandom(12)
    ct = nonce + AESGCM(dk).encrypt(nonce, secret.reveal().encode(), json.dumps(ctx, sort_keys=True).encode())
    return Envelope(ct, wrapped, ks.key_arn)


def decrypt_secret(
    ks: KeyService, tenant_id: uuid.UUID, connection_id: uuid.UUID, ciphertext: bytes, wrapped: bytes
) -> SecretValue:
    ctx = _context(tenant_id, connection_id)
    dk = ks.decrypt_data_key(wrapped, ctx)
    plain = AESGCM(dk).decrypt(ciphertext[:12], ciphertext[12:], json.dumps(ctx, sort_keys=True).encode())
    return SecretValue(plain.decode())


def local_key_service() -> FakeKeyService:
    """The local stand-in for KMS. Shared by processes only through MAPLEROUTE_FAKE_KMS_KEY_HEX."""
    from core.config import settings

    hex_key = settings().fake_kms_key_hex
    return FakeKeyService(bytes.fromhex(hex_key) if hex_key else None)


def encrypt_with_context(ks: KeyService, context: dict[str, str], plaintext: bytes) -> Envelope:
    """Envelope-encrypt bytes under a fresh data key bound to ``context`` (B2: TOTP seeds)."""
    dk, wrapped = ks.generate_data_key(context)
    nonce = os.urandom(12)
    return Envelope(nonce + AESGCM(dk).encrypt(nonce, plaintext, json.dumps(context, sort_keys=True).encode()),
                    wrapped, ks.key_arn)


def decrypt_with_context(ks: KeyService, context: dict[str, str], ciphertext: bytes, wrapped: bytes) -> bytes:
    dk = ks.decrypt_data_key(wrapped, context)
    return AESGCM(dk).decrypt(ciphertext[:12], ciphertext[12:], json.dumps(context, sort_keys=True).encode())

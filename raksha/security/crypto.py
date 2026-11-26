"""Key handling and at-rest encryption for intermediates.

* Keys are derived from RAKSHA_SECRET with HKDF-SHA256 and a purpose label (key separation):
  one sub-key for pseudonyms, one for date shifts, one for the spill vault.
* The vault encrypts any intermediate that would otherwise touch disk with AES-256-GCM
  (random 96-bit nonce from os.urandom, file name + purpose bound as associated data).
  The key lives only in process memory and is never written anywhere.
"""
from __future__ import annotations

import hashlib
import hmac
import os


def hkdf(secret: bytes, label: str, length: int = 32) -> bytes:
    """RFC 5869 HKDF-SHA256 (extract + expand) with a fixed salt and a purpose label."""
    prk = hmac.new(b"raksha-hkdf-salt-v1", secret, hashlib.sha256).digest()
    out, block, i = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + label.encode() + bytes([i]), hashlib.sha256).digest()
        out += block
        i += 1
    return out[:length]


class Keyring:
    """Purpose-separated keys derived once from the release secret."""

    def __init__(self, secret: bytes):
        if not secret:
            raise ValueError("empty secret")
        self.pseudonym = hkdf(secret, "pseudonym")
        self.shift = hkdf(secret, "date-shift")
        self.vault = hkdf(secret, "vault-aes-gcm")
        self.misc = hkdf(secret, "misc")

    def mac(self, key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


class Vault:
    """AES-GCM sealed blobs. Used only when policy security.spill_to_disk is true."""

    def __init__(self, key: bytes):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self._aead = AESGCM(key)

    def seal(self, data: bytes, aad: bytes = b"") -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, data, aad)

    def open(self, blob: bytes, aad: bytes = b"") -> bytes:
        return self._aead.decrypt(blob[:12], blob[12:], aad)

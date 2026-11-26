"""Keyed, non-reversible pseudonyms: PSN- + Crockford base32 of HMAC-SHA256(pseudonym key, 'psn|' + cluster key).

The cluster key is the minimum of the cluster's strongest identifiers (order-independent), so the same
patient gets the same pseudonym whatever the file order. Different RAKSHA_SECRET -> different key
(HKDF sub-key) -> unrelated pseudonyms. Collisions extend every colliding code deterministically.
"""
from __future__ import annotations

import hashlib
import hmac

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def b32(digest: bytes, n: int) -> str:
    v = int.from_bytes(digest, "big")
    out = []
    for _ in range(n):
        out.append(ALPHABET[v & 31])
        v >>= 5
    return "".join(out)


def assign(cluster_keys: dict, key: bytes, prefix: str = "PSN-", length: int = 6) -> dict:
    """cluster id -> pseudonym, collision-free."""
    digests = {cid: hmac.new(key, ("psn|" + ck).encode("utf-8"), hashlib.sha256).digest()
               for cid, ck in cluster_keys.items()}
    n = length
    while True:
        codes = {cid: b32(d, n) for cid, d in digests.items()}
        if len(set(codes.values())) == len(codes) or n >= 40:
            break
        n += 1
    return {cid: prefix + c for cid, c in codes.items()}

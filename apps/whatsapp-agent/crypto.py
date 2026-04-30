"""Hashing + encryption utilities. All PII handling goes through here."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config import get_settings


# ── Phone hashing ──────────────────────────────────────────────────────────
# SHA-256 with a server-side pepper. Pepper MUST stay constant across the
# lifetime of the system — rotating it breaks every existing user identity.

def hash_phone(phone: str) -> str:
    """Hash a phone number deterministically. `phone` may include 'whatsapp:' prefix."""
    pepper = get_settings().phone_hash_pepper.encode("utf-8")
    if not pepper:
        raise RuntimeError("PHONE_HASH_PEPPER not configured")
    normalized = _normalize_phone(phone).encode("utf-8")
    digest = hmac.new(pepper, normalized, hashlib.sha256).hexdigest()
    return digest


def _normalize_phone(phone: str) -> str:
    """Strip 'whatsapp:' prefix, '+', spaces. Keep digits only."""
    p = phone.lower().strip()
    if p.startswith("whatsapp:"):
        p = p[len("whatsapp:"):]
    return "".join(ch for ch in p if ch.isdigit())


# ── PII encryption (AES-256-GCM) ───────────────────────────────────────────
# We store raw phones encrypted so we can send replies. Format on disk:
#   12-byte nonce || ciphertext || 16-byte tag  (all concatenated)
# AESGCM.encrypt returns ciphertext+tag; we prepend the nonce.

def _key() -> bytes:
    raw = get_settings().pii_encryption_key
    if not raw:
        # Fallback for dev: derive from pepper (NOT for production)
        return hashlib.sha256(get_settings().phone_hash_pepper.encode()).digest()
    # Accept hex (output of `openssl rand -hex 32`)
    if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    # Accept base64
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    # Anything else: hash it down to 32 bytes
    return hashlib.sha256(raw.encode("utf-8")).digest()


def encrypt_pii(plaintext: str) -> bytes:
    """Encrypt a string. Returns nonce(12) || ct || tag(16)."""
    if plaintext is None:
        return b""
    aes = AESGCM(_key())
    nonce = secrets.token_bytes(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ct


def decrypt_pii(blob: bytes | memoryview | None) -> str:
    if blob is None:
        return ""
    if isinstance(blob, memoryview):
        blob = bytes(blob)
    if len(blob) < 12 + 16:
        raise ValueError("ciphertext too short")
    nonce, ct = blob[:12], blob[12:]
    aes = AESGCM(_key())
    return aes.decrypt(nonce, ct, None).decode("utf-8")


# ── Generic helpers ────────────────────────────────────────────────────────

def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def random_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_ip(ip: str) -> str:
    """Hash an IP for audit logs (less sensitive than phone, simple SHA-256 with pepper)."""
    pepper = get_settings().phone_hash_pepper.encode("utf-8")
    return hmac.new(pepper, ip.encode("utf-8"), hashlib.sha256).hexdigest()[:16]

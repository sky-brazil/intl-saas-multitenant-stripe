"""Token and webhook signature helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_access_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_hmac_signature(payload: bytes, signature: str | None, secret: str | None) -> bool:
    """Validate webhook payload signature.

    If no secret is configured, signature validation is skipped.
    """
    if not secret:
        return True
    if not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)

"""Content hashing. Every input to scoring is content-hashed (CLAUDE.md)."""

import hashlib


def content_hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

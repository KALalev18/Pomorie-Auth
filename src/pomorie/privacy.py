"""Pseudonymisation helpers.

HMAC-SHA256 with a secret key, not a plain hash: Bulgarian plates follow a small,
enumerable format, so an unkeyed SHA-256 could be reversed by hashing every possible
plate. Without the key the hash reveals nothing; with it we can still match "the same
plate reported again", which the fraud checks need.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from pomorie.config import get_settings

# Bulgarian plates use the Cyrillic letters that look like Latin ones (А В Е К М Н О Р С Т У Х).
# Residents type either alphabet, so map both to one form before hashing.
_CYRILLIC_TO_LATIN = str.maketrans("АВЕКМНОРСТУХ", "ABEKMHOPCTYX")
_NON_ALNUM = re.compile(r"[^0-9A-Z]")


def normalise_plate(plate: str) -> str:
    return _NON_ALNUM.sub("", plate.upper().translate(_CYRILLIC_TO_LATIN))


def pseudonym(value: str, purpose: str, key: str | None = None) -> str:
    """Keyed hash of ``value``. ``purpose`` separates domains so ids can't be cross-joined."""
    secret = (key or get_settings().pseudonym_key).encode()
    return hmac.new(secret, f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def plate_hash(plate: str, key: str | None = None) -> str | None:
    normalised = normalise_plate(plate)
    return pseudonym(normalised, "plate", key) if normalised else None

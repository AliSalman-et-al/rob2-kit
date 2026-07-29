"""Canonical byte representation and content hashes."""

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def canonical_json_bytes(value: BaseModel | Any) -> bytes:
    """Return deterministic, compact UTF-8 JSON bytes."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=False)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_digest(data: bytes) -> str:
    """Hash exact bytes using the required algorithm-labelled form."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def canonical_hash(value: BaseModel | Any) -> str:
    """Hash the canonical JSON representation of a structured value."""
    return sha256_digest(canonical_json_bytes(value))

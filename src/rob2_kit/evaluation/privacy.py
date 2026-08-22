"""Strict allow-list for public retained evaluation evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any

_FORBIDDEN = {
    "source",
    "sources",
    "text",
    "extracted_text",
    "prompt",
    "credential",
    "credentials",
    "password",
    "token",
    "path",
    "private_artifact",
    "artifact_path",
}


@dataclass(frozen=True)
class RetainedEvidenceManifest:
    schema_version: str
    run_id: str
    identities: dict[str, str]
    timings: dict[str, float | int]
    counts: dict[str, int]
    hashes: dict[str, str]
    review_references: tuple[str, ...]
    final_references: tuple[str, ...]
    verifier_output: dict[str, Any]
    config_before_hash: str
    config_after_hash: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RetainedEvidenceManifest:
        allowed = set(cls.__annotations__)
        forbidden = set(value) - allowed
        if forbidden:
            raise ValueError(f"privacy manifest has forbidden keys: {sorted(forbidden)}")
        cls._reject(value)
        return cls(**value)

    @classmethod
    def _reject(cls, value: Any, key: str = "") -> None:
        if key.casefold() in _FORBIDDEN:
            raise ValueError(f"privacy manifest retains forbidden {key}")
        if isinstance(value, dict):
            for item_key, item in value.items():
                cls._reject(item, str(item_key))
        elif isinstance(value, (list, tuple)):
            for item in value:
                cls._reject(item, key)
        elif isinstance(value, str) and (
            "\\" in value or "/" in value or "-----begin" in value.casefold()
        ):
            raise ValueError("privacy manifest retains path-like or credential-like content")

    @property
    def identity(self) -> str:
        return (
            "sha256:"
            + sha256(
                json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )

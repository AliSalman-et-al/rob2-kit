"""Explicit time and identifier policy for deterministic qualification runs."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class QualificationDeterminism:
    """An immutable normalized execution contract used only by release qualification."""

    observed_at: datetime
    namespace: uuid.UUID = uuid.NAMESPACE_URL
    seed: str = "rob2-qualification"

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() != UTC.utcoffset(
            self.observed_at
        ):
            raise ValueError("qualification time must be a UTC instant")

    def now(self) -> datetime:
        return self.observed_at

    def event_identifiers(
        self, operation_key: str, revision_id: str, sequence: int
    ) -> tuple[str, str]:
        seed = f"{self.seed}|{sequence}|{operation_key}|{revision_id}"
        return (
            f"operation:{uuid.uuid5(self.namespace, f'operation|{seed}')}",
            f"event:{uuid.uuid5(self.namespace, f'event|{seed}')}",
        )

    def run_id(self, digest: str, _root: Path, event_count: int) -> str:
        material = f"{digest}|{self.seed}|{event_count}".encode()
        return f"run:{hashlib.sha256(material).hexdigest()[:24]}"

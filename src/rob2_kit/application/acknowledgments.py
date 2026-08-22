"""Exact verification for durable researcher and host acknowledgments."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ._state import identity, read_json, record_uri
from .contracts import RecordReference, ReviewAcknowledgmentReference, ReviewAuthority


class StoredReviewAcknowledgment(BaseModel):
    """The complete, closed durable acknowledgment payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str = "review_ack"
    identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    uri: str = Field(pattern=r"^rob2://detail/review_ack/sha256:[0-9a-f]{64}$")
    record: RecordReference
    authority: ReviewAuthority
    purpose: str
    caller: str = Field(min_length=1)
    observed_at: str = Field(min_length=1)


def verify_acknowledgment(
    workspace: str | Path,
    filename: str,
    reference: ReviewAcknowledgmentReference,
    *,
    record: RecordReference,
    purpose: str,
    authority: ReviewAuthority,
) -> ReviewAcknowledgmentReference | None:
    raw = read_json(workspace, filename)
    if raw is None:
        return None
    try:
        if set(raw) != {
            "kind", "identity", "uri", "record", "authority", "purpose", "caller", "observed_at"
        }:
            return None
        stored = StoredReviewAcknowledgment.model_validate(raw)
        observed = datetime.fromisoformat(stored.observed_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    payload = {
        key: raw.get(key)
        for key in ("record", "authority", "purpose", "caller", "observed_at")
    }
    if (
        stored.kind != "review_ack"
        or stored.identity != reference.identity
        or stored.uri != reference.uri
        or reference.uri != record_uri("review_ack", reference.identity)
        or raw.get("record") != record.model_dump(mode="json")
        or raw.get("authority") != authority.value
        or raw.get("purpose") != purpose
        or not isinstance(raw.get("caller"), str)
        or not raw["caller"].startswith(
            ("cli:", "server:") if authority is ReviewAuthority.RESEARCHER else ("host:",)
        )
        or observed.tzinfo is None
        or observed.utcoffset() != UTC.utcoffset(observed)
        or identity(payload) != reference.identity
    ):
        return None
    return reference

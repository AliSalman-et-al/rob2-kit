from datetime import UTC, datetime, timedelta, timezone

import pytest

from rob2_kit.judgment_models import Override, TextEvidenceRef, VisualEvidenceRef
from rob2_kit.models import StrictModel, canonical_json_bytes


class _Timestamp(StrictModel):
    observed_at: datetime


def test_evidence_text_is_preserved_and_visual_requires_full_page_region() -> None:
    ref = TextEvidenceRef(
        source_id=" s ", source_sha256=" h ", page_number=1, start=0, end=1, quote=" q "
    )
    assert (ref.source_id, ref.quote) == (" s ", " q ")
    with pytest.raises(ValueError, match="full normalized"):
        VisualEvidenceRef(
            source_id="s",
            source_sha256="h",
            page_number=1,
            origin="rendered_page",
            region=(0, 0, 0.5, 1),
            image_sha256="i",
            transcription="text",
        )


def test_override_requires_utc_and_preserves_actor() -> None:
    override = Override(
        justification=" reason ", actor=" reviewer ", observed_at=datetime(2026, 8, 13, tzinfo=UTC)
    )
    assert (override.justification, override.actor) == (" reason ", " reviewer ")
    with pytest.raises(ValueError, match="UTC"):
        Override(justification="reason", actor="reviewer", observed_at=datetime(2026, 8, 13))


def test_canonical_timestamps_are_z_normalized_recursively() -> None:
    instant = datetime(2026, 8, 13, 5, tzinfo=timezone(timedelta(hours=5)))
    raw = {"nested": [instant]}
    model = _Timestamp(observed_at=instant)
    assert canonical_json_bytes(raw) == b'{"nested":["2026-08-13T00:00:00Z"]}'
    assert canonical_json_bytes({"observed_at": instant}) == canonical_json_bytes(model)
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_json_bytes({"nested": [datetime(2026, 8, 13)]})

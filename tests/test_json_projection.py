from __future__ import annotations

from pathlib import Path

import pytest

from rob2_kit.application._state import InvalidJSONSourceError, _pages


def test_invalid_json_is_a_controlled_actionable_error() -> None:
    with pytest.raises(InvalidJSONSourceError, match=r"invalid JSON source source\.json"):
        _pages(Path("source.json"), b'{"missing":')

    with pytest.raises(InvalidJSONSourceError, match=r"non-standard JSON constant NaN"):
        _pages(Path("source.json"), b"NaN")

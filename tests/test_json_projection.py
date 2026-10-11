from __future__ import annotations

from pathlib import Path

import pytest

from rob2_kit.application._state import InvalidJSONSourceError, _pages


def test_json_projection_is_sorted_path_addressable_and_preserves_array_order() -> None:
    raw = b'{"z":[{"b":true,"a":null},[],{}],"a.b":"line\\nx","empty":{"nested":[]}}'

    pages = _pages(Path("source.json"), raw)

    assert pages == (
        '["a.b"]: "line"\n'
        '["a.b"]: "x"\n'
        "empty.nested: []\n"
        "z[0].a: null\n"
        "z[0].b: true\n"
        "z[1]: []\n"
        "z[2]: {}",
    )


def test_invalid_json_is_a_controlled_actionable_error() -> None:
    with pytest.raises(InvalidJSONSourceError, match=r"invalid JSON source source\.json"):
        _pages(Path("source.json"), b'{"missing":')

    with pytest.raises(InvalidJSONSourceError, match=r"non-standard JSON constant NaN"):
        _pages(Path("source.json"), b"NaN")

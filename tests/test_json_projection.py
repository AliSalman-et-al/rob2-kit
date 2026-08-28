from __future__ import annotations

import hashlib
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


def test_json_projection_preserves_empty_segments_in_multiline_scalars() -> None:
    raw = b'{"note":"before\\n\\nlast\\r\\n"}'

    assert _pages(Path("source.json"), raw) == ('note: "before"\nnote: ""\nnote: "last"\nnote: ""',)


def test_json_projection_keeps_single_line_scalar_strings_unchanged() -> None:
    assert _pages(Path("source.json"), b'{"note":"before"}') == ('note: "before"',)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"7", ("$: 7",)),
        (b"[]", ("$: []",)),
        (b"{}", ("$: {}",)),
    ],
)
def test_json_projection_represents_root_leaves(raw: bytes, expected: tuple[str, ...]) -> None:
    assert _pages(Path("source.json"), raw) == expected


def test_json_projection_does_not_change_captured_bytes() -> None:
    raw = b'{"value": "keep these bytes exactly"}\r\n'
    digest = hashlib.sha256(raw).digest()

    _pages(Path("source.json"), raw)

    assert hashlib.sha256(raw).digest() == digest


def test_invalid_json_is_a_controlled_actionable_error() -> None:
    with pytest.raises(InvalidJSONSourceError, match=r"invalid JSON source source\.json"):
        _pages(Path("source.json"), b'{"missing":')

    with pytest.raises(InvalidJSONSourceError, match=r"non-standard JSON constant NaN"):
        _pages(Path("source.json"), b"NaN")

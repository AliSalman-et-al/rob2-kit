import json
from math import nan

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rob2_kit.domain.canonical import canonical_hash, canonical_json_bytes, sha256_digest


@given(st.dictionaries(st.text(min_size=1), st.integers(), max_size=10))
def test_canonical_json_is_independent_of_mapping_order(value: dict[str, int]) -> None:
    reversed_value = dict(reversed(tuple(value.items())))
    assert canonical_json_bytes(value) == canonical_json_bytes(reversed_value)
    assert canonical_hash(value) == canonical_hash(reversed_value)


def test_canonical_json_is_utf8_compact_and_has_known_hash() -> None:
    value = {"é": "RoB 2", "answer": "yes"}
    encoded = canonical_json_bytes(value)
    assert encoded == '{"answer":"yes","é":"RoB 2"}'.encode()
    assert canonical_hash(value) == sha256_digest(encoded)


def test_non_json_numbers_are_rejected() -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"invalid": nan})


def test_canonical_bytes_are_valid_json() -> None:
    assert json.loads(canonical_json_bytes({"value": 3})) == {"value": 3}

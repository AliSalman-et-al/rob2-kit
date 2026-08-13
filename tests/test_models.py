from typing import Any, cast

import pytest
from pydantic import ValidationError

from rob2_kit.models import Answer, Question, canonical_json_bytes, sha256


def test_models_are_strict_immutable_and_canonical():
    with pytest.raises(ValidationError):
        Question(
            **cast(dict[str, Any], {"id": "x", "domain_id": "d", "wording": "w", "extra": "no"})
        )
    question = Question(id="x", domain_id="d", wording="w")
    with pytest.raises(ValidationError):
        cast(Any, question).wording = "changed"
    assert canonical_json_bytes({"b": 1, "a": Answer.YES}) == b'{"a":"yes","b":1}'
    assert sha256({"b": 1, "a": Answer.YES}).startswith("sha256:")

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rob2_kit.application.finalization import _valid_result_shape
from rob2_kit.workflow_models import CategoryProfileResult


def _category(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "category_axes": ["Any event", "Grade 3"],
        "value": "65",
    }
    value.update(overrides)
    return value


def _profile(categories: list[dict[str, object]]) -> dict[str, object]:
    return {
        "form": "single_group_category_profile",
        "endpoint": {"name": "adverse events", "definition": "grade 3 or higher"},
        "group_id": "intervention",
        "denominator_basis": "follow-up participants",
        "category_axis_names": ["event", "grade"],
        "categories": categories,
    }


def test_category_profile_requires_complete_axis_key() -> None:
    with pytest.raises(ValidationError):
        CategoryProfileResult.model_validate(
            _profile([{**_category(), "group_or_category": "Any event"}])
        )

    with pytest.raises(ValidationError):
        CategoryProfileResult.model_validate(_profile([_category(category_axes=["Any event", ""])]))


def test_profile_measurement_metadata_is_declared_once() -> None:
    profile = CategoryProfileResult.model_validate(
        _profile(
            [
                _category(),
                _category(
                    category_axes=["Any event", "Grade 4"],
                    value="16.7",
                ),
            ]
        )
    )
    assert [item.category_axes for item in profile.categories] == [
        ("Any event", "Grade 3"),
        ("Any event", "Grade 4"),
    ]
    assert profile.denominator_basis == "follow-up participants"


def test_repeated_cell_metadata_produces_one_actionable_validation_error() -> None:
    cells = [
        _category(category_axes=["Any event", grade], evidence="eh_0000000000000000")
        for grade in ("Grade 3", "Grade 4", "Grade 5")
    ]
    with pytest.raises(ValidationError) as caught:
        CategoryProfileResult.model_validate(_profile(cells))

    assert len(caught.value.errors()) == 1
    assert "do not repeat Evidence handles" in str(caught.value)


def test_category_axes_may_repeat_when_positions_are_distinct_dimensions() -> None:
    profile = CategoryProfileResult.model_validate(
        _profile([_category(category_axes=["All", "All"])])
    )
    assert profile.categories[0].category_axes == ("All", "All")


def test_category_profile_supports_one_dimensional_cells() -> None:
    profile = CategoryProfileResult.model_validate(
        {
            **_profile([_category(category_axes=["Any event"])]),
            "category_axis_names": ["event"],
        }
    )
    assert profile.category_axis_names == ("event",)


def test_category_profile_rejects_axis_arity_mismatch() -> None:
    with pytest.raises(ValidationError, match="arity"):
        CategoryProfileResult.model_validate(_profile([_category(category_axes=["Any event"])]))


def test_duplicate_category_axes_are_rejected_in_replay_shape() -> None:
    result: dict[str, object] = {
        "trial_id": "trial",
        "target": {"comparison_groups": [{"id": "intervention"}]},
        "reported": _profile([_category(), _category()]),
    }
    assert not _valid_result_shape(result, "adverse events")

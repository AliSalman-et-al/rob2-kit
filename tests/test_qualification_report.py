from __future__ import annotations

from copy import deepcopy

import pytest

from rob2_kit.evaluation.qualification_report import SCHEMA, identity, promotion_decision, validate


def _report() -> dict:
    frozen = {
        name: identity({"name": name, "revision": 1})
        for name in ("build", "pack", "skill", "source", "config")
    }
    return {
        "schema": SCHEMA,
        "identity": frozen,
        "mechanical": [
            {
                "check_id": "integrity-1",
                "kind": "integrity",
                "status": "completion",
                "observed": True,
            }
        ],
        "observations": [
            _observation("text", "text-1"),
            _observation("image", "image-1"),
            _observation("guidance", "guidance-1"),
            _observation("schema", "schema-1"),
            _observation("continuation", "continuation-1"),
        ],
        "attempts": [{"attempt_id": "attempt-1", "host": "codex", "status": "completion"}],
        "promotion": "promote",
    }


def _observation(kind: str, observation_id: str) -> dict:
    return {
        "observation_id": observation_id,
        "attempt_id": "attempt-1",
        "host": "codex",
        "kind": kind,
        "status": "completion",
        "observable": True,
    }


def test_complete_observable_report_promotes_deterministically() -> None:
    report = _report()
    assert validate(report) == []
    assert promotion_decision(report) == "promote"
    assert report == deepcopy(report)


def test_unobservable_host_check_is_retained_and_forces_hold() -> None:
    report = _report()
    report["observations"][1]["observable"] = None
    report["observations"][1]["status"] = "unsupported_reassurance"
    report["promotion"] = "hold"
    assert validate(report) == []
    assert promotion_decision(report) == "hold"


def test_failures_are_retained_and_private_fields_are_rejected() -> None:
    report = _report()
    report["attempts"].append(
        {"attempt_id": "failed-1", "host": "claude-code", "status": "failure"}
    )
    report["promotion"] = "hold"
    assert validate(report) == []
    private = deepcopy(report)
    private["observations"][0]["prompt"] = "must not be retained"
    assert any("private field" in error for error in validate(private))
    assert all("must not be retained" not in error for error in validate(private))


def test_closed_enums_and_false_promotion_are_rejected() -> None:
    report = _report()
    report["observations"][0]["status"] = "pass"
    assert validate(report)
    report = _report()
    report["promotion"] = "promote"
    report["observations"][0]["observable"] = False
    assert "promotion does not match recorded evidence" in "; ".join(validate(report))


def test_required_host_observation_matrix_is_closed() -> None:
    report = _report()
    report["observations"] = report["observations"][:1]
    report["promotion"] = "hold"
    assert any("required host observations are missing" in error for error in validate(report))
    assert promotion_decision(report) == "hold"


def test_required_observation_matrix_is_complete_for_each_attempt_host() -> None:
    report = _report()
    report["attempts"].append(
        {"attempt_id": "attempt-2", "host": "claude-code", "status": "completion"}
    )
    report["observations"][1]["attempt_id"] = "attempt-2"
    report["observations"][1]["host"] = "claude-code"
    report["promotion"] = "hold"

    errors = validate(report)

    assert any("for codex" in error for error in errors)
    assert any("for claude-code" in error for error in errors)
    assert promotion_decision(report) == "hold"


def test_observation_host_must_match_its_attempt() -> None:
    report = _report()
    report["observations"][0]["host"] = "claude-code"
    report["promotion"] = "hold"

    errors = validate(report)

    assert "observations[0] host does not match its attempt" in errors
    assert promotion_decision(report) == "hold"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda report: report["mechanical"][0].update({"check_id": []}),
        lambda report: report["mechanical"][0].update({"kind": []}),
        lambda report: report["observations"][0].update({"observation_id": []}),
        lambda report: report["observations"][0].update({"observable": []}),
        lambda report: report["attempts"][0].update({"attempt_id": []}),
        lambda report: report["attempts"][0].update({"status": []}),
    ),
)
def test_malformed_json_is_held_without_raising_type_errors(mutate) -> None:
    report = _report()
    mutate(report)
    assert validate(report)
    assert promotion_decision(report) == "hold"


def test_malformed_promotion_is_held_without_raising_type_errors() -> None:
    report = _report()
    report["promotion"] = []
    assert validate(report)
    assert promotion_decision(report) == "hold"

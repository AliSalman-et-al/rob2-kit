from __future__ import annotations

# ruff: noqa: E501
from pathlib import Path

import pytest

from rob2_kit.application._state import read_json, write_jsons
from rob2_kit.application.contracts import ReviewAuthority
from rob2_kit.application.intake import (
    CaptureRequest,
    IntakePlanEntry,
    SourceCriticality,
    SourceDisposition,
    acknowledge_intake,
    capture_batch,
    save_intake_plan,
)
from rob2_kit.application.preflight import (
    AuthorizedSourceRoot,
    PreflightRequest,
    inspect_candidate_sources,
    preflight_sources,
)
from rob2_kit.application.status import current_status


def test_capture_replays_and_reports_changed_bytes(tmp_path: Path) -> None:
    (tmp_path / "article.txt").write_text("article", encoding="utf-8")
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(
            roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="trial"),)
        ),
    )
    plan = save_intake_plan(
        tmp_path,
        preflight.reference,
        (
            IntakePlanEntry(
                candidate_identity=preflight.candidates[0].identity,
                role="main_article",
                disposition=SourceDisposition.INCLUDE,
                criticality=SourceCriticality.REQUIRED,
            ),
        ),
    )
    acknowledgment = acknowledge_intake(tmp_path, plan.plan, ReviewAuthority.HOST)
    (tmp_path / "article.txt").write_text("changed", encoding="utf-8")
    drift = capture_batch(
        tmp_path, CaptureRequest(plan=plan.plan, acknowledgment=acknowledgment)
    )
    assert "changed_bytes:trial:article.txt" in drift.conditions
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(
            roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="trial"),)
        ),
    )
    plan = save_intake_plan(
        tmp_path,
        preflight.reference,
        (
            IntakePlanEntry(
                candidate_identity=preflight.candidates[0].identity,
                role="main_article",
                disposition=SourceDisposition.INCLUDE,
                criticality=SourceCriticality.REQUIRED,
            ),
        ),
    )
    acknowledgment = acknowledge_intake(tmp_path, plan.plan, ReviewAuthority.HOST)
    first = capture_batch(
        tmp_path, CaptureRequest(plan=plan.plan, acknowledgment=acknowledgment)
    )
    assert capture_batch(
        tmp_path, CaptureRequest(plan=plan.plan, acknowledgment=acknowledgment)
    ).captured_batch == first.captured_batch


def _ready_capture(tmp_path: Path):
    (tmp_path / "article.txt").write_text("article", encoding="utf-8")
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="trial"),)),
    )
    plan = save_intake_plan(
        tmp_path,
        preflight.reference,
        (IntakePlanEntry(candidate_identity=preflight.candidates[0].identity, role="main_article", disposition=SourceDisposition.INCLUDE, criticality=SourceCriticality.REQUIRED),),
    )
    ack = acknowledge_intake(tmp_path, plan.plan, ReviewAuthority.HOST)
    return plan, ack


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("purpose", "proposal"),
        ("authority", "researcher"),
        ("record", {"kind": "proposal_review", "identity": "sha256:" + "0" * 64, "uri": "rob2://detail/proposal_review/sha256:" + "0" * 64}),
        ("caller", "host"),
        ("observed_at", "not-a-time"),
        ("identity", "sha256:" + "0" * 64),
        ("uri", "rob2://detail/review_ack/sha256:" + "0" * 64),
    ),
)
def test_capture_rejects_corrupt_intake_ack_before_publication(tmp_path: Path, field: str, value: object) -> None:
    plan, ack = _ready_capture(tmp_path)
    raw = read_json(tmp_path, "review_ack.json")
    assert raw is not None
    raw[field] = value
    write_jsons(tmp_path, {"review_ack.json": raw})
    with pytest.raises(ValueError):
        capture_batch(tmp_path, CaptureRequest(plan=plan.plan, acknowledgment=ack))
    state = read_json(tmp_path, "state.json")
    assert state is not None and not state.get("captured_identity")


@pytest.mark.parametrize("conditional", (False, True))
def test_restart_retains_exact_intake_capture_authority(tmp_path: Path, conditional: bool) -> None:
    (tmp_path / "main.txt").write_text("main", encoding="utf-8")
    if conditional:
        (tmp_path / "supplement.txt").write_text("supplement", encoding="utf-8")
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="trial"),)),
    )
    entries = []
    for candidate in preflight.candidates:
        entries.append(
            IntakePlanEntry(
                candidate_identity=candidate.identity,
                role="main_article" if candidate.relative_path == "main.txt" else "supplement",
                disposition=(SourceDisposition.OMIT if conditional and candidate.relative_path == "supplement.txt" else SourceDisposition.INCLUDE),
                criticality=(SourceCriticality.OPTIONAL if candidate.relative_path == "supplement.txt" else SourceCriticality.REQUIRED),
                omission_reason=("not needed" if candidate.relative_path == "supplement.txt" else None),
            )
        )
    plan = save_intake_plan(tmp_path, preflight.reference, tuple(entries))
    authority = ReviewAuthority.RESEARCHER if conditional else ReviewAuthority.HOST
    caller = "cli:test" if conditional else "host:mcp"
    acknowledgment = acknowledge_intake(tmp_path, plan.plan, authority, caller=caller)
    restarted = current_status(tmp_path)
    assert restarted.presentation.code == "capture_ready"
    assert restarted.review.required is authority
    assert restarted.review.satisfied
    assert restarted.continuation is not None
    captured = capture_batch(tmp_path, CaptureRequest(plan=plan.plan, acknowledgment=acknowledgment))
    assert captured.outcome.value == "success"


def test_candidate_inspection_rejects_a_tampered_preflight(tmp_path: Path) -> None:
    (tmp_path / "article.txt").write_text("article", encoding="utf-8")
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(roots=(AuthorizedSourceRoot(alias="trial", path=".", trial_id="trial"),)),
    )
    raw = read_json(tmp_path, "preflight.json")
    assert raw is not None
    raw["candidates"][0]["pages"] = ["forged"]
    write_jsons(tmp_path, {"preflight.json": raw})
    with pytest.raises(ValueError, match="active preflight"):
        inspect_candidate_sources(tmp_path, preflight.candidates[0])


def test_preflight_records_a_typed_registry_condition_for_each_empty_trial(tmp_path: Path) -> None:
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    preflight = preflight_sources(
        tmp_path,
        PreflightRequest(
            roots=(
                AuthorizedSourceRoot(alias="one", path="one", trial_id="one"),
                AuthorizedSourceRoot(alias="two", path="two", trial_id="two"),
            )
        ),
    )
    assert preflight.registry_attempts == 0
    assert preflight.registry_outcomes == ()
    assert preflight.conditions == ("registry_no_candidate:one", "registry_no_candidate:two")

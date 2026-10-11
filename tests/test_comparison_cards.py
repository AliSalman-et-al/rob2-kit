from __future__ import annotations

from pathlib import Path

from support.rob2 import _assessment_workspace, _call, _domain_draft


def _save_domain(
    workspace: Path,
    domain_id: str,
    revision: int,
    evidence: dict[str, object],
) -> int:
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", domain_id, revision, evidence),
    )
    assert saved["outcome"] == "success", saved
    return int(saved["head"]["state_revision"])


def test_missing_data_card_marks_conflicting_typed_counts(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    revision = _save_domain(workspace, "domain:randomization", revision, evidence)
    revision = _save_domain(workspace, "domain:deviations", revision, evidence)
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    answer = next(
        item for item in draft["answers"] if item["question_id"] == "sq:missing:data-available"
    )
    row = {
        "arm": "intervention",
        "population": "randomized participants",
        "unit": "participants",
        "time_point": "week 12",
        "randomized": 100,
        "observed": 95,
    }
    answer["missing_data"] = [row, row | {"observed": 94}]
    saved = _call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success", saved

    context = _call(
        workspace,
        "get_domain_context",
        {"domain_id": "domain:missing"},
    )["data"]
    card = context["comparison_cards"][0]
    slots = {item["name"]: item for item in card["slots"]}
    assert slots["approved_outcome"]["status"] == "supported"
    assert slots["randomized"]["status"] == "supported"
    assert slots["observed"]["status"] == "conflicted"
    assert card["missing_data"]["conflicts"]
    assert slots["randomized"]["passages"]
    assert slots["follow_up_availability"]["status"] == "unknown"

from pathlib import Path

from support.rob2 import _assessment_workspace, _call, _domain_draft

from rob2_kit.application._state import _state
from rob2_kit.workflow_models import DomainSaveAnswer


def test_d3_recovery_tracks_required_questions_and_branch_changes(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain in ("domain:randomization", "domain:deviations"):
        saved = _call(
            workspace, "save_domain_judgment", _domain_draft("trial", domain, revision, evidence)
        )
        assert saved["outcome"] == "success", saved
        revision = saved["head"]["state_revision"]
    _call(workspace, "get_domain_context", {})
    draft = _domain_draft("trial", "domain:missing", revision, evidence)
    items = {row["question_id"]: row for row in draft["answers"]}
    q1, q2, q3, q4 = (
        "sq:missing:data-available",
        "sq:missing:evidence-unbiased",
        "sq:missing:true-value-dependent",
        "sq:missing:likely-dependent",
    )
    before = _state(workspace)
    for values, missing in [
        ({q1: "probably_no"}, q2),
        ({q1: "probably_no", q2: "no"}, q3),
        ({q1: "probably_no", q2: "no", q3: "probably_yes"}, q4),
    ]:
        rows = [{**items[q], "answer": value} for q, value in values.items()]
        repaired = _call(workspace, "save_domain_judgment", {**draft, "answers": rows})
        assert repaired["outcome"] == "repair", repaired
        defect = next(
            x for x in repaired["repairs"] if x["code"] == "answers_must_match_active_questions"
        )
        recovery = defect["answer_path"]
        assert recovery["active_question_ids"] == [*values, missing]
        assert recovery["missing_question_ids"] == [missing]
        schema = recovery["minimal_answer_schema"]
        assert set(schema["required"]) == set(DomainSaveAnswer.model_json_schema()["required"])
        assert schema["additionalProperties"] is False
        assert "default" not in schema["properties"]["answer"]
        assert schema["properties"]["bases"]["items"]["required"] == ["evidence", "role"]
        assert _state(workspace) == before
    # Changing an earlier response changes the active branch; no stale list is retained.
    rows = [{**items[q1], "answer": "probably_yes"}, {**items[q3], "answer": "no_information"}]
    saved = _call(workspace, "save_domain_judgment", {**draft, "answers": rows})
    assert saved["outcome"] == "success", saved
    assert saved["data"]["checkpoint"]["judgment"] == "low"

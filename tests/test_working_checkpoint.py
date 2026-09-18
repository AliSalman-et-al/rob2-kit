from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from support.rob2 import (
    _call,
    _domain_draft,
    _prepared_evidence,
    _proposal_args,
    _result,
    _review,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.application.status import _active_trial_and_domain
from rob2_kit.models import canonical_json_bytes
from rob2_kit.packs.scientific import SCIENTIFIC_PACK
from rob2_kit.workflow_models import WorkingCheckpoint


def _checkpoint(source_id: str, text: str = "Allocation concealment is not yet clear.") -> dict:
    return {
        "trial_id": "trial",
        "observations": [
            {
                "text": text,
                "sources": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
                "domain_id": "domain:randomization",
                "question_id": "sq:randomization:concealment",
            }
        ],
        "interpretations": [
            {
                "text": "The report does not describe who generated the sequence.",
                "sources": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
                "domain_id": "domain:randomization",
            }
        ],
        "terminology": [
            {
                "term": "central allocation",
                "meaning": "Assignment is issued after enrollment by a central service.",
                "sources": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
            }
        ],
        "unread_ranges": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
        "open_questions": [
            {
                "text": "Was the allocation sequence concealed until assignment?",
                "sources": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
                "domain_id": "domain:randomization",
                "question_id": "sq:randomization:concealment",
            }
        ],
        "drafts": [
            {
                "domain_id": "domain:randomization",
                "question_id": "sq:randomization:concealment",
                "answer": "no_information",
                "text": ("Do not treat the silence as evidence of inadequate concealment."),
                "sources": [{"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}],
            }
        ],
        "next_action": "Read the protocol section on sequence generation and concealment.",
    }


def _proposal_waiting_for_review(workspace: Path) -> dict:
    evidence = _prepared_evidence(workspace)
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert proposed["outcome"] == "review_required", proposed
    return evidence


def test_active_trial_follows_captured_batch_order() -> None:
    state = {
        "batch": {"trials": [{"id": "trial-z"}, {"id": "trial-a"}]},
        "trial_dispositions": {"trial-a": "pending", "trial-z": "pending"},
        "domain_records": {},
    }

    assert _active_trial_and_domain(state) == ("trial-z", SCIENTIFIC_PACK.domains[0].id)


def test_working_checkpoint_replaces_notes_without_changing_assessment_and_survives_approval(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    before = _state(workspace)
    source_id = evidence["source_id"]

    saved = _call(workspace, "save_working_checkpoint", {"checkpoint": _checkpoint(source_id)})

    assert saved["outcome"] == "success", saved
    assert saved["data"]["authoritative"] is False
    assert saved["data"]["result_identity"].startswith("sha256:")
    assert saved["head"]["state_revision"] == before["revision"]
    after_save = _state(workspace)
    assert after_save["trial_dispositions"] == before["trial_dispositions"]
    assert after_save.get("domain_records", {}) == before.get("domain_records", {})
    with sqlite3.connect(workspace / ".rob2-kit" / "canonical.sqlite3") as connection:
        canonical_count = connection.execute("SELECT COUNT(*) FROM canonical_records").fetchone()[0]
    with sqlite3.connect(workspace / ".rob2-kit" / "working.sqlite3") as connection:
        working_count = connection.execute("SELECT COUNT(*) FROM working_checkpoints").fetchone()[0]
    assert working_count == 1

    status = _call(workspace, "get_status", {})["data"]["working_checkpoint"]
    assert status["status"] == "current"
    assert status["checkpoint"]["drafts"][0]["answer"] == "no_information"
    assert status["checkpoint"]["unread_ranges"][0] == {
        "source_id": source_id,
        "page": 1,
        "start_line": 1,
        "end_line": 1,
    }

    replacement = _checkpoint(source_id, "Keep the uncertainty and reread the passage.")
    replaced = _call(workspace, "save_working_checkpoint", {"checkpoint": replacement})
    assert replaced["outcome"] == "success", replaced
    assert replaced["data"]["checkpoint_identity"] != saved["data"]["checkpoint_identity"]
    assert (
        _call(workspace, "get_status", {})["data"]["working_checkpoint"]["checkpoint"][
            "observations"
        ][0]["text"]
        == replacement["observations"][0]["text"]
    )
    with sqlite3.connect(workspace / ".rob2-kit" / "canonical.sqlite3") as connection:
        stored_count = connection.execute("SELECT COUNT(*) FROM canonical_records").fetchone()[0]
        assert stored_count == canonical_count
    with sqlite3.connect(workspace / ".rob2-kit" / "working.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM working_checkpoints").fetchone()[0] == 1

    _review(workspace)
    resumed = _call(workspace, "get_status", {})["data"]["working_checkpoint"]
    assert resumed["status"] == "current"
    assert resumed["checkpoint_identity"] == replaced["data"]["checkpoint_identity"]


def test_current_notes_avoid_duplicate_read_gate_on_approved_proposal_retry(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    _call(workspace, "save_working_checkpoint", {"checkpoint": _checkpoint(evidence["source_id"])})
    _review(workspace)

    retry = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))

    assert retry["outcome"] == "success", retry
    assert retry["data"].get("retry") is True


def test_working_checkpoint_yields_to_a_newer_canonical_domain_commit(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    _call(workspace, "save_working_checkpoint", {"checkpoint": _checkpoint(evidence["source_id"])})
    _review(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])

    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, evidence),
    )

    assert saved["outcome"] == "success", saved
    status = _call(workspace, "get_status", {})["data"]["working_checkpoint"]
    assert status["status"] == "stale"
    assert status["reason"] == "canonical_newer"
    assert status["checkpoint"] is None
    assert status["recovery"] == "resume_from_canonical_checkpoint"


def test_working_checkpoint_is_hidden_after_result_replacement(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    source_id = evidence["source_id"]
    _call(workspace, "save_working_checkpoint", {"checkpoint": _checkpoint(source_id)})
    _review(workspace)

    revised = _result(evidence)
    revised["target"]["time_point_or_window"]["description"] = "a corrected follow-up window"
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [revised]))

    assert proposed["outcome"] == "review_required", proposed
    status = _call(workspace, "get_status", {})["data"]["working_checkpoint"]
    assert status["status"] == "stale"
    assert status["reason"] == "result_changed"
    assert status["checkpoint"] is None
    assert status["recovery"] == "reorient_from_sources"


def test_working_checkpoint_is_hidden_when_bound_source_scope_differs(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    saved = _call(
        workspace,
        "save_working_checkpoint",
        {"checkpoint": _checkpoint(evidence["source_id"])},
    )
    assert saved["outcome"] == "success", saved
    database = workspace / ".rob2-kit" / "working.sqlite3"
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT batch_id,trial_id,payload FROM working_checkpoints"
        ).fetchone()
        payload = json.loads(row[2])
        payload["source_scope"][0]["projection_hash"] = "sha256:" + "f" * 64
        payload["identity"] = None
        checkpoint = WorkingCheckpoint.model_validate(payload)
        connection.execute(
            "UPDATE working_checkpoints SET identity=?,payload=? WHERE batch_id=? AND trial_id=?",
            (
                checkpoint.identity,
                canonical_json_bytes(checkpoint.model_dump(mode="json", exclude_none=True)),
                row[0],
                row[1],
            ),
        )

    status = _call(workspace, "get_status", {})["data"]["working_checkpoint"]
    assert status["status"] == "stale"
    assert status["reason"] == "source_changed"
    assert status["checkpoint"] is None


def test_missing_working_notes_request_reorientation_without_changing_assessment(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    saved = _call(
        workspace,
        "save_working_checkpoint",
        {"checkpoint": _checkpoint(evidence["source_id"])},
    )
    assert saved["outcome"] == "success", saved
    before = _state(workspace)
    with sqlite3.connect(workspace / ".rob2-kit" / "working.sqlite3") as connection:
        connection.execute("DELETE FROM working_checkpoints")

    status = _call(workspace, "get_status", {})["data"]["working_checkpoint"]
    assert status["status"] == "absent"
    assert status["reason"] == "not_saved"
    assert status["recovery"] == "reorient_from_sources"
    after = _state(workspace)
    assert after["revision"] == before["revision"]
    assert after["trial_dispositions"] == before["trial_dispositions"]
    assert after.get("domain_records", {}) == before.get("domain_records", {})


def test_working_checkpoint_survives_cold_rebuild_of_derivative_search_cache(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    saved = _call(
        workspace,
        "save_working_checkpoint",
        {"checkpoint": _checkpoint(evidence["source_id"])},
    )
    assert saved["outcome"] == "success", saved
    (workspace / ".rob2-kit" / "derivative.sqlite3").unlink()

    status = _call(workspace, "get_status", {})["data"]["working_checkpoint"]

    assert status["status"] == "current"
    assert status["checkpoint_identity"] == saved["data"]["checkpoint_identity"]
    assert (
        status["checkpoint"]["observations"][0]["text"]
        == _checkpoint(evidence["source_id"])["observations"][0]["text"]
    )
    assert (workspace / ".rob2-kit" / "derivative.sqlite3").is_file()
    assert (workspace / ".rob2-kit" / "working.sqlite3").is_file()

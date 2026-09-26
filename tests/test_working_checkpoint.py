from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError
from support.rob2 import (
    _call,
    _domain_draft,
    _prepared_evidence,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _review,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.application.status import _active_trial_and_domain
from rob2_kit.models import canonical_json_bytes
from rob2_kit.packs.scientific import SCIENTIFIC_PACK
from rob2_kit.workflow_models import WorkingCheckpoint, WorkingPremiseRecord


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
    assert _state(workspace).get("domain_records", {}) == {}


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
    assert status["checkpoint"] is not None
    assert status["checkpoint"]["observations"]
    assert status["stale_domains"] == [SCIENTIFIC_PACK.domains[0].id]
    assert status["recovery"] == "resume_from_checkpoint"


@pytest.mark.parametrize(
    "scenario",
    [
        "cohort",
        "fixed_time_probability",
        "follow_up_hazard_ratio",
        "adverse_event_threshold",
    ],
)
def test_working_checkpoint_is_hidden_after_result_scope_replacement(
    tmp_path: Path, scenario: str
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    source_id = evidence["source_id"]
    _call(workspace, "save_working_checkpoint", {"checkpoint": _checkpoint(source_id)})
    _review(workspace)

    revised = _result(evidence)
    if scenario == "cohort":
        revised["reported"]["analysis_population"] = "per-protocol population"
    elif scenario == "fixed_time_probability":
        revised["target"]["time_point_or_window"]["description"] = "12 weeks after randomization"
        revised["target"]["intended_effect_measure"] = "probability"
    elif scenario == "follow_up_hazard_ratio":
        revised["target"]["time_point_or_window"]["description"] = "end of follow-up"
        revised["target"]["intended_effect_measure"] = "hazard ratio"
    else:
        revised["target"]["measurement"]["method"] = (
            "grade 3 or higher treatment-emergent adverse events"
        )
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [revised]))

    assert proposed["outcome"] == "review_required", proposed
    status = _call(workspace, "get_status", {})["data"]["working_checkpoint"]
    assert status["status"] == "stale"
    assert status["reason"] == "result_changed"
    assert status["checkpoint"] is None
    assert status["recovery"] == "reorient_from_sources"


def test_working_checkpoint_is_isolated_per_workspace(tmp_path: Path) -> None:
    first = _workspace(tmp_path / "first")
    first_evidence = _proposal_waiting_for_review(first)
    saved = _call(
        first,
        "save_working_checkpoint",
        {"checkpoint": _checkpoint(first_evidence["source_id"])},
    )
    assert saved["outcome"] == "success", saved

    second = _workspace(tmp_path / "second")
    _proposal_waiting_for_review(second)
    status = _call(second, "get_status", {})["data"]["working_checkpoint"]

    assert status["status"] == "absent"
    assert status["reason"] == "not_saved"


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


def test_pre_premise_working_checkpoint_retains_legacy_identity(tmp_path: Path) -> None:
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
        payload.pop("premise_records")
        identity_payload = {key: value for key, value in payload.items() if key != "identity"}
        payload["identity"] = (
            "sha256:" + hashlib.sha256(canonical_json_bytes(identity_payload)).hexdigest()
        )
        encoded = canonical_json_bytes(payload)
        connection.execute(
            "UPDATE working_checkpoints SET identity=?,payload=? WHERE batch_id=? AND trial_id=?",
            (payload["identity"], encoded, row[0], row[1]),
        )

    status = _call(workspace, "get_status", {})["data"]["working_checkpoint"]
    assert status["status"] == "current"
    assert status["checkpoint_identity"] == payload["identity"]
    assert status["checkpoint"]["premise_records"] == []
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT payload FROM working_checkpoints").fetchone()[0] == encoded
        )


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

    status_data = _call(workspace, "get_status", {})["data"]
    status = status_data["working_checkpoint"]
    assert status["status"] == "absent"
    assert status["reason"] == "not_saved"
    assert status["recovery"] == "reorient_from_sources"
    investigation = status_data["investigation"]
    assert investigation["status"] == "not_established"
    assert investigation["sufficiency"]["attribution"] == "not_established"
    assert investigation["coverage"]["state"] == "delivered"
    choices = {item["operation"] for item in investigation["recovery_choices"]}
    assert {
        "save_working_checkpoint",
        "search_sources",
        "read_pages",
        "validate_domain_assessment",
    } <= choices
    after = _state(workspace)
    assert after["revision"] == before["revision"]
    assert after["trial_dispositions"] == before["trial_dispositions"]
    assert after.get("domain_records", {}) == before.get("domain_records", {})


def test_status_separates_delivered_text_from_host_note_references(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    _review(workspace)

    delivered = _call(workspace, "get_status", {})["data"]["investigation"]
    assert delivered["coverage"]["state"] == "delivered"
    assert delivered["coverage"]["delivered_sources"] == [evidence["source_id"]]
    assert delivered["coverage"]["sources_without_delivery"] == []
    assert delivered["host_notes"]["observation_count"] == 0
    assert delivered["host_notes"]["referenced_sources"] == []

    with sqlite3.connect(workspace / ".rob2-kit" / "derivative.sqlite3") as connection:
        connection.execute("DELETE FROM page_reads")
    saved = _call(
        workspace,
        "save_working_checkpoint",
        {"checkpoint": _checkpoint(evidence["source_id"])},
    )
    assert saved["outcome"] == "success", saved

    noted_without_delivery = _call(workspace, "get_status", {})["data"]["investigation"]
    assert noted_without_delivery["coverage"]["state"] == "unobserved"
    assert noted_without_delivery["coverage"]["delivered_sources"] == []
    assert noted_without_delivery["coverage"]["sources_without_delivery"] == [evidence["source_id"]]
    assert noted_without_delivery["host_notes"]["referenced_sources"] == [evidence["source_id"]]


def test_premise_support_is_explicitly_a_host_assertion(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    checkpoint = _checkpoint(evidence["source_id"])
    checkpoint["premise_records"] = [
        {
            "proposition": "The allocation sequence was unpredictable.",
            "status": "support",
            "observations": checkpoint["observations"],
            "inference": "This observation tentatively supports unpredictability.",
            "domain_id": "domain:randomization",
            "question_id": "sq:randomization:sequence",
        }
    ]
    _call(workspace, "save_working_checkpoint", {"checkpoint": checkpoint})
    _review(workspace)

    investigation = _call(workspace, "get_status", {})["data"]["investigation"]
    assert investigation["status"] == "supported"
    assert investigation["sufficiency"] == {
        "status": "supported",
        "attribution": "host_asserted",
    }
    assert investigation["support"]
    assert "verified" not in investigation["sufficiency"]["attribution"]


def test_editing_advisory_notes_preserves_a_valid_domain_context_cursor(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    _review(workspace)
    _read_required_main_reports(workspace)
    checkpoint = _checkpoint(evidence["source_id"])
    checkpoint["premise_records"] = [
        {
            "proposition": "The allocation sequence was unpredictable.",
            "status": "unresolved",
            "observations": checkpoint["observations"],
            "unresolved_component": "The sequence generation method is not established.",
            "domain_id": "domain:randomization",
            "question_id": "sq:randomization:sequence",
        }
    ]
    assert (
        _call(workspace, "save_working_checkpoint", {"checkpoint": checkpoint})["outcome"]
        == "success"
    )

    first = _call(
        workspace,
        "get_domain_context",
        {
            "trial_id": "trial",
            "domain_id": "domain:randomization",
            "max_response_bytes": 16_384,
        },
    )
    assert first["outcome"] == "success", first
    cursor = first["data"]["context_page"]["next_cursor"]
    assert cursor

    edited = _checkpoint(evidence["source_id"], "A clearer observation from the same passage.")
    edited["premise_records"] = checkpoint["premise_records"]
    assert (
        _call(workspace, "save_working_checkpoint", {"checkpoint": edited})["outcome"] == "success"
    )

    continued = _call(workspace, "get_domain_context", {"cursor": cursor})

    assert continued["outcome"] == "success", continued
    assert continued["data"]["context_page"]["index"] == 1
    assert (
        continued["data"]["context_page"]["snapshot_digest"]
        == first["data"]["context_page"]["snapshot_digest"]
    )


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


@pytest.mark.parametrize("status", ["support", "contradiction"])
def test_premise_record_keeps_host_inference_separate_from_source_facts(status: str) -> None:
    record = WorkingPremiseRecord.model_validate(
        {
            "proposition": "Outcome ascertainment continued after treatment stopped.",
            "status": status,
            "observations": [
                {
                    "text": "The report says participants were followed for survival.",
                    "sources": [
                        {
                            "source_id": "sh_0123456789abcdef",
                            "page": 2,
                            "start_line": 3,
                            "end_line": 4,
                        }
                    ],
                }
            ],
            "inference": "This tentatively supports continued ascertainment.",
            "counterevidence": [
                {
                    "text": "The disposition of some participants remains unclear.",
                    "sources": [
                        {
                            "source_id": "sh_fedcba9876543210",
                            "page": 3,
                            "start_line": 1,
                            "end_line": 1,
                        }
                    ],
                }
            ],
            "next_action": "Read the participant-flow section.",
        }
    )

    assert record.status == status
    assert record.inference is not None
    assert not hasattr(record.inference, "sources")
    assert record.observations[0].sources[0].page == 2
    assert record.counterevidence[0].sources[0].page == 3


def test_unresolved_premise_requires_a_component() -> None:
    with pytest.raises(ValidationError, match="unresolved_component"):
        WorkingPremiseRecord.model_validate(
            {
                "proposition": "The missingness mechanism is outcome-dependent.",
                "status": "unresolved",
            }
        )


def test_premise_record_is_saved_and_resumed_as_working_state(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    source_id = evidence["source_id"]
    checkpoint = _checkpoint(source_id)
    checkpoint["premise_records"] = [
        {
            "proposition": "Allocation remained concealed until assignment.",
            "status": "unresolved",
            "observations": [
                {
                    "text": "The report does not describe the allocation process.",
                    "sources": [
                        {"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}
                    ],
                }
            ],
            "inference": "Silence does not establish inadequate concealment.",
            "counterevidence": [],
            "unresolved_component": "The sequence and concealment procedure are not reported.",
            "next_action": "Read the protocol section on allocation.",
        }
    ]

    saved = _call(workspace, "save_working_checkpoint", {"checkpoint": checkpoint})
    assert saved["outcome"] == "success", saved
    status = _call(workspace, "get_status", {})["data"]["working_checkpoint"]
    premise = status["checkpoint"]["premise_records"][0]
    assert premise["proposition"] == checkpoint["premise_records"][0]["proposition"]
    assert premise["inference"] == checkpoint["premise_records"][0]["inference"]
    assert (
        premise["unresolved_component"] == checkpoint["premise_records"][0]["unresolved_component"]
    )
    assert premise["observations"][0]["sources"][0]["source_id"] == source_id


def test_investigation_projection_tracks_domain_dependency_and_unread_coverage(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    source_id = evidence["source_id"]
    checkpoint = _checkpoint(source_id)
    checkpoint["premise_records"] = [
        {
            "proposition": "Allocation remained concealed until assignment.",
            "status": "bounded",
            "observations": [
                {
                    "text": "The report does not describe the allocation process.",
                    "sources": [
                        {"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}
                    ],
                }
            ],
            "unresolved_component": "The sequence and concealment procedure are not reported.",
            "stopping_rationale": "The captured report does not resolve this premise.",
            "domain_id": "domain:randomization",
            "question_id": "sq:randomization:concealment",
        },
        {
            "proposition": "The sequence was generated without foreknowledge.",
            "status": "support",
            "observations": [
                {
                    "text": "A separate observation was recorded for sequence generation.",
                    "sources": [
                        {"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}
                    ],
                }
            ],
            "inference": "The reported sequence method supports unpredictability.",
            "domain_id": "domain:randomization",
            "question_id": "sq:randomization:sequence",
        },
    ]
    saved = _call(workspace, "save_working_checkpoint", {"checkpoint": checkpoint})
    assert saved["outcome"] == "success", saved

    _review(workspace)
    status = _call(workspace, "get_status", {})
    investigation = status["data"]["investigation"]
    assert investigation["status"] == "bounded"
    assert [item["question_id"] for item in investigation["premises"]] == [
        "sq:randomization:concealment",
        "sq:randomization:sequence",
    ]
    assert (
        investigation["stopping_rationale"]
        == checkpoint["premise_records"][0]["stopping_rationale"]
    )
    assert investigation["coverage"]["sources_without_delivery"] == []
    assert investigation["coverage"]["state"] == "delivered"
    assert investigation["host_notes"]["unread_ranges"][0]["source_id"] == source_id
    assert all(
        choice["operation"] != "save_domain_judgment"
        for choice in investigation["recovery_choices"]
    )

    context = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:randomization"},
    )
    context_choices = {
        choice["operation"] for choice in context["data"]["investigation"]["recovery_choices"]
    }
    assert "validate_domain_assessment" in context_choices
    assert "save_domain_judgment" not in context_choices
    revision = int(context["head"]["state_revision"])
    saved_domain = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", "domain:randomization", revision, evidence),
    )
    assert saved_domain["outcome"] == "success", saved_domain

    unrelated = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:deviations"},
    )["data"]["investigation"]
    assert unrelated["stale"] == []
    assert unrelated["coverage"]["sources_without_delivery"] == []
    assert unrelated["coverage"]["state"] == "delivered"

    related = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:randomization"},
    )["data"]["investigation"]
    assert related["status"] == "unresolved"
    assert related["sufficiency"] == {
        "status": "unresolved",
        "attribution": "not_established",
    }
    assert related["stopping_rationale"] is None
    assert related["coverage"]["sources_without_delivery"] == []
    assert related["coverage"]["state"] == "delivered"
    assert {item["material"] for item in related["stale"]} == {
        "interpretations",
        "premise_inference",
        "drafts",
        "stopping_rationale",
    }


def test_public_domain_context_foregrounds_active_unresolved_premise(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    source_id = evidence["source_id"]
    checkpoint = _checkpoint(source_id)
    checkpoint["premise_records"] = [
        {
            "proposition": "Baseline groups were balanced.",
            "status": "support",
            "observations": [
                {
                    "text": "The baseline table reports comparable groups.",
                    "sources": [
                        {"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}
                    ],
                }
            ],
            "inference": "The reported values suggest similar baseline characteristics.",
            "domain_id": "domain:randomization",
            "question_id": "sq:randomization:baseline-imbalance",
        },
        {
            "proposition": "The allocation process remained concealed.",
            "status": "unresolved",
            "observations": [
                {
                    "text": "The accessible report does not describe allocation concealment.",
                    "sources": [
                        {"source_id": source_id, "page": 1, "start_line": 1, "end_line": 1}
                    ],
                }
            ],
            "unresolved_component": "The concealment process is not described.",
            "domain_id": "domain:randomization",
            "question_id": "sq:randomization:concealment",
        },
    ]
    saved = _call(workspace, "save_working_checkpoint", {"checkpoint": checkpoint})
    assert saved["outcome"] == "success", saved
    _review(workspace)

    context = _call(
        workspace,
        "get_domain_context",
        {"trial_id": "trial", "domain_id": "domain:randomization"},
    )

    investigation = context["data"]["investigation"]
    assert investigation["proposition"] == "The allocation process remained concealed."
    assert investigation["status"] == "unresolved"
    assert {item["question_id"] for item in investigation["premises"]} == {
        "sq:randomization:baseline-imbalance",
        "sq:randomization:concealment",
    }


def test_trial_review_retains_source_observations_after_domain_commits(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _proposal_waiting_for_review(workspace)
    checkpoint = _checkpoint(evidence["source_id"])
    checkpoint["premise_records"] = [
        {
            "proposition": "Allocation remained concealed until assignment.",
            "status": "bounded",
            "observations": checkpoint["observations"],
            "unresolved_component": "The concealment procedure is not reported.",
            "stopping_rationale": "The captured report leaves the procedure unresolved.",
            "domain_id": "domain:randomization",
            "question_id": "sq:randomization:concealment",
            "next_action": "Read the remaining accessible protocol section.",
        }
    ]
    saved = _call(workspace, "save_working_checkpoint", {"checkpoint": checkpoint})
    assert saved["outcome"] == "success", saved

    _review(workspace)
    revision = int(
        _call(
            workspace,
            "get_domain_context",
            {"trial_id": "trial", "domain_id": SCIENTIFIC_PACK.domains[0].id},
        )["head"]["state_revision"]
    )
    for domain in SCIENTIFIC_PACK.domains:
        saved_domain = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved_domain["outcome"] == "success", saved_domain
        revision = int(saved_domain["head"]["state_revision"])

    review = _call(
        workspace,
        "review_trial",
        {"trial_id": "trial", "expected_revision": revision},
    )
    assert review["outcome"] == "success", review
    randomization = next(
        item
        for item in review["data"]["domain_findings"]
        if item["domain_id"] == "domain:randomization"
    )
    assert randomization["premise_records"][0]["observations"]
    concealment = next(
        item
        for item in randomization["answers"]
        if item["question_id"] == "sq:randomization:concealment"
    )
    assert concealment["uninvestigated_routes"]

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _finalize_assessment,
    _prepared_evidence,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _review,
    _standalone_verify,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import AssessableResultDraft, ResultApplicability


def test_omitted_result_clarity_defaults_to_unknown_and_cannot_claim_exact(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result.pop("clarity")

    repair = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))

    assert repair["outcome"] == "repair", repair
    assert all(item["code"] == "exact_result_scope_not_established" for item in repair["repairs"])
    assert all("clarity" in item["path"] for item in repair["repairs"])

    result["relation"] = "related"
    result["relation_rationale"] = "The candidate is related, but scope remains uncertain."
    accepted = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert accepted["outcome"] == "review_required", accepted
    stored = _state(workspace)["proposal"]["payload"]["results"][0]["clarity"]
    assert set(stored.values()) == {"unclear"}


def test_corrected_approved_result_requires_renewed_review_and_fresh_domains(
    tmp_path: Path,
) -> None:
    workspace, evidence, revision = _assessment_workspace(
        tmp_path,
        initial_effect=("0.61", "95% CI, 0.47 to 0.80"),
    )
    for domain in SCIENTIFIC_PACK.domains:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])

    approved_state = _state(workspace)
    prior_proposal = approved_state["proposal"]
    prior_review = approved_state["proposal_review"]
    prior_acknowledgment = approved_state["proposal_acknowledgment"]
    prior_snapshot = approved_state["snapshots"]["trial"]
    prior_checkpoints = tuple(
        approved_state["domain_records"][f"trial:{domain.id}"]["identity"]
        for domain in SCIENTIFIC_PACK.domains
    )
    revised = _result(evidence)
    revised["target"]["time_point_or_window"]["description"] = (
        "follow-up through 30 June data cutoff"
    )
    revised["target"]["intended_effect_measure"] = "hazard ratio"
    revised["reported"] = {
        "form": "comparative_effect",
        "effect_measure": "hazard ratio",
        "estimate": "0.58",
        "precision": "95% CI, 0.40 to 0.75",
        "analysis_population": "randomized population",
        "endpoint": revised["reported"]["endpoint"],
    }
    revised["relation"] = "related"
    revised["relation_rationale"] = (
        "The corrected report conflicts on the data cutoff and reported estimate, so its result "
        "remains related."
    )
    revised["clarity"]["time_point"] = "conflicting"
    revised["clarity"]["source_table_meaning"] = "conflicting"

    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [revised]))

    assert saved["outcome"] == "review_required", saved
    pending = _state(workspace)
    assert pending["phase"] == "proposal"
    assert pending["trial_dispositions"]["trial"] == "pending"
    assert pending["proposal"]["payload"]["results"][0]["clarity"]["time_point"] == ("conflicting")
    assert (
        pending["proposal"]["payload"]["results"][0]["clarity"]["source_table_meaning"]
        == "conflicting"
    )
    assert pending["proposal"]["payload"]["results"][0]["reported"]["estimate"] == "0.58"
    assert (
        pending["proposal"]["payload"]["results"][0]["reported"]["precision"]
        == "95% CI, 0.40 to 0.75"
    )
    assert not any(key.startswith("trial:") for key in pending["domain_records"])
    assert "trial" not in pending["snapshots"]
    assert pending["proposal_revision_trial_ids"] == ["trial"]

    connection = sqlite3.connect(workspace / ".rob2-kit" / "canonical.sqlite3")
    try:
        archived = connection.execute(
            "SELECT payload FROM canonical_records WHERE identity=? AND kind='proposal'",
            (prior_proposal["identity"],),
        ).fetchone()
        prior_review_record = connection.execute(
            "SELECT payload FROM canonical_records WHERE identity=? AND kind='review'",
            (prior_review["identity"],),
        ).fetchone()
        prior_ack_record = connection.execute(
            "SELECT payload FROM canonical_records WHERE identity=? AND kind='acknowledgment'",
            (prior_acknowledgment["identity"],),
        ).fetchone()
    finally:
        connection.close()
    assert archived is not None and json.loads(archived[0]) == prior_proposal
    assert prior_review_record is not None
    assert prior_ack_record is not None
    retained_checkpoints = tuple(
        pending["domain_history"][f"trial:{domain.id}"][-1] for domain in SCIENTIFIC_PACK.domains
    )
    assert retained_checkpoints == prior_checkpoints
    assert pending["snapshot_history"]["trial"][-1] == prior_snapshot["identity"]

    _review(workspace)
    resumed = _state(workspace)
    assert resumed["phase"] == "assessment"
    assert resumed["proposal_review"]["identity"] != prior_review["identity"]
    assert (
        resumed["proposal_acknowledgment"]["review_identity"]
        == resumed["proposal_review"]["identity"]
    )
    assert resumed["domain_records"] == {}
    assert resumed["snapshots"] == {}
    assert resumed["proposal"]["payload"]["results"][0]["reported"]["estimate"] == "0.58"
    first_domain = SCIENTIFIC_PACK.domains[0]
    fresh_revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    fresh = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", first_domain.id, fresh_revision, evidence),
    )
    assert fresh["outcome"] == "success", fresh
    assert fresh["data"]["checkpoint"]["identity"] != prior_checkpoints[0]
    fresh_revision = int(fresh["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains[1:]:
        fresh = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, fresh_revision, evidence),
        )
        assert fresh["outcome"] == "success", fresh
        fresh_revision = int(fresh["head"]["state_revision"])

    finalized = _finalize_assessment(workspace, fresh_revision)
    assert finalized["outcome"] == "success", finalized
    artifact = workspace / str(finalized["data"]["artifact"]["path"])
    assert verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0


def test_result_draft_rejects_removed_status_and_missing_known_design_evidence() -> None:
    with pytest.raises(ValidationError):
        ResultApplicability.model_validate(
            {
                "design": "individual_parallel",
                "status": "supported",
                "rationale": "The captured Source describes this design or leaves it unresolved.",
                "evidence": ("eh_" + "0" * 16,),
            }
        )
    for design in ("individual_parallel", "cluster_randomized", "crossover"):
        with pytest.raises(ValidationError):
            ResultApplicability.model_validate(
                {
                    "design": design,
                    "rationale": "The captured Source describes this design.",
                    "evidence": (),
                }
            )


@pytest.mark.parametrize(
    "design",
    ("cluster_randomized", "crossover", "unclear"),
)
def test_approval_routes_unsupported_applicability_to_typed_trial_review(
    tmp_path: Path, design: str
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["applicability"] = {
        "design": design,
        "rationale": (
            "The captured Source does not establish an assessable individual parallel design."
        ),
        "evidence": [evidence["handle"]],
    }

    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert proposed["outcome"] == "review_required", proposed
    _review(workspace)

    state = _state(workspace)
    status_receipt = _call(workspace, "get_status", {})
    assert status_receipt["data"]["trial_dispositions"]["trial"] == "reviewable"
    assert status_receipt["head"]["phase"] == "assessment"
    assert status_receipt["head"]["next_action"]["operation"] == "review_trial"
    assert state["proposal"]["payload"]["results"][0]["kind"] == "assessable"
    reviewed = _call(
        workspace,
        "review_trial",
        {"trial_id": "trial", "expected_revision": status_receipt["head"]["state_revision"]},
    )
    expected = "needs_input" if design == "unclear" else "unsupported_design"
    assert reviewed["data"]["review"]["disposition"] == expected
    closed = _call(
        workspace,
        "close_trial",
        {
            "trial_id": "trial",
            "expected_revision": reviewed["head"]["state_revision"],
            "review_reference": reviewed["data"]["review"]["identity"],
        },
    )
    assert closed["data"]["closure"]["disposition"] == expected
    assert state["proposal"]["payload"]["results"][0]["kind"] == "assessable"
    assert _state(workspace)["trial_dispositions"]["trial"] == expected

    blocked = _call(workspace, "get_domain_context", {})
    assert blocked["outcome"] == "condition"


def test_result_and_applicability_evidence_survive_review_replacement_and_derivative_loss(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    trial = workspace / "input" / "trial"
    (trial / "protocol.txt").write_text(
        "The allocation used individual parallel randomization.\n",
        encoding="utf-8",
    )
    (trial / "sources.toml").write_text(
        'roles = { "main.txt" = "main_article", "protocol.txt" = "protocol" }\n',
        encoding="utf-8",
    )
    result_evidence = _prepared_evidence(workspace)
    protocol = next(
        source
        for source in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if source["label"] == "protocol.txt"
    )
    _call(
        workspace,
        "read_pages",
        {"trial_id": "trial", "source_id": protocol["id"], "pages": [1]},
    )
    design_evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": protocol["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]

    result = _result(result_evidence)
    result["applicability"]["evidence"] = [design_evidence["handle"]]
    result["passage_refs"] = [result_evidence["handle"]]
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert proposed["outcome"] == "review_required", proposed
    initial = _state(workspace)
    initial_result = initial["proposal"]["payload"]["results"][0]
    assert (
        initial_result["reported"]["analysis_population"]
        == result["reported"]["analysis_population"]
    )
    assert (
        initial["review"]["candidate"]["proposal"]["results"][0]["reported"]["analysis_population"]
        == result["reported"]["analysis_population"]
    )
    assert {item["handle"] for item in initial_result["evidence"]} == {
        result_evidence["handle"],
        design_evidence["handle"],
    }
    assert initial_result["applicability"]["evidence"] == [design_evidence["handle"]]
    assert "passage_refs" not in initial_result
    assert {item["handle"] for item in initial["proposal"]["evidence"].values()} == {
        result_evidence["handle"],
        design_evidence["handle"],
    }

    replacement = _result(result_evidence)
    replacement["applicability"]["evidence"] = [design_evidence["handle"]]
    replacement["passage_refs"] = [result_evidence["handle"]]
    replacement["target"]["time_point_or_window"]["description"] = "a corrected analysis window"
    replaced = _call(workspace, "save_proposal", _proposal_args(workspace, [replacement]))
    assert replaced["outcome"] == "review_required", replaced
    revised = _state(workspace)
    revised_result = revised["proposal"]["payload"]["results"][0]
    assert {item["handle"] for item in revised_result["evidence"]} == {
        result_evidence["handle"],
        design_evidence["handle"],
    }
    assert revised_result["applicability"]["evidence"] == [design_evidence["handle"]]
    assert revised["review"]["candidate"]["proposal"] == revised["proposal"]["payload"]
    assert revised["review"]["identity"] != initial["review"]["identity"]
    assert {item["handle"] for item in revised["proposal"]["evidence"].values()} == {
        result_evidence["handle"],
        design_evidence["handle"],
    }

    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, result_evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])

    (workspace / ".rob2-kit" / "derivative.sqlite3").unlink()
    finalized = _finalize_assessment(workspace, revision)
    assert finalized["outcome"] == "success", finalized
    artifact = workspace / str(finalized["data"]["artifact"]["path"])
    assert verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0


def test_exact_relation_requires_rationale_and_repairs_fabricated_endpoint(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "The source endpoint was measured in the analyzed population; source endpoint; "
        "death ascertainment; end of follow-up; assigned to intervention; assigned to control; "
        "randomized population; risk ratio; risk; 1; events; 2.\n",
        encoding="utf-8",
    )
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"]["endpoint"]["name"] = "source endpoint"
    result["reported"]["endpoint"]["definition"] = (
        "The source endpoint was measured in the analyzed population"
    )

    missing_rationale = dict(result)
    missing_rationale.pop("relation_rationale")
    with pytest.raises(ValidationError):
        AssessableResultDraft.model_validate(missing_rationale)

    result["reported"]["endpoint"]["name"] = "fabricated source endpoint"
    result["relation_rationale"] = "The source establishes the reported endpoint correspondence."
    fabricated = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert fabricated["outcome"] == "repair"
    assert any(
        repair["code"] in {"result_value_not_supported", "incoherent_reported_result"}
        and "fabricated source endpoint" in repair["detail"]
        for repair in fabricated["repairs"]
    )


def test_unidentified_group_statistic_survives_assessment_without_inventing_a_label(
    tmp_path: Path,
) -> None:
    import runpy
    import zipfile

    from rob2_kit.application.finalization import _valid_result_shape, verify_bundle
    from rob2_kit.packs import SCIENTIFIC_PACK

    workspace = _workspace(tmp_path)
    (workspace / "input/trial/main.txt").write_text(
        "At one year the requested outcome was 5.7 points for intervention and 14 points "
        "for control; participants were individually randomized.\n",
        encoding="utf-8",
    )
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["relation"] = "narrower"
    result["relation_rationale"] = "The reported one-year values do not identify their statistic."
    result["clarity"]["source_table_meaning"] = "unclear"
    reported: dict[str, Any] = {
        "form": "group_bound_values",
        "endpoint": {"name": "requested outcome"},
        "analysis_population": "Not identified for these values.",
        "group_values": [
            {"group_id": "a", "statistic": "mean", "value": "5.7", "unit": "points"},
            {"group_id": "b", "statistic": "mean", "value": "14", "unit": "points"},
        ],
    }
    result["reported"] = reported
    invented = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert invented["outcome"] == "repair", invented
    assert any(item["code"] == "result_value_not_supported" for item in invented["repairs"])

    reported["group_values"] = [
        {key: item for key, item in value.items() if key != "statistic"}
        for value in reported["group_values"]
    ]
    # The Source still leaves scientific meaning unresolved; preserve that assertion.
    result["clarity"]["source_table_meaning"] = "unclear"
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert saved["outcome"] == "review_required", saved
    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        committed = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert committed["outcome"] == "success", committed
        revision = int(committed["head"]["state_revision"])
    finalized = _finalize_assessment(workspace, revision)
    artifact = workspace / str(finalized["data"]["artifact"]["path"])
    assert verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0

    with zipfile.ZipFile(artifact) as archive:
        canonical = json.loads(archive.read("canonical.json"))
    stored = canonical["proposal"]["payload"]["results"][0]
    assert all(value["statistic"] is None for value in stored["reported"]["group_values"])
    assert not any(
        binding["field"]["path"].endswith("/statistic") for binding in stored["bindings"]
    )
    assert (
        canonical["scientific_pack"]["result_semantics_version"]
        == "rob2-kit.result-semantics.v0.11"
    )
    standalone_shape = runpy.run_path("scripts/verify_bundle.py")["_valid_result_shape"]
    # v0.8 claimed complete statistic labels; its interpretation must stay strict.
    for validator in (_valid_result_shape, standalone_shape):
        assert not validator(stored, "requested outcome", "rob2-kit.result-semantics.v0.8")
        stored["clarity"]["source_table_meaning"] = "specified"
        assert not validator(stored, "requested outcome", "rob2-kit.result-semantics.v0.9")
        stored["clarity"]["source_table_meaning"] = "unclear"


@pytest.mark.parametrize(
    ("source", "statistic", "values", "interpretation"),
    [
        (
            "At one year, requested outcome GMR was 0.87 for intervention and 0.96 "
            "for control; individually randomized.",
            "GMR",
            ("0.87", "0.96"),
            "These are paired ratios and scientifically unitless; no unit is printed.",
        ),
        (
            "At one year, requested outcome mean was 5.7 for intervention and 14 "
            "for control; individually randomized.",
            "mean",
            ("5.7", "14"),
            "The reported unit is unreported; physical scale remains unknown.",
        ),
        (
            "At one year, requested outcome mean was 5.7 for intervention and 14 "
            "for control; units are labelled points in the table but mg in the legend; "
            "individually randomized.",
            "mean",
            ("5.7", "14"),
            "The source units conflict between points and mg; no single unit is established.",
        ),
    ],
)
def test_null_source_unit_preserves_interpretation_without_literal_binding(
    tmp_path: Path, source: str, statistic: str, values: tuple[str, str], interpretation: str
) -> None:
    import runpy

    from rob2_kit.application.finalization import _valid_result_shape

    workspace = _workspace(tmp_path)
    (workspace / "input/trial/main.txt").write_text(source + "\n")
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["relation"] = "narrower"
    result["relation_rationale"] = interpretation
    result["clarity"]["source_table_meaning"] = "unclear"
    result["reported"] = {
        "form": "group_bound_values",
        "endpoint": {"name": "requested outcome"},
        "analysis_population": "Reported group values; inclusion details unknown.",
        "group_values": [
            {"group_id": group, "statistic": statistic, "value": value, "unit": None}
            for group, value in zip(("a", "b"), values, strict=True)
        ],
    }
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert saved["outcome"] == "review_required", saved
    stored = _state(workspace)["proposal"]["payload"]["results"][0]
    assert all(value["unit"] is None for value in stored["reported"]["group_values"])
    assert stored["relation_rationale"] == interpretation
    assert not any(binding["field"]["path"].endswith("/unit") for binding in stored["bindings"])
    # Recovery and typed serialization retain null, without converting it to unitless.
    recovered = _call(workspace, "get_status", {})
    assert recovered["outcome"] == "success"
    draft = AssessableResultDraft.model_validate(result)
    assert draft.reported.form == "group_bound_values"
    assert draft.reported.group_values[0].unit is None
    standalone_shape = runpy.run_path("scripts/verify_bundle.py")["_valid_result_shape"]
    for validator in (_valid_result_shape, standalone_shape):
        assert validator(stored, "requested outcome", "rob2-kit.result-semantics.v0.10")
        assert not validator(stored, "requested outcome", "rob2-kit.result-semantics.v0.9")
        stored["clarity"]["source_table_meaning"] = "specified"
        assert not validator(stored, "requested outcome", "rob2-kit.result-semantics.v0.10")
        assert validator(stored, "requested outcome", "rob2-kit.result-semantics.v0.11")
        stored["clarity"]["source_table_meaning"] = "unclear"
    if statistic == "GMR":
        _review(workspace)
        _read_required_main_reports(workspace)
        revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
        for domain in SCIENTIFIC_PACK.domains:
            committed = _call(
                workspace,
                "save_domain_judgment",
                _domain_draft("trial", domain.id, revision, evidence),
            )
            assert committed["outcome"] == "success", committed
            revision = int(committed["head"]["state_revision"])
        finalized = _finalize_assessment(workspace, revision)
        artifact = workspace / str(finalized["data"]["artifact"]["path"])
        assert verify_bundle(artifact)
        assert _standalone_verify(artifact).returncode == 0

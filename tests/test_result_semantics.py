from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from support.rob2 import (
    _assessment_workspace,
    _call,
    _domain_draft,
    _prepared_evidence,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _review,
    _standalone_verify,
    _workspace,
)

from rob2_kit.application._state import _state
from rob2_kit.application.domains import reconcile_missing_data
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import AssessableResultDraft, ResultApplicability


def test_result_draft_accepts_each_applicability_contract() -> None:
    cases = (
        ("individual_parallel", ("eh_" + "0" * 16,)),
        ("cluster_randomized", ("eh_" + "0" * 16,)),
        ("crossover", ("eh_" + "0" * 16,)),
        ("unclear", ()),
    )

    for design, evidence in cases:
        applicability = ResultApplicability.model_validate(
            {
                "design": design,
                "rationale": "The captured Source describes this design or leaves it unresolved.",
                "evidence": evidence,
            }
        )
        draft = _result({"handle": "eh_" + "0" * 16})
        draft["applicability"] = applicability.model_dump(mode="json")

        parsed = AssessableResultDraft.model_validate(draft)

        assert parsed.applicability.design == design
        assert parsed.applicability.evidence == evidence


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
def test_approval_closes_unsupported_applicability_as_needs_input_without_unavailable_result(
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
    assert status_receipt["data"]["trial_dispositions"]["trial"] == "needs_input"
    assert status_receipt["head"]["phase"] == "ready_to_finalize"
    assert status_receipt["head"]["next_action"]["operation"] == "finalize_batch"
    assert state["proposal"]["payload"]["results"][0]["kind"] == "assessable"
    assert any(
        terminal.get("trial_id") == "trial" and terminal.get("disposition") == "needs_input"
        for terminal in state.get("terminals", {}).values()
    )

    blocked = _call(workspace, "get_domain_context", {})
    assert blocked["outcome"] == "condition"


def test_applicability_evidence_must_be_selected_from_the_same_trial(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    second = workspace / "input" / "second"
    second.mkdir(parents=True)
    (second / "main.txt").write_text(
        (workspace / "input" / "trial" / "main.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    primary = _prepared_evidence(workspace)
    source = _call(workspace, "list_sources", {"trial_id": "second"})["data"]["sources"][0]
    foreign = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "second",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    first_result = _result(primary)
    first_result["applicability"]["evidence"] = [foreign["handle"]]
    second_result = _result(foreign)
    second_result["trial_id"] = "second"

    repair = _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [first_result, second_result]),
    )

    assert repair["outcome"] == "repair", repair
    assert repair["repairs"] == [
        {
            "path": "/results/0/applicability/evidence/0",
            "code": "cross_trial_evidence",
            "detail": "applicability Evidence must resolve to this Trial",
        }
    ]


def test_approval_keeps_supported_applicability_on_the_domain_path(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    proposed = _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [_result(evidence)]),
    )
    assert proposed["outcome"] == "review_required", proposed

    _review(workspace)

    status = _call(workspace, "get_status", {})
    assert status["data"]["trial_dispositions"]["trial"] == "pending"
    assert status["head"]["phase"] == "assessment"
    assert status["head"]["next_action"]["operation"] == "get_domain_context"


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
    assert [item["handle"] for item in initial_result["evidence"]] == [result_evidence["handle"]]
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
    assert [item["handle"] for item in revised_result["evidence"]] == [result_evidence["handle"]]
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
    finalized = _call(workspace, "finalize_batch", {"expected_revision": revision})
    assert finalized["outcome"] == "success", finalized
    artifact = workspace / str(finalized["data"]["artifact"]["path"])
    assert verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0


def test_exact_relation_with_different_source_name_requires_rationale_and_keeps_binding(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "The requested outcome was reported under the source-owned label all-cause death; "
        "death ascertainment; end of follow-up; assigned to intervention; assigned to control; "
        "randomized population; risk ratio; The requested outcome was measured in the analyzed "
        "population.; risk; 1; events; 2.\n",
        encoding="utf-8",
    )
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"]["endpoint"]["name"] = "all-cause death"
    result["relation_rationale"] = (
        "The source reports all-cause death as the requested outcome for this Result."
    )

    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))

    assert proposed["outcome"] == "review_required", proposed
    canonical = _state(workspace)["proposal"]["payload"]["results"][0]
    endpoint_binding = next(
        binding
        for binding in canonical["bindings"]
        if binding["field"]["path"] == "/reported/endpoint/name"
    )
    assert canonical["relation"] == "exact"
    assert canonical["relation_rationale"] == result["relation_rationale"]
    assert canonical["reported"]["endpoint"]["name"] == "all-cause death"
    assert canonical["evidence"][endpoint_binding["evidence_index"]]["handle"] == evidence["handle"]


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


def test_domain_context_missing_data_preview_is_typed_read_only_and_scope_bounded(
    tmp_path: Path,
) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    for domain_id in ("domain:randomization", "domain:deviations"):
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain_id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])

    rows: list[dict[str, Any]] = [
        {
            "arm": "intervention",
            "population": "randomized participants",
            "unit": "participants",
            "time_point": "week 12",
            "randomized": 100,
            "observed": 95,
            "basis": [evidence["handle"]],
        },
        {
            "arm": "intervention",
            "population": "analyzed participants",
            "unit": "participants",
            "time_point": "week 12",
            "randomized": 80,
            "basis": [evidence["handle"]],
        },
        {
            "arm": "control",
            "population": "randomized participants",
            "unit": "participants",
            "time_point": "week 12",
            "randomized": 90,
            "observed": 84,
            "basis": [evidence["handle"]],
        },
    ]
    before = _state(workspace)

    context = _call(
        workspace,
        "get_domain_context",
        {
            "trial_id": "trial",
            "domain_id": "domain:missing",
            "missing_data": rows,
        },
    )

    assert context["outcome"] == "success", context
    card = next(
        card
        for card in context["data"]["comparison_cards"]
        if card["question_id"] == "sq:missing:data-available"
    )
    expected_rows = [row | {"basis": [evidence["identity"]]} for row in rows]
    assert card["missing_data"] == reconcile_missing_data(expected_rows)
    preview_by_scope = {
        tuple(item["scope"].values()): item for item in card["missing_data"]["rows"]
    }
    assert (
        preview_by_scope[("intervention", "analyzed participants", "participants", "week 12")][
            "missing"
        ]
        is None
    )
    assert len(preview_by_scope) == 3

    after = _state(workspace)
    assert after["revision"] == before["revision"]
    assert after.get("domain_records") == before.get("domain_records")

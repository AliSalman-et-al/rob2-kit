from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.workflow_models import ResultClarity

_REPO = Path(__file__).resolve().parents[1]
_AUDIT = _REPO / "docs/evaluation/2026-10-03-emperor-proposal-bef6a06"


def _request() -> dict:
    handles = [
        item["handle"] for item in json.loads((_AUDIT / "selected-evidence.json").read_text())
    ]
    return {
        "results": [
            {
                "trial_id": "emperor-reduced",
                "relation": "exact",
                "relation_rationale": "Primary first-event composite, randomized assignment, ITT "
                "population and trial follow-up match; median duration is not a fixed-time risk.",
                "clarity": {name: "specified" for name in ResultClarity.model_fields},
                "design": "individual_parallel",
                "design_rationale": "Patients individually randomized.",
                "design_evidence": [handles[0]],
                "target_measurement": "Adjudicated cardiovascular death or hospitalization "
                "for heart failure, analyzed as time to first event",
                "target_window": "Randomized trial follow-up through planned treatment end",
                "comparison_groups": [
                    {"id": "empagliflozin", "assignment": "Empagliflozin 10 mg once daily"},
                    {"id": "placebo", "assignment": "Placebo"},
                ],
                "baseline_subgroup": None,
                "intended_effect_measure": "hazard ratio",
                "reported_outcome": "cardiovascular death or hospitalization for heart failure",
                "analysis_population": "All randomized patients, ITT, with data obtained through "
                "planned treatment end; varying follow-up and losses are not complete observation.",
                "effect_measure": "hazard ratio",
                "estimate": "0.75",
                "precision": "95% confidence interval [CI], 0.65 to 0.86",
                "passage_refs": [handles[0]],
            }
        ],
        "assessments": [
            {
                "trial_id": "emperor-reduced",
                "evidence_basis": handles,
                "scope_justification": "Source primary composite is time to first event over trial "
                "follow-up; HR and interval are explicitly reported together.",
                "population_justification": "Source ITT includes all randomized patients; source "
                "reports losses and unknown vital status; ITT is not complete observation.",
                "unknowns": [],
                "counterevidence": [],
            }
        ],
        "expected_revision": 1,
    }


def _native(workspace: Path, arguments: dict, tool: str = "validate_proposal") -> dict:
    async def call() -> dict:
        previous = os.environ.get("ROB2_WORKSPACE")
        os.environ["ROB2_WORKSPACE"] = str(workspace)
        try:
            async with Client(mcp) as client:
                result = await client.call_tool(tool, arguments)
                return dict(result.structured_content or {})
        finally:
            if previous is None:
                os.environ.pop("ROB2_WORKSPACE", None)
            else:
                os.environ["ROB2_WORKSPACE"] = previous

    return asyncio.run(call())


@pytest.mark.parametrize("ordinal", range(4))
def test_actual_emperor_attempt_has_only_chosen_record_errors(tmp_path: Path, ordinal: int) -> None:
    attempts = json.loads((_AUDIT / "proposal-attempts.json").read_text())
    with pytest.raises(ToolError) as caught:
        _native(tmp_path, attempts[ordinal]["arguments"])
    feedback = json.loads(str(caught.value))
    assert feedback["code"] == "invalid_proposal_arguments"
    assert len(str(caught.value).encode()) <= 4096
    assert "missing_results" not in feedback["required_fields"]
    assert "MissingResultProposal" not in str(caught.value)
    assert "input_value" not in str(caught.value)
    assert feedback["syntax"]["comparison_groups[]"]["required"] == ["id", "assignment"]
    assert not feedback["saved"]


def test_live_declaration_has_two_separate_record_collections() -> None:
    async def schema() -> dict:
        async with Client(mcp) as client:
            return next(
                tool.input_schema
                for tool in await client.list_tools()
                if tool.name == "validate_proposal"
            )

    declaration = asyncio.run(schema())
    result = declaration["properties"]["results"]["items"]
    missing = declaration["properties"]["missing_results"]["items"]
    assert result["type"] == missing["type"] == "object"
    assert "anyOf" not in result and "anyOf" not in missing
    assert "reported_outcome" in result["properties"]
    assert "missing_facts" not in result["properties"]
    assert "missing_facts" in missing["properties"]
    assert "reported_outcome" not in missing["properties"]
    assert "kind" not in result["properties"] and "kind" not in missing["properties"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda card: card["comparison_groups"][0].update(name="invented field"),
        lambda card: card.update(passage_refs=["not-a-handle"]),
        lambda card: card.update(missing_facts=[]),
    ],
)
def test_invalid_arm_handle_or_record_type_is_specific(tmp_path: Path, mutate) -> None:
    request = _request()
    mutate(request["results"][0])
    with pytest.raises(ToolError) as caught:
        _native(tmp_path, request)
    feedback = json.loads(str(caught.value))
    assert feedback["code"] == "invalid_proposal_arguments"
    assert all(d["path"].startswith("/results/") for d in feedback["defects"])
    assert "MissingResultProposal" not in str(caught.value)


def test_arbitrarily_bad_batch_has_bounded_no_echo_feedback(tmp_path: Path) -> None:
    request = _request()
    request["results"] = [
        {"trial_id": "emperor-reduced", "private_value": "DO_NOT_ECHO" * 1000}
    ] * 100
    with pytest.raises(ToolError) as caught:
        _native(tmp_path, request)
    feedback = json.loads(str(caught.value))
    assert len(str(caught.value).encode()) <= 4096
    assert "DO_NOT_ECHO" not in str(caught.value)
    assert feedback["additional_defects"] > 100
    assert len(feedback["defects"]) <= 8


@pytest.fixture
def source_request(tmp_path: Path) -> tuple[Path, dict]:
    """Portable binding control: each retained Code source excerpt stays separate."""
    from support.rob2 import _call

    excerpts = json.loads((_AUDIT / "selected-evidence.json").read_text())
    folder = tmp_path / "input/emperor-reduced"
    folder.mkdir(parents=True)
    for n, excerpt in enumerate(excerpts):
        (folder / f"p{n}.txt").write_text(excerpt["quote"])
    (folder / "sources.toml").write_text('[roles]\n"p0.txt" = "main_article"\n')
    _call(
        tmp_path,
        "prepare_batch",
        {
            "requested_outcome": "Composite of cardiovascular death or hospitalization for "
            "worsening heart failure, time to first event",
            "expected_revision": 0,
        },
    )
    sources = _call(tmp_path, "list_sources", {"trial_id": "emperor-reduced"})["data"]["sources"]
    handles = []
    for n, excerpt in enumerate(excerpts):
        source = next(s for s in sources if s["label"] == f"p{n}.txt")
        if n == 0:
            _call(
                tmp_path,
                "read_pages",
                {"trial_id": "emperor-reduced", "source_id": source["id"], "pages": [1]},
            )
        evidence = _call(
            tmp_path,
            "select_text_evidence",
            {
                "trial_id": "emperor-reduced",
                "source_id": source["id"],
                "page": 1,
                "start_line": 1,
                "end_line": len(excerpt["quote"].splitlines()),
            },
        )["data"]["evidence"]
        handles.append(evidence["handle"])
    request = _request()
    request["results"][0]["passage_refs"] = handles[:1]
    request["results"][0]["design_evidence"] = handles[:1]
    request["assessments"][0]["evidence_basis"] = handles
    request["expected_revision"] = _call(tmp_path, "get_status", {})["head"]["state_revision"]
    return tmp_path, request


def test_minimal_source_bound_hr_ci_preserves_internal_result_identity(source_request) -> None:
    import shutil

    from rob2_kit.application._state import _identity, _state
    from rob2_kit.application.proposal import _canonical_result, _evidence_catalog
    from rob2_kit.application.proposal import validate_proposal as validate_internal
    from rob2_kit.workflow_models import NarrativeEvidenceDraft, ResultProposal

    workspace, request = source_request
    current = ResultProposal.model_validate(request["results"][0]).to_draft()
    legacy = current.model_copy(
        update={
            "passage_refs": (),
            "evidence": (NarrativeEvidenceDraft(kind="narrative", handle=current.passage_refs[0]),),
        }
    )
    outcome = _state(workspace)["batch"]["trials"][0]["requested_outcome"]
    catalog = _evidence_catalog(workspace)
    new, defects = _canonical_result(current, 0, catalog, "/results/0", outcome)
    old, old_defects = _canonical_result(legacy, 0, catalog, "/results/0", outcome)
    assert not defects and not old_defects
    assert _identity(new) == _identity(old)
    legacy_workspace = workspace.parent / (workspace.name + "-legacy")
    shutil.copytree(workspace, legacy_workspace)
    legacy_validation = validate_internal(
        legacy_workspace,
        {
            "results": [legacy.model_dump(mode="json")],
            "assessments": request["assessments"],
            "expected_revision": request["expected_revision"],
        },
    )
    assert legacy_validation["outcome"] == "success", legacy_validation
    legacy_saved = _native(
        legacy_workspace,
        {
            "expected_revision": _state(legacy_workspace)["revision"],
        },
        "save_proposal",
    )
    assert legacy_saved["outcome"] == "review_required"
    validated = _native(workspace, request)
    assert validated["outcome"] == "success", validated
    saved = _native(
        workspace, {"expected_revision": validated["head"]["state_revision"]}, "save_proposal"
    )
    assert saved["outcome"] == "review_required", saved
    canonical = _state(workspace)["proposal"]["payload"]["results"][0]
    assert canonical["kind"] == "assessable" and canonical["reported"]["estimate"] == "0.75"
    assert canonical["reported"]["precision"] == request["results"][0]["precision"]
    legacy_canonical = _state(legacy_workspace)["proposal"]["payload"]["results"][0]
    assert _identity(canonical) == _identity(legacy_canonical)
    assert {"/reported/estimate", "/reported/effect_measure", "/reported/precision"} <= {
        binding["field"]["path"] for binding in canonical["bindings"]
    }


def test_conflicting_exact_scope_stays_unresolved_and_related_keeps_target(source_request) -> None:
    workspace, request = source_request
    target = request["results"][0]["target_window"]
    request["results"][0]["clarity"]["time_point"] = "conflicting"
    rejected = _native(workspace, request)
    assert rejected["outcome"] == "repair"
    assert any(r["code"] == "exact_result_scope_not_established" for r in rejected["repairs"])
    request["results"][0]["relation"] = "related"
    accepted = _native(workspace, request)
    assert accepted["outcome"] == "success", accepted
    assert accepted["data"]["scope_review"][0]["target"]["window"] == target


def test_well_shaped_unknown_handle_cannot_be_bound(source_request) -> None:
    workspace, request = source_request
    request["results"][0]["passage_refs"] = ["eh_0000000000000000"]
    rejected = _native(workspace, request)
    assert rejected["outcome"] == "repair", rejected


def test_conflicting_routes_for_same_trial_do_not_persist(source_request) -> None:
    from rob2_kit.application._state import _state

    workspace, request = source_request
    request["missing_results"] = [
        {
            "trial_id": "emperor-reduced",
            "relation": "ambiguous",
            "missing_facts": [
                {
                    "fact": "A missing comparative Result",
                    "basis": {
                        "kind": "missing_reporting",
                        "evidence": request["results"][0]["passage_refs"][0],
                    },
                }
            ],
        }
    ]
    rejected = _native(workspace, request)
    assert rejected["outcome"] == "repair"
    assert any(r["code"] == "duplicate_trial_result" for r in rejected["repairs"])
    assert _state(workspace)["proposal"] is None


def test_missing_record_failure_has_only_missing_record_recovery(tmp_path: Path) -> None:
    request = {
        "results": [],
        "missing_results": [{"trial_id": "emperor-reduced", "relation": "exact"}],
        "assessments": [{"trial_id": "emperor-reduced", "unknowns": []}],
        "expected_revision": 0,
    }
    with pytest.raises(ToolError) as caught:
        _native(tmp_path, request)
    feedback = json.loads(str(caught.value))
    assert set(feedback["required_fields"]) == {"missing_results"}
    assert "comparison_groups[]" not in feedback["syntax"]
    assert "effect_measure" not in feedback["requirements"]
    assert all(d["path"].startswith("/missing_results/") for d in feedback["defects"])
    assert len(str(caught.value).encode()) <= 4096


@pytest.mark.parametrize("ordinal", range(2))
def test_recovery_feedback_exposes_independent_defects_in_one_reply(tmp_path: Path, ordinal: int):
    audit = _REPO / "docs/evaluation/2026-10-03-emperor-recovery-687fb24"
    attempts = json.loads((audit / "proposal-attempts.json").read_text())
    attempt = attempts[ordinal]
    before = json.loads(attempt["result"]["content"][0]["text"])
    with pytest.raises(ToolError) as caught:
        _native(tmp_path, attempt["arguments"])
    after = json.loads(str(caught.value))
    assert len(str(caught.value).encode()) <= 4096
    assert after["additional_defects"] == 0
    assert sum(d["count"] for d in after["defects"]) == (
        len(before["defects"]) + before["additional_defects"] - (2 if ordinal == 0 else 0)
    )
    paths = {d["path"] for d in after["defects"]}
    assert {"/results/0/clarity", "/results/0/evidence"} <= paths
    assert after["syntax"]["clarity"]["required"] == list(ResultClarity.model_fields)
    assert after["syntax"]["clarity"]["each_value"] == [
        "specified",
        "unclear",
        "unavailable",
        "conflicting",
    ]
    assert after["syntax"]["group_values[]"]["required"] == [
        "group_id",
        "value",
        "unit",
    ]
    assert "passage_refs" in after["syntax"]["evidence[]"]
    assert "target_time_value and target_time_unit together" in after["requirements"]
    if ordinal == 0:
        assert {"/assessments/0/unknowns", "/assessments/0/counterevidence"} <= paths
    else:
        assert {"/results/1", "/results/1/missing_facts"} <= paths
        assert next(d for d in after["defects"] if d["path"] == "/results/0/clarity")["count"] == 8
        assert "assessments[].unknowns" in after["requirements"]

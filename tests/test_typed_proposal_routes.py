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

_HANDLES = ["eh_0000000000000001", "eh_0000000000000002"]


def _archived_request(handles: list[str] = _HANDLES) -> dict:
    """The retired results/assessments request shape."""
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


def _request() -> dict:
    request = _archived_request()
    card = request["results"][0]
    assessment = request["assessments"][0]
    selection = {
        "trial_id": card.pop("trial_id"),
        "relation": card.pop("relation"),
        "scope_rationale": card.pop("relation_rationale"),
        "population_rationale": assessment["population_justification"],
        "source_passages": card.pop("passage_refs"),
        "unknowns": assessment["unknowns"],
        "counterevidence": assessment["counterevidence"],
        "candidate": card,
    }
    return {"selections": [selection], "expected_revision": request["expected_revision"]}


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


def test_archived_requests_are_rejected_without_public_compatibility(tmp_path: Path):
    with pytest.raises(ToolError) as caught:
        _native(tmp_path, _archived_request())
    feedback = json.loads(str(caught.value))
    assert feedback["code"] == "invalid_proposal_arguments"
    assert not feedback["saved"]
    assert len(str(caught.value).encode()) <= 4096
    assert any(d["path"] == "/selections" for d in feedback["defects"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["candidate"]["comparison_groups"][0].update(name="invented"),
        lambda s: s.update(source_passages=["not-a-handle"]),
        lambda s: s.update(missing_facts=[{"fact": "invented"}]),
    ],
)
def test_invalid_selection_cannot_guess_missing_science(tmp_path: Path, mutate):
    request = _request()
    mutate(request["selections"][0])
    with pytest.raises(ToolError) as caught:
        _native(tmp_path, request)
    assert len(str(caught.value).encode()) <= 4096
    assert "input_value" not in str(caught.value)


def test_arbitrary_invalid_batch_is_bounded_without_echo(tmp_path: Path):
    request = {
        "selections": [{"private_value": "DO_NOT_ECHO" * 1000}] * 100,
        "expected_revision": 0,
    }
    with pytest.raises(ToolError) as caught:
        _native(tmp_path, request)
    assert len(str(caught.value).encode()) <= 4096
    assert "DO_NOT_ECHO" not in str(caught.value)
    assert json.loads(str(caught.value))["additional_defects"] > 100


@pytest.fixture
def source_request(tmp_path: Path) -> tuple[Path, dict]:
    """Portable binding control: each source excerpt stays separate."""
    from support.rob2 import _call

    excerpts = [
        {
            "quote": "Patients were randomly assigned to empagliflozin or placebo.\n"
            "The primary outcome was cardiovascular death or heart-failure hospitalization."
        },
        {"quote": "Hazard ratio 0.75 (95% CI 0.65 to 0.86)."},
    ]
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
    request["selections"][0]["source_passages"] = handles[:1]
    request["selections"][0]["candidate"]["design_evidence"] = handles[:1]
    request["expected_revision"] = _call(tmp_path, "get_status", {})["head"]["state_revision"]
    return tmp_path, request


def test_well_shaped_unknown_handle_cannot_be_bound(source_request) -> None:
    workspace, request = source_request
    request["selections"][0]["source_passages"] = ["eh_0000000000000000"]
    rejected = _native(workspace, request)
    assert rejected["outcome"] == "repair", rejected


def test_conflicting_routes_for_same_trial_do_not_persist(source_request) -> None:
    from rob2_kit.application._state import _state

    workspace, request = source_request
    request["selections"].append(
        {
            **request["selections"][0],
            "candidate": None,
            "relation": "ambiguous",
            "missing_facts": [
                {
                    "fact": "Missing comparator",
                    "basis": {
                        "kind": "missing_reporting",
                        "evidence": request["selections"][0]["source_passages"][0],
                    },
                }
            ],
        }
    )
    rejected = _native(workspace, request)
    assert rejected["outcome"] == "repair"
    assert any(r["code"] == "duplicate_trial_result" for r in rejected["repairs"])
    assert _state(workspace)["proposal"] is None

from __future__ import annotations

import copy
import hashlib
import runpy
from pathlib import Path
from typing import Any, cast

import pytest
from support.proposal import _state_proposal
from support.rob2 import (
    _call,
    _domain_draft,
    _finalize_assessment,
    _prepared_evidence,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _review,
    _standalone_verify,
    _unavailable_result,
    _workspace,
)

from rob2_kit.application import finalization, proposal
from rob2_kit.application._state import _identity, _source_id, _state
from rob2_kit.application.proposal import _bind_result
from rob2_kit.packs import SCIENTIFIC_PACK


def test_reported_result_rejects_cross_evidence_endpoint_numeric_splice(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "death ascertainment; end of follow-up; assigned to intervention; assigned to control; "
        "randomized population; risk ratio\n"
        "The requested outcome was not reported; only an alternate endpoint was measured.\n"
        "risk; 1; events; 2.",
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    _read_required_main_reports(workspace)
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "main.txt"
    )
    first_evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    endpoint_evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 2,
            "end_line": 2,
        },
    )["data"]["evidence"]
    third_evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 3,
            "end_line": 3,
        },
    )["data"]["evidence"]
    result = _result(endpoint_evidence)
    result["reported"]["endpoint"]["definition"] = endpoint_evidence["quote"]
    result["passage_refs"] = [
        first_evidence["handle"],
        endpoint_evidence["handle"],
        third_evidence["handle"],
    ]
    repair = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert repair["outcome"] == "repair"
    assert [item["code"] for item in repair["repairs"]].count("incoherent_reported_result") == 1
    coherence = next(
        item for item in repair["repairs"] if item["code"] == "incoherent_reported_result"
    )
    assert coherence["path"] == "/results/0/reported"
    assert "Do not resubmit the same cross-passage combination" in coherence["detail"]
    assert "endpoint identifier exactly as it appears" in coherence["detail"]


def test_revised_result_binds_reported_leaves_to_its_coherent_evidence_and_finalizes(
    tmp_path: Path,
) -> None:
    """A pending replacement must not inherit generic bindings from its rejected predecessor."""

    workspace = _workspace(tmp_path)
    candidate_a_text = (
        "The requested outcome was not reported; only an alternate endpoint was measured. "
        "death ascertainment; end of follow-up; assigned to intervention; assigned to control; "
        "randomized population; risk ratio; The requested outcome was measured in the "
        "analyzed population.; risk; 1; events; 2."
    )
    (workspace / "input" / "trial" / "main.txt").write_bytes((candidate_a_text + "\n").encode())

    def evidence_identity(relative: str, quote: str) -> str:
        digest = "sha256:" + hashlib.sha256((quote + "\n").encode()).hexdigest()
        source_id = _source_id("trial", relative, digest)
        return _identity(
            {
                "kind": "narrative",
                "trial_id": "trial",
                "source_id": source_id,
                "page": 1,
                "start": 0,
                "end": len(quote),
                "quote": quote,
                "start_line": 1,
                "end_line": 1,
            }
        )

    candidate_a_identity = evidence_identity("main.txt", candidate_a_text)
    candidate_b_text = next(
        text
        for suffix in range(64)
        for text in [
            (
                "death ascertainment; end of follow-up; assigned to intervention; "
                "assigned to control; randomized population; risk ratio; The requested "
                "outcome was measured in the analyzed population with radiographic "
                f"confirmation; risk; 1; events; 2. corrected candidate {suffix}."
            )
        ]
        if candidate_a_identity < evidence_identity("revised.txt", text)
    )
    (workspace / "input" / "trial" / "revised.txt").write_bytes((candidate_b_text + "\n").encode())

    candidate_a_evidence = _prepared_evidence(workspace)
    sources = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    revised_source = next(source for source in sources if source["label"] == "revised.txt")
    candidate_b_evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": revised_source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    assert candidate_a_evidence["identity"] < candidate_b_evidence["identity"]

    rejected_candidate = _call(
        workspace, "save_proposal", _proposal_args(workspace, [_result(candidate_a_evidence)])
    )
    assert rejected_candidate["outcome"] == "review_required"

    corrected_candidate = _result(candidate_b_evidence)
    corrected_candidate["reported"]["endpoint"]["definition"] = (
        "The requested outcome was measured in the analyzed population with radiographic "
        "confirmation"
    )
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [corrected_candidate]))
    assert saved["outcome"] == "review_required", saved

    stored = _state_proposal(workspace)["results"][0]
    reported_handles = {
        stored["evidence"][binding["evidence_index"]]["handle"]
        for binding in stored["bindings"]
        if binding["field"]["path"].startswith("/reported/")
    }
    assert reported_handles == {candidate_b_evidence["handle"]}

    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        receipt = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, candidate_b_evidence),
        )
        assert receipt["outcome"] == "success", receipt
        revision = int(receipt["head"]["state_revision"])
    finalized = _finalize_assessment(workspace, revision)
    assert finalized["outcome"] == "success", finalized


def test_comparative_anchor_allows_precision_in_a_separate_evidence_item() -> None:
    result = {
        "trial_id": "trial",
        "reported": {
            "form": "comparative_effect",
            "effect_measure": "risk ratio",
            "estimate": "1",
            "precision": "95% CI 0.5 to 2",
            "analysis_population": "analyzed population",
            "endpoint": {"name": "requested outcome", "definition": "event risk"},
            "group_values": [
                {"group_id": "a", "statistic": "risk", "value": "1", "unit": "events"},
                {"group_id": "b", "statistic": "risk", "value": "2", "unit": "events"},
            ],
        },
        "evidence": [
            {"kind": "narrative", "handle": "anchor"},
            {"kind": "narrative", "handle": "precision"},
        ],
    }
    catalog = {
        "anchor": {
            "handle": "anchor",
            "kind": "narrative",
            "trial_id": "trial",
            "quote": "requested outcome event risk risk ratio 1 risk 1 events risk 2 events",
        },
        "precision": {
            "handle": "precision",
            "kind": "narrative",
            "trial_id": "trial",
            "quote": "95% CI 0.5 to 2",
        },
    }
    typed_result = cast(dict[str, object], result)
    typed_evidence = cast(list[dict[str, object]], result["evidence"])
    typed_catalog = cast(dict[str, dict[str, object]], catalog)
    assert proposal._reported_result_has_coherent_anchor(typed_result, typed_catalog)
    assert finalization._reported_result_has_coherent_anchor(
        typed_result, typed_evidence, typed_catalog
    )
    standalone = runpy.run_path("scripts/verify_bundle.py")
    assert standalone["_reported_result_has_coherent_anchor"](
        typed_result, typed_evidence, typed_catalog
    )


def test_comparative_anchor_accepts_derived_estimate_when_group_tuple_is_source_bound() -> None:
    result = {
        "trial_id": "trial",
        "reported": {
            "form": "comparative_effect",
            "effect_measure": "risk ratio",
            "estimate": "3",
            "precision": None,
            "analysis_population": "analyzed population",
            "endpoint": {"name": "requested outcome", "definition": "event risk"},
            "group_values": [
                {"group_id": "a", "statistic": "risk", "value": "1", "unit": "events"},
                {"group_id": "b", "statistic": "risk", "value": "2", "unit": "events"},
            ],
        },
        "evidence": [
            {"kind": "narrative", "handle": "anchor"},
            {
                "kind": "derived",
                "operation": "sum",
                "inputs": [
                    {"handle": "anchor", "value": "1"},
                    {"handle": "anchor", "value": "2"},
                ],
                "value": "3",
            },
        ],
    }
    catalog = {
        "anchor": {
            "handle": "anchor",
            "kind": "narrative",
            "trial_id": "trial",
            "quote": "requested outcome event risk risk ratio risk 1 events risk 2 events",
        }
    }
    typed_result = cast(dict[str, object], result)
    typed_evidence = cast(list[dict[str, object]], result["evidence"])
    typed_catalog = cast(dict[str, dict[str, object]], catalog)
    assert proposal._reported_result_has_coherent_anchor(typed_result, typed_catalog)
    assert finalization._reported_result_has_coherent_anchor(
        typed_result, typed_evidence, typed_catalog
    )
    standalone = runpy.run_path("scripts/verify_bundle.py")
    assert standalone["_reported_result_has_coherent_anchor"](
        typed_result, typed_evidence, typed_catalog
    )


def test_numeric_result_anchor_rejects_substrings_in_both_verifiers() -> None:
    result = {
        "trial_id": "trial",
        "reported": {
            "form": "group_bound_values",
            "analysis_population": "analyzed population",
            "endpoint": {"name": "requested outcome", "definition": None},
            "group_values": [
                {"group_id": "a", "statistic": "events", "value": "4", "unit": "events"},
                {"group_id": "b", "statistic": "events", "value": "5", "unit": "events"},
            ],
        },
        "evidence": [{"kind": "narrative", "handle": "anchor"}],
    }
    catalog = {
        "anchor": {
            "handle": "anchor",
            "kind": "narrative",
            "trial_id": "trial",
            "quote": "requested outcome events 34 events 56",
        }
    }
    typed_result = cast(dict[str, object], result)
    typed_evidence = cast(list[dict[str, object]], result["evidence"])
    typed_catalog = cast(dict[str, dict[str, object]], catalog)
    assert not proposal._reported_result_has_coherent_anchor(typed_result, typed_catalog)
    assert not finalization._reported_result_has_coherent_anchor(
        typed_result, typed_evidence, typed_catalog
    )
    standalone = runpy.run_path("scripts/verify_bundle.py")
    assert not standalone["_reported_result_has_coherent_anchor"](
        typed_result, typed_evidence, typed_catalog
    )

    result["reported"]["group_values"][0]["value"] = "34"
    result["reported"]["group_values"][1]["value"] = "56"
    assert proposal._reported_result_has_coherent_anchor(typed_result, typed_catalog)
    assert finalization._reported_result_has_coherent_anchor(
        typed_result, typed_evidence, typed_catalog
    )
    assert standalone["_reported_result_has_coherent_anchor"](
        typed_result, typed_evidence, typed_catalog
    )


@pytest.mark.parametrize("evidence_kind", ["table", "figure"])
def test_replay_binding_accepts_repeated_values_in_table_and_figure(
    tmp_path: Path, evidence_kind: str
) -> None:
    """Replay binds leaves to one immutable item, not a unique text occurrence."""
    workspace = _workspace(tmp_path)
    selected = _prepared_evidence(workspace)
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(selected)]))
    assert saved["outcome"] == "review_required"
    state = _state(workspace)
    result = copy.deepcopy(state["proposal"]["payload"]["results"][0])
    catalog = copy.deepcopy(state["proposal"]["evidence"])
    sources = {
        source["id"]: source for trial in state["batch"]["trials"] for source in trial["sources"]
    }
    material = str(selected["quote"])
    handle = result["evidence"][0]["handle"]
    selected_item = next(item for item in catalog.values() if item["handle"] == handle)
    selected_item["quote"] = material + " " + material
    result["reported"] = {
        "form": "single_group_category_profile",
        "analysis_population": "randomized population",
        "endpoint": result["reported"]["endpoint"],
        "group_id": "a",
        "denominator_basis": "randomized population",
        "category_axis_names": ["outcome"],
        "categories": [{"category_axes": ["requested outcome"], "value": "1"}],
    }
    if evidence_kind == "table":
        result["evidence"][0] = {
            "kind": "table",
            "handle": handle,
            "basis": "text",
            "title": "requested outcome",
            "scope": "requested outcome",
            "cohort": "randomized population",
            "row": "risk",
            "columns": ["events"],
            "group_or_category_axes": ["risk"],
            "cells": ["1", "2"],
            "units": ["events"],
            "denominators": ["randomized population"],
            "footnotes": [],
        }
    else:
        source = sources[selected_item["source_id"]]
        png_sha256 = "sha256:" + "0" * 64
        render_identity = _identity(
            {
                "source_id": selected_item["source_id"],
                "source_sha256": source["sha256"],
                "page": 1,
                "recipe": "test",
            }
        )
        render = {
            "identity": render_identity,
            "source_id": selected_item["source_id"],
            "page": 1,
            "png_sha256": png_sha256,
            "recipe": "test",
        }
        delivery_receipt = _identity(
            {
                "trial_id": "trial",
                "source_id": selected_item["source_id"],
                "render_identity": render_identity,
                "png_sha256": png_sha256,
                "channel": "mcp_image_content",
                "mime_type": "image/png",
            }
        )
        selected_item.update(
            {
                "kind": "figure",
                "render": render,
                "delivery_receipt": delivery_receipt,
                "region": [0.0, 0.0, 1.0, 1.0],
                "transcription": material + " " + material,
                "provenance": "text_corroborated",
            }
        )
        result["evidence"][0] = {
            "kind": "figure",
            "handle": handle,
            "render_identity": render_identity,
            "delivery_receipt": delivery_receipt,
            "region": [0.0, 0.0, 1.0, 1.0],
            "transcription": selected_item["transcription"],
            "provenance": selected_item["provenance"],
        }
    defects, _ = _bind_result(result, catalog, 0, "/results/0", [])
    assert defects == []
    requested = {"trial": "requested outcome"}
    assert finalization._verify_result_evidence(result, catalog, sources, _identity, requested)
    standalone = runpy.run_path("scripts/verify_bundle.py")
    assert standalone["_valid_result_evidence"](result, catalog, sources, requested)


def test_nonblank_result_invariants_match_both_bundle_verifiers(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    saved = _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [_unavailable_result(evidence, "missing endpoint")]),
    )
    assert saved["outcome"] == "review_required"
    state = _state(workspace)
    result = state["proposal"]["payload"]["results"][0]
    catalog = state["proposal"]["evidence"]
    sources = {
        source["id"]: source for trial in state["batch"]["trials"] for source in trial["sources"]
    }
    standalone = runpy.run_path("scripts/verify_bundle.py")
    requested = {"trial": "requested outcome"}
    assert finalization._verify_result_evidence(result, catalog, sources, _identity, requested)
    assert standalone["_valid_result_evidence"](result, catalog, sources, requested)

    for mutate in (
        lambda candidate: candidate["missing_facts"][0].update({"fact": "  "}),
        lambda candidate: candidate["missing_facts"][0]["basis"].update({"source": "\t"}),
    ):
        invalid = copy.deepcopy(result)
        mutate(invalid)
        assert not finalization._verify_result_evidence(
            invalid, catalog, sources, _identity, requested
        )
        assert not standalone["_valid_result_evidence"](invalid, catalog, sources, requested)

    assess_root = tmp_path / "assess"
    assess_root.mkdir()
    assess_workspace = _workspace(assess_root)
    assess_evidence = _prepared_evidence(assess_workspace)
    saved = _call(
        assess_workspace,
        "save_proposal",
        _proposal_args(assess_workspace, [_result(assess_evidence)]),
    )
    assert saved["outcome"] == "review_required"
    assess_result = _state(assess_workspace)["proposal"]["payload"]["results"][0]
    assert finalization._valid_result_shape(assess_result, "requested outcome")
    assert standalone["_valid_result_shape"](assess_result, "requested outcome")
    for mutate in (
        lambda candidate: candidate.update({"relation_rationale": "  "}),
        lambda candidate: candidate["target"]["measurement"].update({"method": "\t"}),
        lambda candidate: candidate["target"]["time_point_or_window"].update({"description": "  "}),
        lambda candidate: candidate["target"]["time_point_or_window"].update(
            {"kind": "quantified", "description": "follow-up", "value": " ", "unit": "months"}
        ),
        lambda candidate: candidate["target"]["comparison_groups"][0].update({"id": "  "}),
    ):
        invalid = copy.deepcopy(assess_result)
        mutate(invalid)
        assert not finalization._valid_result_shape(invalid, "requested outcome")
        assert not standalone["_valid_result_shape"](invalid, "requested outcome")


def test_component_definition_is_repaired_but_nullable_definition_finalizes(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "input" / "trial" / "main.txt").write_text(
        "composite requested outcome; death ascertainment; end of follow-up; "
        "assigned to intervention; assigned to control; randomized population; risk ratio; "
        "risk; 1; events; 2.\n"
        "Hospitalization alone was defined as an admission to hospital.",
        encoding="utf-8",
    )
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    _read_required_main_reports(workspace)
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "main.txt"
    )
    quantitative_evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    definition_evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 2,
            "end_line": 2,
        },
    )["data"]["evidence"]
    result = _result(quantitative_evidence)
    result["reported"]["endpoint"] = {
        "name": "composite requested outcome",
        "definition": "Hospitalization alone was defined as an admission to hospital.",
    }
    result["passage_refs"] = [
        quantitative_evidence["handle"],
        definition_evidence["handle"],
    ]
    result["relation"] = "related"
    result["relation_rationale"] = "The reported composite overlaps the requested outcome."
    repair = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert repair["outcome"] == "repair"
    assert any(
        item["code"] == "endpoint_definition_not_jointly_supported"
        and item["path"] == "/results/0/reported/endpoint/definition"
        and "omit endpoint.definition" in item["detail"]
        for item in repair["repairs"]
    )

    result["reported"]["endpoint"]["definition"] = None
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert saved["outcome"] == "review_required", saved
    stored = _state_proposal(workspace)["results"][0]
    assert all(
        binding["field"]["path"] != "/reported/endpoint/definition"
        for binding in stored["bindings"]
    )
    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        receipt = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, quantitative_evidence),
        )
        assert receipt["outcome"] == "success", receipt
        revision = int(receipt["head"]["state_revision"])
    finalized = _finalize_assessment(workspace, revision)
    assert finalized["outcome"] == "success", finalized
    artifact = workspace / str(finalized["data"]["artifact"]["path"])
    assert finalization.verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0


@pytest.mark.parametrize(
    ("kind", "item", "catalog_item", "root_code"),
    [
        (
            "table",
            {
                "kind": "table",
                "handle": "table-1",
                "basis": "text",
                "title": "title",
                "scope": "scope",
                "cohort": "cohort",
                "row": "row",
                "columns": ["column"],
                "group_or_category_axes": ["axis"],
                "cells": ["invented cell"],
                "units": ["unit"],
                "denominators": ["denominator"],
                "footnotes": [],
            },
            {
                "handle": "table-1",
                "kind": "narrative",
                "trial_id": "trial",
                "quote": "title scope cohort row column axis cell unit denominator",
                "transcription": "",
            },
            "table_material_mismatch",
        ),
    ],
)
def test_invalid_typed_visual_evidence_suppresses_dependent_binding_repairs(
    kind: str,
    item: dict[str, Any],
    catalog_item: dict[str, Any],
    root_code: str,
) -> None:
    result = {
        "trial_id": "trial",
        "target": {
            "unsupported": "not in selected material",
            "comparison_groups": [{"id": "group"}],
        },
        "reported": {"endpoint": {"name": "axis", "definition": "series"}},
        "evidence": [item],
    }

    repairs, _ = _bind_result(result, {"identity": catalog_item}, 0, "/results/0", [])

    assert any(repair["code"] == root_code for repair in repairs)
    assert any(repair["code"] == "result_value_not_supported" for repair in repairs)

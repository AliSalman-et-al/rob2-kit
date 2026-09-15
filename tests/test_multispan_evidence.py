from __future__ import annotations

import copy
import runpy
from pathlib import Path
from typing import Any, cast

from support.rob2 import (
    _call,
    _domain_draft,
    _finalize_assessment,
    _proposal_args,
    _read_required_main_reports,
    _result,
    _review,
    _standalone_verify,
)

from rob2_kit.application import finalization
from rob2_kit.application._state import _identity, _state
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.packs import SCIENTIFIC_PACK


def _table_workspace(tmp_path: Path) -> Path:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    # The first physical line deliberately exceeds the projection line cap.
    # The separately selected table fragments that follow must retain their
    # own exact coordinates rather than being reconstructed into one quote.
    (trial / "main.txt").write_text(
        ("padding " * 400)
        + "\n"
        + (
            "Table 2. requested outcome. The requested outcome was measured in the analyzed "
            "population. death ascertainment at end of follow-up.\n"
        )
        + (
            "Header: requested outcome; risk; events; randomized population; assigned to "
            "intervention; assigned to control; risk ratio.\n"
        )
        + "Quantitative row: requested outcome; risk; 1 events; 2 events; randomized population.\n"
        + "Unit and denominator: events; randomized population.\n"
        + "Footnote: events were recorded at end of follow-up.\n",
        encoding="utf-8",
    )
    return tmp_path


def _select_lines(workspace: Path, start_line: int, end_line: int) -> dict[str, object]:
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    response = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": start_line,
            "end_line": end_line,
        },
    )
    assert response["outcome"] == "success", response
    return response["data"]["evidence"]


def _multispan_result(
    title: dict[str, object],
    header: dict[str, object],
    row: dict[str, object],
    unit: dict[str, object],
    footnote: dict[str, object],
) -> dict[str, object]:
    result = _result(title)
    result["evidence"] = [
        {
            "kind": "table_multispan",
            "basis": "text",
            "spans": [
                {"role": "title_or_definition", "handle": title["handle"]},
                {"role": "header", "handle": header["handle"]},
                {"role": "quantitative_row", "handle": row["handle"]},
                {"role": "unit", "handle": unit["handle"]},
                {"role": "footnote", "handle": footnote["handle"]},
            ],
            "title": "requested outcome",
            "scope": "requested outcome",
            "cohort": "randomized population",
            "row": "risk",
            "columns": ["events"],
            "group_or_category_axes": ["risk"],
            "cells": ["1", "2"],
            "units": ["events"],
            "denominators": ["randomized population"],
            "footnotes": ["end of follow-up"],
        }
    ]
    return result


def test_multispan_table_evidence_keeps_separate_source_spans_through_export(
    tmp_path: Path,
) -> None:
    workspace = _table_workspace(tmp_path)
    prepared = _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    assert prepared["outcome"] == "success", prepared
    _read_required_main_reports(workspace)
    source_id = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]["id"]
    numbered_text = _call(
        workspace,
        "read_pages",
        {
            "trial_id": "trial",
            "source_id": source_id,
            "pages": [1],
        },
    )["data"]["pages"][0]["numbered_text"]
    lines = [line.split("|", 1)[1] for line in numbered_text.splitlines()]
    indexes = {
        label: next(index + 1 for index, line in enumerate(lines) if label in line)
        for label in (
            "Table 2",
            "Header:",
            "Quantitative row:",
            "Unit and denominator:",
            "Footnote:",
        )
    }
    title = _select_lines(workspace, indexes["Table 2"], indexes["Table 2"])
    header = _select_lines(workspace, indexes["Header:"], indexes["Header:"])
    row = _select_lines(workspace, indexes["Quantitative row:"], indexes["Quantitative row:"])
    unit = _select_lines(
        workspace, indexes["Unit and denominator:"], indexes["Unit and denominator:"]
    )
    footnote = _select_lines(workspace, indexes["Footnote:"], indexes["Footnote:"])

    saved = _call(
        workspace,
        "save_proposal",
        _proposal_args(
            workspace,
            [_multispan_result(title, header, row, unit, footnote)],
        ),
    )
    assert saved["outcome"] == "review_required", saved
    _review(workspace)
    _read_required_main_reports(workspace)

    context = _call(workspace, "get_domain_context", {})
    result_evidence = context["data"]["result"]["evidence"]
    multispan = next(item for item in result_evidence if item["kind"] == "table_multispan")
    assert [span["role"] for span in multispan["spans"]] == [
        "title_or_definition",
        "header",
        "quantitative_row",
        "unit",
        "footnote",
    ]
    assert [span["identity"] for span in multispan["spans"]] == [
        title["identity"],
        header["identity"],
        row["identity"],
        unit["identity"],
        footnote["identity"],
    ]
    assert (
        len({(span["source_id"], span["start"], span["end"]) for span in multispan["spans"]}) == 5
    )

    revision = int(context["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        receipt = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, title),
        )
        assert receipt["outcome"] == "success", receipt
        revision = int(receipt["head"]["state_revision"])
    finalized = _finalize_assessment(workspace, revision)
    artifact = workspace / str(finalized["data"]["artifact"]["path"])
    assert verify_bundle(artifact)
    standalone = _standalone_verify(artifact)
    assert standalone.returncode == 0, standalone.stderr


def test_multispan_table_tampering_is_rejected_by_both_verifiers(tmp_path: Path) -> None:
    workspace = _table_workspace(tmp_path)
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    _read_required_main_reports(workspace)
    title, header, row, unit, footnote = (
        _select_lines(workspace, line, line) for line in (3, 4, 5, 6, 7)
    )
    saved = _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [_multispan_result(title, header, row, unit, footnote)]),
    )
    assert saved["outcome"] == "review_required", saved
    state = _state(workspace)
    result = copy.deepcopy(state["proposal"]["payload"]["results"][0])
    catalog = copy.deepcopy(state["proposal"]["evidence"])
    source_map = {
        source["id"]: source for trial in state["batch"]["trials"] for source in trial["sources"]
    }
    result["evidence"][0]["spans"][2]["handle"] = header["handle"]
    requested = {"trial": "requested outcome"}
    assert not finalization._verify_result_evidence(
        result, catalog, source_map, _identity, requested
    )
    standalone = runpy.run_path("scripts/verify_bundle.py")
    assert not standalone["_valid_result_evidence"](result, catalog, source_map, requested)


def test_exact_source_span_identity_ignores_discovery_but_not_location(tmp_path: Path) -> None:
    workspace = _table_workspace(tmp_path)
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    _read_required_main_reports(workspace)
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "requested outcome", "mode": "any"},
    )
    first = _select_lines(workspace, 2, 2)
    _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "death ascertainment", "mode": "any"},
    )
    repeated = _select_lines(workspace, 2, 2)
    different = _select_lines(workspace, 3, 3)
    assert first["identity"] == repeated["identity"]
    assert first["handle"] == repeated["handle"]
    assert first["identity"] != different["identity"]
    assert first["source_id"] == different["source_id"] == source["id"]


def test_multispan_table_rejects_generic_total_as_an_endpoint(tmp_path: Path) -> None:
    workspace = _table_workspace(tmp_path)
    _call(
        workspace,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    _read_required_main_reports(workspace)
    title, header, row, unit, footnote = (
        _select_lines(workspace, line, line) for line in (3, 4, 5, 6, 7)
    )
    result = _multispan_result(title, header, row, unit, footnote)
    reported = cast(dict[str, Any], result["reported"])
    reported["endpoint"] = {"name": "Total", "definition": None}
    rejected = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert rejected["outcome"] == "repair"
    assert any(item["code"] == "generic_table_endpoint" for item in rejected["repairs"])

"""Black-box assessment lifecycle behavior tests."""

# Shared private helpers keep caller setup out of the scenarios.
# ruff: noqa: F405

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from fastmcp import Client
from support.rob2 import *  # noqa: F401,F403

from rob2_kit.application._state import _state
from rob2_kit.application.contracts import COUNTERS, TOOL_NAMES
from rob2_kit.application.finalization import verify_bundle
from rob2_kit.application.proposal import save_proposal as application_save_proposal
from rob2_kit.application.status import get_status
from rob2_kit.interfaces.mcp.server import mcp
from rob2_kit.packs import SCIENTIFIC_PACK
from rob2_kit.workflow_models import ProposalDraft


def test_structured_domain_uses_and_search_receipts(tmp_path: Path) -> None:
    workspace, evidence, revision = _assessment_workspace(tmp_path)
    domain_id = SCIENTIFIC_PACK.domains[0].id
    context = _call(workspace, "get_domain_context", {"trial_id": "trial", "domain_id": domain_id})
    assert context["head"]["next_action"] == {
        "operation": "save_domain_judgment",
        "authority": "host",
        "trial_id": "trial",
        "domain_id": domain_id,
        "expected_revision": revision,
        "caller_inputs": ["answers", "multiple_concerns"],
    }
    draft = _domain_draft("trial", domain_id, revision, evidence)
    saved = _call(workspace, "save_domain_judgment", draft)
    assert saved["outcome"] == "success"
    checkpoint = _state(workspace)["domain_records"][f"trial:{domain_id}"]
    assert checkpoint["answers"][0]["bases"][0]["evidence"] == evidence["identity"]
    assert _call(workspace, "save_domain_judgment", draft)["data"]["retry"] is True

    stale = _domain_draft("trial", SCIENTIFIC_PACK.domains[1].id, revision, evidence)
    assert _call(workspace, "save_domain_judgment", stale)["outcome"] == "conflict"

    receipt = _search_receipt(
        workspace,
        _call(
            workspace,
            "search_sources",
            {"trial_id": "trial", "query": "not-in-source", "mode": "any"},
        )["data"]["search_receipt"],
    )
    absence = _domain_draft(
        "trial",
        SCIENTIFIC_PACK.domains[1].id,
        saved["head"]["state_revision"],
        search_receipt=receipt["handle"],
    )
    absence["answers"][0]["bases"] = [{"kind": "absence", "search_receipt": receipt["handle"]}]
    accepted = _call(workspace, "save_domain_judgment", absence)
    assert accepted["outcome"] == "success"
    checkpoint = _state(workspace)["domain_records"][f"trial:{SCIENTIFIC_PACK.domains[1].id}"]
    assert len(checkpoint["search_accounts"]) == 1
    assert {
        key: checkpoint["search_accounts"][0][key]
        for key in (
            "identity",
            "handle",
            "trial_id",
            "query",
            "mode",
            "total_matches",
            "truncated",
            "condition",
        )
    } == {
        key: receipt[key]
        for key in (
            "identity",
            "handle",
            "trial_id",
            "query",
            "mode",
            "total_matches",
            "truncated",
            "condition",
        )
    }

    invalid = _domain_draft(
        "trial",
        SCIENTIFIC_PACK.domains[2].id,
        accepted["head"]["state_revision"],
        search_receipt=receipt["handle"],
    )
    invalid["answers"][0]["bases"] = [{"kind": "absence", "search_receipt": "sr_" + "0" * 16}]
    assert _call(workspace, "save_domain_judgment", invalid)["outcome"] == "repair"


def test_absence_based_five_domain_assessment_finalizes(tmp_path: Path) -> None:
    artifact = _absence_assessed_artifact(_workspace(tmp_path))
    assert artifact.is_file()


def test_finalization_preserves_trailing_pdf_format_characters(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "input" / "trial" / "main.txt"
    source.write_text(
        source.read_text(encoding="utf-8").rstrip("\n") + "\u00ad\n",
        encoding="utf-8",
    )
    evidence = _prepared_evidence(workspace)
    proposed = _call(workspace, "save_proposal", _proposal_args(workspace, [_result(evidence)]))
    assert proposed["outcome"] == "review_required", proposed
    _review(workspace)
    _read_required_main_reports(workspace)
    revision = int(_call(workspace, "get_domain_context", {})["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, evidence),
        )
        assert saved["outcome"] == "success", saved
        revision = int(saved["head"]["state_revision"])
    finalized = _finalize_assessment(workspace, revision)
    artifact = workspace / finalized["data"]["artifact"]["path"]
    assert verify_bundle(artifact)
    assert _standalone_verify(artifact).returncode == 0


def test_batch_domains_cannot_advance_a_later_trial(tmp_path: Path) -> None:
    source_text = (
        "The requested outcome was measured in the analyzed population. "
        "death ascertainment; end of follow-up; assigned to intervention; "
        "assigned to control; randomized population; risk ratio; risk; 1; events; 2.\n"
    )
    for label in ("trial-a", "trial-b"):
        trial = tmp_path / "input" / label
        trial.mkdir(parents=True)
        (trial / "main.txt").write_text(source_text, encoding="utf-8")

    prepared = _call(
        tmp_path,
        "prepare_batch",
        {"requested_outcome": "requested outcome", "expected_revision": 0},
    )
    assert {trial["requested_outcome"] for trial in prepared["data"]["trials"]} == {
        "requested outcome"
    }
    _read_required_main_reports(tmp_path)

    evidence_by_trial: dict[str, dict[str, Any]] = {}
    for trial_id in ("trial-a", "trial-b"):
        source = _call(tmp_path, "list_sources", {"trial_id": trial_id})["data"]["sources"][0]
        evidence_by_trial[trial_id] = _call(
            tmp_path,
            "select_text_evidence",
            {
                "trial_id": trial_id,
                "source_id": source["id"],
                "page": 1,
                "start_line": 1,
                "end_line": 1,
            },
        )["data"]["evidence"]
    proposal = _call(
        tmp_path,
        "save_proposal",
        _proposal_args(
            tmp_path,
            [
                _result_for_trial(evidence_by_trial["trial-a"], "trial-a"),
                _result_for_trial(evidence_by_trial["trial-b"], "trial-b"),
            ],
        ),
    )
    assert proposal["outcome"] == "review_required", proposal
    _review(tmp_path)
    _read_required_main_reports(tmp_path)
    context = _call(tmp_path, "get_domain_context", {})
    domain_id = SCIENTIFIC_PACK.domains[0].id
    assert context["data"]["trial_id"] == "trial-a"

    skipped = _call(
        tmp_path,
        "save_domain_judgment",
        _domain_draft(
            "trial-b",
            domain_id,
            int(context["head"]["state_revision"]),
            evidence_by_trial["trial-b"],
        ),
    )

    assert skipped["outcome"] == "repair"
    assert skipped["repairs"] == [
        {
            "path": "/trial_id",
            "code": "trial_out_of_sequence",
            "detail": "complete Trial 'trial-a' before Trial 'trial-b'",
        }
    ]

    skipped_terminal = _call(
        tmp_path,
        "request_trial_terminal",
        {
            "request": {
                "disposition": "needs_input",
                "trial_id": "trial-b",
                "reason": "Researcher clarification is required.",
                "missing_facts": ["Clarification."],
            },
            "expected_revision": int(context["head"]["state_revision"]),
        },
    )
    assert skipped_terminal["outcome"] == "condition"
    assert skipped_terminal["condition"]["detail"] == (
        "complete Trial 'trial-a' before Trial 'trial-b'"
    )

    revision = int(context["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        saved = _call(
            tmp_path,
            "save_domain_judgment",
            _domain_draft("trial-a", domain.id, revision, evidence_by_trial["trial-a"]),
        )
        assert saved["outcome"] == "success"
        revision = int(saved["head"]["state_revision"])
    assert saved["data"]["trial_completed"] is True
    assert _state(tmp_path)["trial_dispositions"]["trial-a"] == "assessed"

    first_checkpoint = _state(tmp_path)["domain_records"]["trial-a:domain:randomization"]
    closed_revision = _domain_draft(
        "trial-a",
        SCIENTIFIC_PACK.domains[0].id,
        revision,
        evidence_by_trial["trial-a"],
    )
    closed_revision["supersedes"] = first_checkpoint["identity"]
    closed_revision["revision_basis"] = {
        "kind": "self_correction",
        "rationale": "This attempted correction occurs after Trial completion.",
    }
    refused_revision = _call(tmp_path, "save_domain_judgment", closed_revision)
    assert refused_revision["outcome"] == "condition"
    assert refused_revision["condition"]["detail"] == (
        "Trial AssessmentSnapshot is final; Domain revisions are closed"
    )

    status = _call(tmp_path, "get_status", {})
    assert status["head"]["next_action"] == {
        "operation": "get_domain_context",
        "authority": "host",
        "trial_id": "trial-b",
        "domain_id": SCIENTIFIC_PACK.domains[0].id,
    }
    next_context = _call(tmp_path, "get_domain_context", {})
    assert next_context["outcome"] == "success"
    assert next_context["data"]["trial_id"] == "trial-b"
    assert next_context["data"]["domain_id"] == SCIENTIFIC_PACK.domains[0].id


def test_real_fastmcp_assessed_path_restart_derivative_rebuild_and_freeze(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    os.environ["ROB2_WORKSPACE"] = str(workspace)

    async def discover() -> list[str]:
        async with Client(mcp) as client:
            return [tool.name for tool in await client.list_tools()]

    assert asyncio.run(discover()) == list(TOOL_NAMES)
    prepared = _call(
        workspace,
        "prepare_batch",
        {
            "requested_outcome": "requested outcome",
            "expected_revision": 0,
        },
    )
    assert prepared["head"]["phase"] == "proposal"
    _read_required_main_reports(workspace)
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    source_id = str(source["id"])
    selected = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source_id,
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    proposal = _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [_result(selected)]),
    )
    assert proposal["outcome"] == "review_required"
    _review(workspace)
    _read_required_main_reports(workspace)

    context = _call(workspace, "get_domain_context", {})
    revision = int(context["head"]["state_revision"])
    for domain in SCIENTIFIC_PACK.domains:
        saved = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial", domain.id, revision, selected),
        )
        assert saved["outcome"] == "success"
        revision = int(saved["head"]["state_revision"])

    corrected = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft("trial", SCIENTIFIC_PACK.domains[0].id, revision, selected),
    )
    assert corrected["outcome"] == "success"
    revision = int(corrected["head"]["state_revision"])
    first_final = _finalize_assessment(workspace, revision)
    assert first_final["data"]["trial_dispositions"] == {"trial": "assessed"}
    assert first_final["head"]["next_action"] is None
    artifact = workspace / str(first_final["data"]["artifact"]["path"])
    assert verify_bundle(artifact)
    verified = subprocess.run(
        [sys.executable, "scripts/verify_bundle.py", str(artifact)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
    tampered = workspace / "tampered.rob2.zip"
    with zipfile.ZipFile(artifact) as original, zipfile.ZipFile(tampered, "w") as archive:
        for info in original.infolist():
            payload = b"{}" if info.filename == "canonical.json" else original.read(info)
            archive.writestr(info, payload)
    rejected = subprocess.run(
        [sys.executable, "scripts/verify_bundle.py", str(tampered)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 1
    first_bytes = artifact.read_bytes()
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        payload = b"".join(archive.read(name) for name in names)
        assert str(workspace) not in payload.decode("utf-8", errors="ignore")
        assert not any(name.endswith(".bin") for name in names)
    derivative = workspace / ".rob2-kit" / "derivative.sqlite3"
    source_rows_before_restart = _call(workspace, "list_sources", {"trial_id": "trial"})["data"][
        "sources"
    ]
    derivative.unlink()
    hits = _call(
        workspace,
        "search_sources",
        {"trial_id": "trial", "query": "requested", "mode": "any"},
    )
    assert hits["data"]["hits"]
    assert (
        _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        == source_rows_before_restart
    )
    retry = _call(
        workspace,
        "finalize_batch",
        {"expected_revision": int(_state(workspace)["revision"])},
    )
    assert retry["data"]["retry"] is True
    assert artifact.read_bytes() == first_bytes
    conflict = _call(workspace, "finalize_batch", {"expected_revision": 0})
    assert conflict["outcome"] == "success"
    assert conflict["data"]["retry"] is True
    frozen = get_status(workspace)
    assert frozen["phase"] == "finalized"
    assert COUNTERS["derivative_rebuilds"] >= 1


def test_finalized_bundle_includes_domain_only_evidence(tmp_path: Path) -> None:
    trial = tmp_path / "input" / "trial"
    trial.mkdir(parents=True)
    (trial / "domain.txt").write_text("risk ratio", encoding="utf-8")
    (trial / "unreferenced.txt").write_text(
        "only an alternate endpoint was measured", encoding="utf-8"
    )
    workspace, proposal_evidence, revision = _assessment_workspace(tmp_path)
    sources = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
    domain_source = next(item for item in sources if item["label"] == "domain.txt")
    unreferenced_source = next(item for item in sources if item["label"] == "unreferenced.txt")
    domain_evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": domain_source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    unreferenced_evidence = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": unreferenced_source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    assert domain_evidence["identity"] != proposal_evidence["identity"]
    assert unreferenced_evidence["identity"] not in {
        proposal_evidence["identity"],
        domain_evidence["identity"],
    }
    for domain in SCIENTIFIC_PACK.domains:
        draft = _domain_draft("trial", domain.id, revision, domain_evidence)
        saved = _call(workspace, "save_domain_judgment", draft)
        assert saved["outcome"] == "success"
        revision = int(saved["head"]["state_revision"])
    finalized = _finalize_assessment(workspace, revision)
    artifact = workspace / str(finalized["data"]["artifact"]["path"])
    assert verify_bundle(artifact)
    verified = _standalone_verify(artifact)
    assert verified.returncode == 0, verified.stderr or verified.stdout
    with zipfile.ZipFile(artifact) as archive:
        canonical = json.loads(archive.read("canonical.json"))
        catalog = canonical["proposal"]["evidence"]
        evidence_members = sorted(
            name for name in archive.namelist() if name.startswith("evidence/")
        )
        assert evidence_members == sorted(
            f"evidence/{identity.removeprefix('sha256:')}.json" for identity in catalog
        )
        assert unreferenced_evidence["identity"] not in catalog


def test_needs_input_and_repairs_are_authoritative(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    prepared = _call(
        workspace,
        "prepare_batch",
        {
            "requested_outcome": "requested outcome",
            "expected_revision": 0,
        },
    )
    assert prepared["head"]["phase"] == "proposal"
    _read_required_main_reports(workspace)
    source = _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"][0]
    evidence = _call(
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
    revision = int(get_status(workspace)["state_revision"])
    repair_result = _result(evidence)
    repair_result["reported"]["values"][0]["statistic"] = "unsupported statistic"
    repair = application_save_proposal(
        workspace,
        ProposalDraft.model_validate({"results": [repair_result], "expected_revision": revision}),
    )
    assert repair["outcome"] == "repair"
    assert any(item["code"] == "result_value_not_supported" for item in repair["repairs"])
    second_repair_result = _result(evidence)
    second_repair_result["reported"]["endpoint"]["name"] = "unsupported endpoint"
    table_repair = application_save_proposal(
        workspace,
        ProposalDraft.model_validate(
            {"results": [second_repair_result], "expected_revision": revision}
        ),
    )
    assert table_repair["outcome"] == "repair"
    assert any(item["code"] == "exact_relation_name_mismatch" for item in table_repair["repairs"])
    third_repair_result = _result(evidence)
    third_repair_result["reported"]["values"][0]["value"] = "unsupported value"
    truncated = application_save_proposal(
        workspace,
        ProposalDraft.model_validate(
            {"results": [third_repair_result], "expected_revision": revision}
        ),
    )
    assert truncated["outcome"] == "repair"
    assert any(item["code"] == "result_value_not_supported" for item in truncated["repairs"])
    unavailable = _call(
        workspace,
        "save_proposal",
        _proposal_args(
            workspace,
            [_unavailable_result(evidence, "Researcher must select the intended result.")],
        ),
    )
    assert unavailable["outcome"] == "review_required"
    _review(workspace)
    finalized = _finalize_assessment(
        workspace,
        int(_call(workspace, "get_status", {})["head"]["state_revision"]),
    )
    assert finalized["data"]["trial_dispositions"] == {"trial": "needs_input"}
    artifact = workspace / str(finalized["data"]["artifact"]["path"])
    assert verify_bundle(artifact)
    for index, mutate in enumerate(
        (
            lambda item: item["missing_facts"][0]["basis"].update({"source": "invented premise"}),
            lambda item: item["missing_facts"].clear(),
            lambda item: item["missing_facts"].append(dict(item["missing_facts"][0])),
            lambda item: item["missing_facts"][0].update({"fact": "invented missing fact"}),
            lambda item: item["missing_facts"][0]["basis"].update(
                {"source": "The requested outcome"}
            ),
        )
    ):
        tampered = tmp_path / f"unavailable-tamper-{index}.rob2.zip"
        _rehashed_result_tamper(artifact, tampered, mutate)
        assert not verify_bundle(tampered)
        assert _standalone_verify(tampered).returncode == 1


def test_unavailable_result_requires_researcher_review(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    ambiguous = _unavailable_result(
        evidence, "Researcher must select the intended progression-free survival result."
    )
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [ambiguous]))
    assert saved["outcome"] == "review_required", saved
    assert saved["head"]["next_action"]["operation"] == "researcher_review"
    assert saved["head"]["next_action"]["authority"] == "researcher"
    # The model-facing boundary cannot approve this candidate.  Only the
    # explicit researcher seam can move it to a preapproval terminal.
    _review(workspace)
    finalized = _finalize_assessment(
        workspace,
        int(_call(workspace, "get_status", {})["head"]["state_revision"]),
    )
    assert finalized["data"]["trial_dispositions"] == {"trial": "needs_input"}


def test_terminal_records_must_match_each_disposition_exactly(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    saved = _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [_unavailable_result(evidence, "Select the result.")]),
    )
    assert saved["outcome"] == "review_required"
    _review(workspace)
    finalized = _finalize_assessment(
        workspace,
        int(_call(workspace, "get_status", {})["head"]["state_revision"]),
    )
    artifact = workspace / str(finalized["data"]["artifact"]["path"])

    def duplicate(canonical: dict[str, Any]) -> None:
        terminals = canonical["terminals"]
        original = next(iter(terminals.values()))
        extra = dict(original)
        extra["reason"] = "A second terminal cannot replace the first."
        extra["identity"] = _identity(
            {key: value for key, value in extra.items() if key != "identity"}
        )
        terminals[extra["identity"]] = extra

    def orphan(canonical: dict[str, Any]) -> None:
        terminals = canonical["terminals"]
        original = next(iter(terminals.values()))
        extra = dict(original)
        extra["trial_id"] = "not-in-batch"
        extra["identity"] = _identity(
            {key: value for key, value in extra.items() if key != "identity"}
        )
        terminals[extra["identity"]] = extra

    for index, mutate in enumerate((duplicate, orphan)):
        tampered = tmp_path / f"terminal-tamper-{index}.rob2.zip"
        _rehashed_domain_tamper(artifact, tampered, mutate)
        assert not verify_bundle(tampered)
        assert _standalone_verify(tampered).returncode == 1


def test_adverse_event_grades_are_categories_and_grade_five_is_retained(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    ae_text = (
        "requested outcome; Treatment-emergent adverse events by grade. group a; "
        "events; participants; "
        "randomized participants; Any event; event; grade; grade_1; grade_2; grade_3; "
        "grade_4; grade_5; 65; 49; 7; 2; 1."
    )
    (workspace / "input" / "trial" / "ae.txt").write_text(ae_text, encoding="utf-8")
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["reported"] = {
        "form": "single_group_category_profile",
        "analysis_population": "randomized population",
        "endpoint": {
            "name": "requested outcome",
            "definition": "Treatment-emergent adverse events by grade.",
        },
        "group_id": "a",
        "denominator_basis": "randomized participants",
        "category_axis_names": ["event", "grade"],
        "categories": [
            {
                "category_axes": ["Any event", f"grade_{grade}"],
                "value": value,
            }
            for grade, value in ((1, "65"), (2, "49"), (3, "7"), (4, "2"), (5, "1"))
        ],
    }
    assert {group["id"] for group in result["target"]["comparison_groups"]} == {"a", "b"}
    assert result["reported"]["group_id"] == "a"
    source = next(
        item
        for item in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if item["label"] == "ae.txt"
    )
    _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": source["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )
    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert saved["outcome"] == "review_required", saved
    stored = _state(workspace)["review"]["candidate"]["proposal"]["results"][0]
    categories = stored["reported"]["categories"]
    assert [item["category_axes"] for item in categories] == [
        ["Any event", "grade_1"],
        ["Any event", "grade_2"],
        ["Any event", "grade_3"],
        ["Any event", "grade_4"],
        ["Any event", "grade_5"],
    ]
    assert [item["value"] for item in categories[:2]] == ["65", "49"]
    assert all(item["category_axes"] != ["treatment_effect"] for item in categories)

    result["reported"]["group_id"] = "phantom-group"
    invalid = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert invalid["outcome"] == "repair"
    assert any(item["code"] == "reported_group_id_not_in_target" for item in invalid["repairs"])

    _review(workspace)
    context = _call(workspace, "get_domain_context", {})
    reported = context["data"]["result"]["reported"]
    assert reported["categories"] == categories


def test_non_exact_result_binds_source_facts_but_not_caller_owned_target_leaves(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    evidence = _prepared_evidence(workspace)
    result = _result(evidence)
    result["relation"] = "related"
    result["relation_rationale"] = (
        "The Source reports a related endpoint with a different definition."
    )
    result["reported"]["endpoint"]["name"] = "alternate endpoint"
    result["reported"]["endpoint"]["definition"] = (
        "The requested outcome was measured in the analyzed population."
    )

    saved = _call(workspace, "save_proposal", _proposal_args(workspace, [result]))
    assert saved["outcome"] == "review_required"
    stored = _state(workspace)["review"]["candidate"]["proposal"]["results"][0]
    paths = {binding["field"]["path"] for binding in stored["bindings"]}
    assert "/target/outcome_definition" not in paths
    assert "/target/measurement/metric" not in paths
    assert "/target/effect_of_interest" not in paths
    assert "/target/comparison_groups/0/id" not in paths
    assert "/target/comparison_groups/1/id" not in paths
    assert "/target/comparison_groups/0/assignment" not in paths
    assert "/target/comparison_groups/1/assignment" not in paths
    assert "/target/time_point_or_window/description" not in paths
    assert "/target/measurement/method" not in paths
    assert "/reported/endpoint/name" in paths


def test_mixed_batch_has_authoritative_needs_input_and_assessed_dispositions(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    second = workspace / "input" / "trial-2"
    second.mkdir(parents=True)
    (second / "main.txt").write_text(
        "The requested outcome was not reported; only an alternate endpoint was measured. "
        "death ascertainment; end of follow-up; "
        "assigned to intervention; assigned to control; "
        "randomized population; risk ratio; The requested outcome was "
        "measured in the analyzed population.; risk; 1; events; 2.\n",
        encoding="utf-8",
    )
    prepared = _call(
        workspace,
        "prepare_batch",
        {
            "requested_outcome": "requested outcome",
            "expected_revision": 0,
        },
    )
    assert prepared["head"]["phase"] == "proposal"
    _read_required_main_reports(workspace)
    evidence: dict[str, dict[str, Any]] = {}
    for trial_id in ("trial", "trial-2"):
        source = _call(workspace, "list_sources", {"trial_id": trial_id})["data"]["sources"][0]
        evidence[trial_id] = _call(
            workspace,
            "select_text_evidence",
            {
                "trial_id": trial_id,
                "source_id": source["id"],
                "page": 1,
                "start_line": 1,
                "end_line": 1,
            },
        )["data"]["evidence"]
    ambiguous = _unavailable_result(
        evidence["trial"], "Researcher must select the intended result."
    )
    saved = _call(
        workspace,
        "save_proposal",
        _proposal_args(workspace, [ambiguous, _result_for_trial(evidence["trial-2"], "trial-2")]),
    )
    assert saved["outcome"] == "review_required"
    assert saved["head"]["next_action"]["purpose"] == "proposal"
    _review(workspace)
    _read_required_main_reports(workspace)
    status = _call(workspace, "get_status", {})
    assert status["data"]["trial_dispositions"] == {"trial": "needs_input", "trial-2": "pending"}
    assert status["head"]["next_action"]["operation"] == "get_domain_context"
    revision = int(
        _call(workspace, "get_domain_context", {"trial_id": "trial-2"})["head"]["state_revision"]
    )
    for domain in SCIENTIFIC_PACK.domains:
        saved_domain = _call(
            workspace,
            "save_domain_judgment",
            _domain_draft("trial-2", domain.id, revision, evidence["trial-2"]),
        )
        assert saved_domain["outcome"] == "success"
        revision = int(saved_domain["head"]["state_revision"])
    finalized = _finalize_assessment(workspace, revision)
    assert finalized["data"]["trial_dispositions"] == {
        "trial": "needs_input",
        "trial-2": "assessed",
    }
    assert verify_bundle(workspace / str(finalized["data"]["artifact"]["path"]))


def test_domain_save_query_work_is_bounded_by_irrelevant_evidence_handles(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    for index in range(32):
        (workspace / "input" / "trial" / f"appendix-{index}.txt").write_text(
            f"Independent passage {index}.\n", encoding="utf-8"
        )
    _call(
        workspace,
        "prepare_batch",
        {
            "requested_outcome": "requested outcome",
            "expected_revision": 0,
        },
    )
    _read_required_main_reports(workspace)
    for source in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]:
        _call(
            workspace,
            "select_text_evidence",
            {
                "trial_id": "trial",
                "source_id": source["id"],
                "page": 1,
                "start_line": 1,
                "end_line": 1,
            },
        )
    evidence = next(
        source
        for source in _call(workspace, "list_sources", {"trial_id": "trial"})["data"]["sources"]
        if source["label"] == "main.txt"
    )
    selected = _call(
        workspace,
        "select_text_evidence",
        {
            "trial_id": "trial",
            "source_id": evidence["id"],
            "page": 1,
            "start_line": 1,
            "end_line": 1,
        },
    )["data"]["evidence"]
    _call(workspace, "save_proposal", _proposal_args(workspace, [_result(selected)]))
    _review(workspace)
    _read_required_main_reports(workspace)
    context = _call(workspace, "get_domain_context", {})
    for name in COUNTERS:
        COUNTERS[name] = 0
    saved = _call(
        workspace,
        "save_domain_judgment",
        _domain_draft(
            "trial", SCIENTIFIC_PACK.domains[0].id, int(context["head"]["state_revision"]), selected
        ),
    )
    assert saved["outcome"] == "success"
    counters = COUNTERS
    # The mandatory post-approval report pass adds fixed status/read metadata queries;
    # the bound still catches work that scales with the 32 irrelevant handles.
    assert counters["database_queries"] < 60
